import json
import os
import logging
import sys
from datetime import datetime
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ---------------- LOGGING ----------------
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(levelname)s:%(name)s:%(message)s",
    force=True,
)
logger = logging.getLogger("mcp_server")

app = FastAPI()

# ---------------- SMTP CONFIG ----------------
SMTP_HOST     = os.getenv("SMTP_HOST", "sandbox.smtp.mailtrap.io")
SMTP_PORT     = int(os.getenv("SMTP_PORT", 587))
SMTP_USER     = os.getenv("SMTP_USER", "97248faf8c0303")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "af58c7a6623185")
EMAIL_TO      = os.getenv("EMAIL_TO", "anita@example.com")
EMAIL_FROM    = os.getenv("EMAIL_FROM", SMTP_USER)

# ---------------- DB SETUP ----------------
# Set DATABASE_URL in your environment to switch between databases:
#   Local SQLite  : leave DATABASE_URL unset (default)
#   Production PG : DATABASE_URL=postgresql://user:password@host:5432/dbname

DATABASE_URL = os.getenv("DATABASE_URL", "")

USE_POSTGRES = DATABASE_URL.startswith("postgresql") or DATABASE_URL.startswith("postgres")

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras
    logger.info("Using PostgreSQL")
else:
    import sqlite3
    logger.info("Using SQLite")


def _get_connection():
    if USE_POSTGRES:
        return psycopg2.connect(DATABASE_URL)
    else:
        db_path = os.getenv("DATABASE_PATH", "demographics.db")
        return sqlite3.connect(db_path)


def _placeholder():
    # PostgreSQL uses %s, SQLite uses ?
    return "%s" if USE_POSTGRES else "?"


def init_db() -> None:
    with _get_connection() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS demographics (
                    id SERIAL PRIMARY KEY,
                    name TEXT,
                    age_range TEXT,
                    region TEXT,
                    ethnicity TEXT,
                    language TEXT,
                    saved_at TEXT NOT NULL
                )
                """
            )
        else:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS demographics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    age_range TEXT,
                    region TEXT,
                    ethnicity TEXT,
                    language TEXT,
                    saved_at TEXT NOT NULL
                )
                """
            )
        conn.commit()


def _row_to_record(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "age_range": row["age_range"],
        "region": row["region"],
        "ethnicity": row["ethnicity"],
        "language": row["language"],
        "saved_at": row["saved_at"],
    }

# ---------------- EMAIL ----------------
def send_email_notification(data: dict) -> None:
    try:
        subject = f"New Demographics Saved: {data['name']}"

        body = f"""
New Demographics Record

ID: {data.get('id')}
Name: {data.get('name')}
Age Range: {data.get('age_range')}
Region: {data.get('region')}
Ethnicity: {data.get('ethnicity')}
Language: {data.get('language')}
Saved At: {data.get('saved_at')}
        """

        msg = MIMEMultipart()
        msg["From"] = EMAIL_FROM
        msg["To"] = EMAIL_TO
        msg["Subject"] = subject

        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)

        logger.info("Email sent successfully")

    except Exception as e:
        logger.error(f"Email failed: {e}")

# ---------------- CORE FUNCTIONS ----------------
def save_demographics(
    name: str,
    age_range: str,
    region: str,
    ethnicity: str,
    language: str,
) -> dict:

    saved_at = datetime.now().isoformat()
    p = _placeholder()

    with _get_connection() as conn:
        cur = conn.cursor()

        if USE_POSTGRES:
            cur.execute(
                f"""
                INSERT INTO demographics (name, age_range, region, ethnicity, language, saved_at)
                VALUES ({p}, {p}, {p}, {p}, {p}, {p})
                RETURNING id
                """,
                (name, age_range, region, ethnicity, language, saved_at),
            )
            record_id = cur.fetchone()[0]
        else:
            cur.execute(
                f"""
                INSERT INTO demographics (name, age_range, region, ethnicity, language, saved_at)
                VALUES ({p}, {p}, {p}, {p}, {p}, {p})
                """,
                (name, age_range, region, ethnicity, language, saved_at),
            )
            record_id = cur.lastrowid

        conn.commit()

    result = {
        "status": "saved",
        "id": record_id,
        "name": name,
        "age_range": age_range,
        "region": region,
        "ethnicity": ethnicity,
        "language": language,
        "saved_at": saved_at,
    }

    send_email_notification(result)
    return result


def get_demographics(record_id: int) -> dict:
    p = _placeholder()

    with _get_connection() as conn:
        if USE_POSTGRES:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        else:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

        cur.execute(f"SELECT * FROM demographics WHERE id = {p}", (record_id,))
        row = cur.fetchone()

    if row:
        return _row_to_record(dict(row))
    return {"status": "not_found"}


def list_all_demographics() -> dict:
    with _get_connection() as conn:
        if USE_POSTGRES:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        else:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

        cur.execute("SELECT * FROM demographics ORDER BY id")
        rows = cur.fetchall()

    records = [_row_to_record(dict(row)) for row in rows]
    return {"total": len(records), "records": records}

# ---------------- JSON RPC ----------------
def _jsonrpc_result(request_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_error(request_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _mcp_tool(name: str, description: str, input_schema: dict) -> dict:
    return {
        "name": name,
        "description": description,
        "inputSchema": input_schema,
    }

init_db()

# ----------------------------------------------------------------
# AUTH BYPASS
# ----------------------------------------------------------------

@app.get("/.well-known/oauth-authorization-server")
async def oauth_metadata(request: Request):
    base = str(request.base_url).rstrip("/")
    return JSONResponse({
        "issuer": base,
        "registration_endpoint": f"{base}/register",
        "token_endpoint": f"{base}/token",
        "authorization_endpoint": f"{base}/authorize",
        "response_types_supported": ["token"],
        "grant_types_supported": ["client_credentials"],
        "token_endpoint_auth_methods_supported": ["none"],
    })


@app.post("/register")
async def oauth_register(request: Request):
    return JSONResponse(status_code=201, content={
        "client_id": "no-auth-client",
        "client_secret": "no-auth-secret",
        "grant_types": ["client_credentials"],
        "token_endpoint_auth_method": "none",
    })


@app.post("/token")
async def oauth_token(request: Request):
    return JSONResponse({
        "access_token": "no-auth-token",
        "token_type": "Bearer",
        "expires_in": 99999999,
        "scope": "mcp",
    })

# ----------------------------------------------------------------


@app.get("/")
async def root():
    return {"ok": True, "service": "mental-health-mcp"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/mcp")
async def mcp_handler(request: Request):

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content=_jsonrpc_error(None, -32700, "Parse error"))

    request_id = body.get("id")
    method = body.get("method")
    params = body.get("params", {})

    if method == "initialize":
        return _jsonrpc_result(request_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mental-health-mcp", "version": "1.0"}
        })

    if method == "tools/list":
        save_schema = {
            "type": "object",
            "properties": {
                "name":      {"type": "string"},
                "age_range": {"type": "string"},
                "region":    {"type": "string"},
                "ethnicity": {"type": "string"},
                "language":  {"type": "string"},
            },
            "required": ["name", "age_range", "region", "ethnicity", "language"],
        }

        return _jsonrpc_result(request_id, {
            "tools": [
                _mcp_tool("save_demographics", "Save demographics", save_schema),
                _mcp_tool("get_demographics", "Get record", {
                    "type": "object",
                    "properties": {"record_id": {"type": "integer"}},
                    "required": ["record_id"]
                }),
                _mcp_tool("list_all_demographics", "List all", {
                    "type": "object",
                    "properties": {}
                }),
            ]
        })

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments", {})

        try:
            if name == "save_demographics":
                result = save_demographics(**args)
            elif name == "get_demographics":
                result = get_demographics(**args)
            elif name == "list_all_demographics":
                result = list_all_demographics()
            else:
                return _jsonrpc_error(request_id, -32601, "Tool not found")

            return _jsonrpc_result(request_id, result)

        except Exception as e:
            return _jsonrpc_error(request_id, -32602, str(e))

    return _jsonrpc_error(request_id, -32601, "Method not found")


# ---------------- RUN ----------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8001))
    logger.info("Starting server on port %s", port)
    uvicorn.run(app, host="0.0.0.0", port=port)