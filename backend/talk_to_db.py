from flask import Flask, request, jsonify
from flask_cors import CORS
import mysql.connector
import requests
import re

app = Flask(__name__)
CORS(app)

# Call to local LLM
def ask_llm(prompt):
    response = requests.post("http://localhost:11434/api/generate", json={
        "model": "mistral",
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,   # more deterministic
            "num_predict": 200    # limit tokens
        }
    })

    return response.json()["response"].strip()

# Get table & column summary
def get_db_summary(config):
    conn = mysql.connector.connect(**config)
    cursor = conn.cursor()

    cursor.execute("SHOW TABLES")
    tables = cursor.fetchall()

    summary = {}
    for (table,) in tables:
        cursor.execute(f"SHOW COLUMNS FROM `{table}`")
        columns = cursor.fetchall()
        summary[table] = [col[0] for col in columns]

    cursor.close()
    conn.close()
    return summary

    
def is_safe_query(sql):
    print("\n🛡️ Inside is_safe_query")
    print("Original SQL:", sql)

    import re
    sql = sql.strip().lower()
    print("Normalized SQL:", sql)

    sql = re.sub(r';+\s*$', '', sql)
    print("After removing trailing semicolon:", sql)

    if ";" in sql:
        print("❌ Found semicolon in middle")
        return False

    if not re.match(r'^select\b', sql):
        print("❌ Not starting with SELECT")
        return False

    forbidden = ["insert", "update", "delete", "drop", "alter", "truncate", "create"]

    for word in forbidden:
        if re.search(rf'\b{word}\b', sql):
            print(f"❌ Found forbidden keyword: {word}")
            return False

    print("✅ Query is SAFE")
    return True

def format_schema(summary):
    schema_text = ""
    for table, cols in summary.items():
        schema_text += f"Table {table}: {', '.join(cols)}\n"
    return schema_text

def select_relevant_schema(summary, nl_query):
    schema_text = format_schema(summary)

    prompt = f"""
    You are a database expert.

    Schema:
    {schema_text}

    User query:
    "{nl_query}"

    Return only relevant table names (comma-separated).
    Only choose from given table names. Do not invent tables.
    No explanation.
    """

    response = ask_llm(prompt)

    tables = [t.strip() for t in response.split(",")]

    selected = {t: summary[t] for t in tables if t in summary}

    # fallback if LLM fails
    return selected if selected else summary

def generate_sql_with_feedback(config, nl_query, max_attempts=3):
    summary = get_db_summary(config)
    relevant_schema = select_relevant_schema(summary, nl_query)

    schema_text = format_schema(relevant_schema)

    error_message = "no error"

    for attempt in range(max_attempts):
        prompt = f"""
        You are an expert MySQL query generator.

        Schema:
        {schema_text}

        User query:
        "{nl_query}"

        Previous error:
        {error_message}

        Rules:
        - Only SELECT queries
        - No explanation
        - No markdown
        - Use ONLY the provided schema.
        - Do not assume missing columns.
        - Fix the query based on the error. Do not repeat the same mistake.

        Generate SQL:
        """

        sql_query = ask_llm(prompt)
        print("\n🔍 RAW LLM OUTPUT:", sql_query)
        sql_query = sql_query.strip().split('\n')[0].strip('` ')
        print("🧹 CLEANED SQL:", sql_query)

        # 🛡️ Security Check
        print("🛡️ CHECKING SAFETY FOR:", sql_query)
        if not is_safe_query(sql_query):
            return {"error": "Unsafe query detected"}

        try:
            conn = mysql.connector.connect(**config)
            cursor = conn.cursor()
            cursor.execute(sql_query)

            if cursor.description:
                columns = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()
                result = [dict(zip(columns, row)) for row in rows]
            else:
                conn.commit()
                result = {"message": "Query executed"}

            cursor.close()
            conn.close()

            return {"sql": sql_query, "result": result}

        except Exception as e:
            error_message = str(e).split(":")[-1]

    return {"error": "Failed after retries", "details": error_message}

def explain_sql(sql):
    prompt = f"Explain this SQL query in simple terms:\n{sql}"
    return ask_llm(prompt)


def explain_result(nl_query, result):
    limited_result = result[:5] if isinstance(result, list) else result

    prompt = f"""
    User asked: "{nl_query}"

    Result:
    {limited_result}

    Explain this in simple terms.
    """
    return ask_llm(prompt)

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
        summary = get_db_summary(config)
        return jsonify(summary)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/query', methods=['POST'])
def handle_query():
    data = request.json

    config = {
        'host': 'localhost',
        'user': data.get('username'),
        'password': data.get('password'),
        'database': data.get('database'),
        'port': 3306
    }

    nl_query = data.get('query')

    response = generate_sql_with_feedback(config, nl_query)

    if "error" in response:
        return jsonify(response)

    sql = response["sql"]
    result = response["result"]

    # 🧠 Explanations
    sql_explanation = explain_sql(sql)
    result_explanation = explain_result(nl_query, result)

    return jsonify({
        "sql": sql,
        "result": result,
        "sql_explanation": sql_explanation,
        "result_explanation": result_explanation
    })

if __name__ == '__main__':
    app.run(port=5000, debug=True)
