# Talk2DB v2

Talk to your MySQL database in plain English. Powered by a local agentic pipeline using Mistral 7B via Ollama.

## How it works

Instead of dumping everything into one prompt, Talk2DB v2 runs a 5-stage pipeline:

1. **Table Selector** — picks only the relevant tables for your query
2. **Query Planner** — reasons in plain English before writing any SQL
3. **SQL Generator** — generates SQL against the plan, with real sampled column values
4. **Retry Executor** — auto-retries up to 3 times if the query fails
5. **Dual Explainer** — explains what the SQL does and what the result means

## Stack

Flask · React · MySQL · Ollama (Mistral 7B) · sqlparse

## Setup

**Backend**
```bash
pip install flask flask-cors flask-session mysql-connector-python sqlparse requests
python app.py
```

**Frontend**
```bash
cd frontend
npm install
npm start
```

Make sure Ollama is running with Mistral pulled:
```bash
ollama pull mistral:7b-instruct
ollama serve
```

## Usage

1. Open `http://localhost:3000`
2. Enter your MySQL credentials and database name
3. Ask questions in plain English
