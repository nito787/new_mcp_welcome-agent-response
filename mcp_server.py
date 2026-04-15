import json
import os
import logging
import sqlite3
import sys
from datetime import datetime
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(levelname)s:%(name)s:%(message)s",
    force=True,
)
logger = logging.getLogger("mcp_server")

app = FastAPI()

DB_PATH = os.environ.get("DB_PATH", "demographics.db")


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS demographics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                preferred_name TEXT NOT NULL,
                age TEXT NOT NULL,
                consent INTEGER NOT NULL,
                preferred_language TEXT NOT NULL,
                communication_preference TEXT NOT NULL,
                session_notes TEXT NOT NULL DEFAULT '',
                user_communication_style TEXT NOT NULL DEFAULT '',
                saved_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def _row_to_record(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "preferred_name": row["preferred_name"],
        "age": row["age"],
        "consent": bool(row["consent"]),
        "preferred_language": row["preferred_language"],
        "communication_preference": row["communication_preference"],
        "session_notes": row["session_notes"],
        "user_communication_style": row["user_communication_style"],
        "saved_at": row["saved_at"],
    }

def save_demographics(
    preferred_name: str,
    age: str,
    consent: bool,
    preferred_language: str,
    communication_preference: str,
    session_notes: str = "",
    user_communication_style: str = ""
) -> dict:
    """Save user demographics collected by the welcome agent."""
    saved_at = datetime.now().isoformat()
    with _get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO demographics (
                preferred_name,
                age,
                consent,
                preferred_language,
                communication_preference,
                session_notes,
                user_communication_style,
                saved_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                preferred_name,
                age,
                int(consent),
                preferred_language,
                communication_preference,
                session_notes,
                user_communication_style,
                saved_at,
            ),
        )
        conn.commit()
        record_id = cursor.lastrowid

    return {
        "status": "saved",
        "id": record_id,
        "preferred_name": preferred_name,
        "message": f"Demographics for {preferred_name} saved successfully."
    }

def get_demographics(record_id: int) -> dict:
    """Retrieve a saved demographics record by ID."""
    with _get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM demographics WHERE id = ?",
            (record_id,),
        ).fetchone()
    if row:
        return _row_to_record(row)
    return {"status": "not_found", "message": f"No record found with id {record_id}"}

def list_all_demographics() -> dict:
    """List all saved demographic records."""
    with _get_connection() as conn:
        rows = conn.execute("SELECT * FROM demographics ORDER BY id").fetchall()
    records = [_row_to_record(row) for row in rows]
    return {
        "total": len(records),
        "records": records
    }


def _jsonrpc_result(request_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_error(request_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _mcp_tool(name: str, description: str, input_schema: dict) -> dict:
    """Build a Tool dict; duplicate schema keys for clients that rename camelCase."""
    schema_copy = json.loads(json.dumps(input_schema))
    return {
        "name": name,
        "description": description,
        "inputSchema": input_schema,
        "input_schema": schema_copy,
    }


init_db()


@app.get("/")
async def root():
    return {
        "ok": True,
        "service": "mental-health-mcp",
        "mcp": "/mcp",
        "health": "/health",
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/mcp")
@app.post("/mcp/mcp_handler")
async def mcp_handler(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content=_jsonrpc_error(None, -32700, "Parse error"),
        )

    request_id = body.get("id")
    method = body.get("method")
    raw_params = body.get("params")
    params = raw_params if isinstance(raw_params, dict) else {}

    # Some MCP clients/proxies send wrapper-style method names instead of
    # canonical MCP JSON-RPC names. Normalize only known wrappers.
    method_aliases = {
        "mcp_initialize": "initialize",
        "mcp_list_tools": "tools/list",
        "mcp_call_tool": "tools/call",
    }
    canonical_methods = {
        "initialize",
        "notifications/initialized",
        "tools/list",
        "tools/call",
    }
    if method not in canonical_methods and method in method_aliases:
        method = method_aliases[method]

    # MCP initialize handshake
    if method == "initialize":
        return _jsonrpc_result(
            request_id,
            {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "mental-health-mcp", "version": "1.0.0"},
                "capabilities": {"tools": {}},
            },
        )

    if method == "notifications/initialized":
        return JSONResponse(status_code=202, content={})

    if method == "tools/list":
        # MCP: canonical key is inputSchema (object with type "object"). Some proxies
        # expose snake_case only; include input_schema as a copy for compatibility.
        save_schema = {
            "type": "object",
            "properties": {
                "preferred_name": {"type": "string"},
                "age": {"type": "string"},
                "consent": {"type": "boolean"},
                "preferred_language": {"type": "string"},
                "communication_preference": {"type": "string"},
                "session_notes": {"type": "string"},
                "user_communication_style": {"type": "string"},
            },
            "required": [
                "preferred_name",
                "age",
                "consent",
                "preferred_language",
                "communication_preference",
            ],
        }
        get_schema = {
            "type": "object",
            "properties": {"record_id": {"type": "integer"}},
            "required": ["record_id"],
        }
        list_schema = {"type": "object", "properties": {}}
        tools_payload = {
            "tools": [
                _mcp_tool(
                    "save_demographics",
                    "Save user demographics collected by the welcome agent.",
                    save_schema,
                ),
                _mcp_tool(
                    "get_demographics",
                    "Retrieve a saved demographics record by ID.",
                    get_schema,
                ),
                _mcp_tool(
                    "list_all_demographics",
                    "List all saved demographic records.",
                    list_schema,
                ),
            ]
        }
        return JSONResponse(content=_jsonrpc_result(request_id, tools_payload))

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments", {})
        try:
            if name == "save_demographics":
                result = save_demographics(**arguments)
            elif name == "get_demographics":
                result = get_demographics(**arguments)
            elif name == "list_all_demographics":
                result = list_all_demographics()
            else:
                return _jsonrpc_error(request_id, -32601, f"Tool not found: {name}")
        except Exception as exc:
            return _jsonrpc_error(request_id, -32602, f"Invalid params: {exc}")

        return _jsonrpc_result(
            request_id,
             result,
        )

    return _jsonrpc_error(request_id, -32601, f"Method not found: {method}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8001))
    logger.info("Starting JSON MCP server on 0.0.0.0:%s", port)
    uvicorn.run(app, host="0.0.0.0", port=port)