from flask import Flask, request, jsonify, session
from flask_cors import CORS
from flask_session import Session
import mysql.connector
import requests
import sqlparse
import re
import os
import json 

app = Flask(__name__)
app.secret_key = "talk2db_secret"
app.config["SESSION_TYPE"] = "filesystem"
Session(app)
CORS(app, supports_credentials=True)

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "mistral:7b-instruct"


# ─────────────────────────────────────────────
# LLM CALL
# ─────────────────────────────────────────────

def ask_llm(prompt, temperature=0.2, max_tokens=400,system=None):
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    try:
        response = requests.post(OLLAMA_URL, json={
            "model": MODEL,
            "prompt":full_prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens
            }
        })
        return response.json()["response"].strip()
    except Exception as e:
        raise RuntimeError(f"LLM call failed: {str(e)}")


def detect_relationships(schema):
    schema_text = format_schema_for_prompt(schema)
    
    prompt = f"""Analyze this database schema and identify relationships between tables.

Schema:
{schema_text}

Rules:
- Look for columns that likely reference other tables (foreign keys, shared IDs, matching names)
- Identify if relationship is one-to-one, one-to-many, or many-to-many
- Only include relationships you are confident about
- If no relationships exist, return an empty list

Return ONLY a JSON array in this exact format, nothing else:
[
  {{
    "from_table": "orders",
    "from_column": "student_id",
    "to_table": "students",
    "to_column": "id",
    "type": "many-to-one",
    "label": "each order belongs to one student"
  }}
]

JSON:"""

    raw = ask_llm(
        prompt,
        temperature=0.1,
        max_tokens=400,
        system="You are a database schema analyst. Output ONLY valid JSON. No explanation, no markdown, no preamble."
    )
    
    # Safely parse JSON response
    try:
        # Strip markdown if model adds it anyway
        raw = re.sub(r"```json|```", "", raw, flags=re.IGNORECASE).strip()
        relationships = json.loads(raw)
        if not isinstance(relationships, list):
            return []
        return relationships
    except json.JSONDecodeError:
        # LLM returned malformed JSON — return empty rather than crash
        print(f"[WARN] Could not parse relationships JSON: {raw}")
        return []

def explain_schema(schema):
    schema_text = format_schema_for_prompt(schema)

    prompt = f"""Given this database schema:
{schema_text}

1. For each table, write one sentence explaining what real-world entity it represents and what data it stores.
2. Describe how the tables relate to each other in plain English.

Write for someone who doesn't know SQL. Be concise.

Explanation:"""

    return ask_llm(
        prompt,
        temperature=0.3,
        max_tokens=400,
        system="You are a helpful database explainer. Write in simple, clear English."
    )
  
def sanitize_nl_query(query):
    # Block prompt injection patterns
    injection_patterns = [
        r"ignore (above|previous|all)",
        r"forget (above|previous|all)",
        r"(drop|delete|truncate|alter|insert|update)\s+table",
        r"you are now",
        r"new instruction",
        r"system prompt",
    ]
    lower = query.lower()
    for pattern in injection_patterns:
        if re.search(pattern, lower):
            raise ValueError("Query contains disallowed patterns.")
    if len(query) > 500:
        raise ValueError("Query too long.")
    return query.strip()



# ─────────────────────────────────────────────
# SCHEMA + VALUE SAMPLING
# ─────────────────────────────────────────────

def get_db_schema_with_samples(config):
    """
    Fetch schema and sample low-cardinality column values.
    This solves the problem where LLM doesn't know actual stored values
    e.g., 'CSE' vs 'Computer Science' vs 'cse'
    """
    conn = mysql.connector.connect(**config)
    cursor = conn.cursor()

    cursor.execute("SHOW TABLES")
    tables = [row[0] for row in cursor.fetchall()]

    schema = {}

    for table in tables:
        cursor.execute(f"SHOW COLUMNS FROM `{table}`")
        columns = cursor.fetchall()

        col_info = {}
        for col in columns:
            col_name = col[0]
            col_type = col[1].lower()

            # Sample values only for text/enum/low-cardinality columns
            sample_values = []
            if any(t in col_type for t in ["char", "varchar", "enum", "text"]):
                try:
                    cursor.execute(
                        f"SELECT DISTINCT `{col_name}` FROM `{table}` LIMIT 8"
                    )
                    rows = cursor.fetchall()
                    sample_values = [str(r[0]) for r in rows if r[0] is not None]
                except:
                    pass

            col_info[col_name] = {
                "type": col_type,
                "samples": sample_values
            }

        schema[table] = col_info

    cursor.close()
    conn.close()
    return schema


def format_schema_for_prompt(schema, tables=None):
    """
    Format schema with sample values for LLM prompt.
    If tables list provided, only format those tables.
    """
    lines = []
    for table, cols in schema.items():
        if tables and table not in tables:
            continue
        col_parts = []
        for col_name, info in cols.items():
            part = col_name
            if info["samples"]:
                part += f" (e.g., {', '.join(info['samples'][:5])})"
            col_parts.append(part)
        lines.append(f"Table `{table}`: {', '.join(col_parts)}")
    return "\n".join(lines)


# ─────────────────────────────────────────────
# STAGE 1 — RELEVANT TABLE SELECTOR
# ─────────────────────────────────────────────

def select_relevant_tables(schema, nl_query):
    all_tables = list(schema.keys())
    schema_text = format_schema_for_prompt(schema)

    prompt = f"""

Schema:
{schema_text}

User query: "{nl_query}"

From the schema above, return ONLY the table names needed to answer this query.
Return as comma-separated names. No explanation. Only use table names from the schema.

Tables:"""

    response = ask_llm( 
            prompt, 
            temperature=0.1,
            max_tokens=50, 
            system="You are a database expert. Output ONLY comma-separated table names. No explanation, no preamble, nothing else.")

    selected = [t.strip().strip('`') for t in response.split(",")]
    valid = [t for t in selected if t in all_tables]

    # fallback to all tables if LLM fails
    print(valid)
    return valid if valid else all_tables


# ─────────────────────────────────────────────
# STAGE 2 — QUERY PLANNER
# ─────────────────────────────────────────────

def plan_query(schema, relevant_tables, nl_query):
    """
    LLM reasons about HOW to answer the query before writing SQL.
    This significantly improves complex query accuracy.
    """
    schema_text = format_schema_for_prompt(schema, tables=relevant_tables)

    prompt = f"""You are a SQL planning expert.

Schema:
{schema_text}

User query: "{nl_query}"

Write a short step-by-step plan (in plain English, no SQL yet) for how to answer this query.
Include:
- Which tables to use
- Which columns to filter, group, or sort
- Any JOINs needed
- Exact filter values to use based on the sample values shown

Plan:"""

    plan = ask_llm(prompt, temperature=0.2, max_tokens=200)
    return plan

def plan_query_with_error(schema, relevant_tables, nl_query, error_message):
    schema_text = format_schema_for_prompt(schema, tables=relevant_tables)

    prompt = f"""You are a SQL planning expert.

Schema:
{schema_text}

User query: "{nl_query}"

A previous attempt failed with this error:
{error_message}

Rewrite the plan to avoid this error. Be specific about exact column names and values to use.

Revised Plan:"""

    return ask_llm(prompt, temperature=0.2, max_tokens=200)

# ─────────────────────────────────────────────
# STAGE 3 — SQL GENERATOR WITH PLAN
# ─────────────────────────────────────────────

def extract_sql(raw_output):
    """Robustly extract SQL from LLM output — handles multi-line, markdown, etc."""

    # Remove markdown code blocks
    raw_output = re.sub(r"```sql|```", "", raw_output, flags=re.IGNORECASE).strip()

    # Try to find SELECT...  block
    match = re.search(r"(SELECT[\s\S]+?)(?:;|$)", raw_output, re.IGNORECASE)
    if match:
        return match.group(1).strip() + ";"

    # Fallback: return first non-empty line
    for line in raw_output.splitlines():
        if line.strip().upper().startswith("SELECT"):
            return line.strip()

    return raw_output.strip()


def validate_sql(sql):
    """Enforce read-only: only SELECT queries allowed."""
    parsed = sqlparse.parse(sql)
    if not parsed:
        raise ValueError("Could not parse SQL.")

    statement = parsed[0]
    stmt_type = statement.get_type()

    if stmt_type != "SELECT":
        raise ValueError(f"Only SELECT queries are allowed. Got: {stmt_type}")

    # Block dangerous keywords even inside SELECT (e.g., INTO OUTFILE)
    dangerous = ["INTO OUTFILE", "INTO DUMPFILE", "LOAD_FILE"]
    sql_upper = sql.upper()
    for keyword in dangerous:
        if keyword in sql_upper:
            raise ValueError(f"Blocked dangerous keyword: {keyword}")

    return True


def generate_sql(schema, relevant_tables, plan, nl_query, error_message="no error"):
    schema_text = format_schema_for_prompt(schema, tables=relevant_tables)

    prompt = f"""

Schema (with sample values):
{schema_text}

Query plan:
{plan}

User query: "{nl_query}"

Previous error: {error_message}

Rules:
- Only generate a single SELECT query
- No explanation, no markdown, no comments
- Use ONLY columns and tables from the schema
- Use exact values as shown in sample values (correct case, spelling)
- Fix the query if there was a previous error

SQL:"""

    raw = ask_llm(prompt, temperature=0.1, max_tokens=300,system="You are an expert MySQL developer. Output ONLY a raw SQL SELECT statement. No markdown, no explanation, no comments. Just the SQL.")
    return extract_sql(raw)


# ─────────────────────────────────────────────
# STAGE 4 — EXECUTOR WITH RETRY LOOP
# ─────────────────────────────────────────────

def apply_row_limit(sql, limit=500):
    """Inject LIMIT if not already present."""
    sql_stripped = sql.rstrip(';').strip()
    if not re.search(r'\bLIMIT\b', sql_stripped, re.IGNORECASE):
        sql_stripped += f" LIMIT {limit}"
    return sql_stripped + ";"

def execute_with_retry(config, schema, relevant_tables, nl_query, max_attempts=3):
    plan = plan_query(schema, relevant_tables, nl_query)

    error_message = "no error"
    last_sql = ""

    for attempt in range(max_attempts):

        if attempt > 0:
            plan = plan_query_with_error(schema, relevant_tables, nl_query, error_message)

        sql = generate_sql(schema, relevant_tables, plan, nl_query, error_message)
        last_sql = sql

        try:
            validate_sql(sql)
        except ValueError as ve:
            error_message = f"Validation error: {str(ve)}"
            continue

        try:
            conn = mysql.connector.connect(**config)
            cursor = conn.cursor()
            safe_sql = apply_row_limit(sql)
            cursor.execute(safe_sql)

            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            result = [dict(zip(columns, row)) for row in rows]

            cursor.close()
            conn.close()

            return {"sql": sql, "plan": plan, "result": result}

        except Exception as e:
            error_message = f"Query: {sql}\nError: {str(e)}"

    return {
        "error": "Failed to generate a valid query after retries.",
        "details": error_message,
        "last_sql": last_sql
    }


# ─────────────────────────────────────────────
# STAGE 5 — EXPLAINERS
# ─────────────────────────────────────────────

def explain_sql(sql, plan):
    prompt = f"""Explain this SQL query in simple, non-technical terms.

Query plan that was used:
{plan}

SQL:
{sql}

Explanation:"""
    return ask_llm(prompt, temperature=0.3, max_tokens=150)


def explain_result(nl_query, result):
    # Cap result size to avoid context overflow on local model
    limited = result[:5] if isinstance(result, list) else result
    capped = []
    for row in limited:
        capped_row = {k: str(v)[:100] for k, v in row.items()}
        capped.append(capped_row)

    prompt = f"""User asked: "{nl_query}"

Result (first few rows):
{capped}

Summarize this result in 2-3 simple sentences.

Summary:"""
    return ask_llm(prompt, temperature=0.3, max_tokens=150)


# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────

@app.route('/connect', methods=['POST'])
def connect_db():
    data = request.json
    config = {
        'host': 'localhost',
        'user': data.get('username'),
        'password': data.get('password'),
        'database': data.get('database'),
        'port': 3306
    }

    try:
        schema = get_db_schema_with_samples(config)

        # Cache in session — no need to re-fetch on every query
        session['db_config'] = config
        session['db_schema'] = schema

        # Return simplified summary for frontend display
        summary = {table: list(cols.keys()) for table, cols in schema.items()}
        return jsonify({"summary": summary})

    except Exception as e:
        return jsonify({"error": "Connection failed. Check credentials."}), 400


@app.route('/schema-info', methods=['GET'])
def schema_info():
    schema = session.get('db_schema')
    if not schema:
        return jsonify({"error": "Not connected."}), 401

    try:
        explanation = explain_schema(schema)
        relationships = detect_relationships(schema)
        summary = {table: list(cols.keys()) for table, cols in schema.items()}

        return jsonify({
            "summary": summary,
            "explanation": explanation,
            "relationships": relationships
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/query', methods=['POST'])
def handle_query():
    data = request.json
    nl_query = data.get('query', '').strip()

    try:
        nl_query = sanitize_nl_query(nl_query)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    

    if not nl_query:
        return jsonify({"error": "Query cannot be empty."}), 400

    # Load from session cache
    config = session.get('db_config')
    schema = session.get('db_schema')

    if not config or not schema:
        return jsonify({"error": "Not connected. Please connect to a database first."}), 401

    try:
        relevant_tables = select_relevant_tables(schema, nl_query)
        response = execute_with_retry(config, schema, relevant_tables, nl_query)

        if "error" in response:
            return jsonify(response), 200

        sql = response["sql"]
        plan = response["plan"]
        result = response["result"]

        sql_explanation = explain_sql(sql, plan)
        result_explanation = explain_result(nl_query, result)

        return jsonify({
            "sql": sql,
            "plan": plan,
            "sql_explanation": sql_explanation,
            "result": result,
            "result_explanation": result_explanation
        })

    except Exception as e:
        return jsonify({"error": "Something went wrong.", "details": str(e)}), 500


@app.route('/refresh-schema', methods=['POST'])
def refresh_schema():
    """Call this if the DB schema changes mid-session."""
    config = session.get('db_config')
    if not config:
        return jsonify({"error": "Not connected."}), 401

    try:
        schema = get_db_schema_with_samples(config)
        session['db_schema'] = schema
        summary = {table: list(cols.keys()) for table, cols in schema.items()}
        return jsonify({"summary": summary})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/disconnect', methods=['POST'])
def disconnect():
    session.clear()
    return jsonify({"message": "Disconnected."})


if __name__ == '__main__':
    app.run(port=5000, debug=True)