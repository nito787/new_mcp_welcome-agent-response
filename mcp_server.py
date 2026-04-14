import json
import os
import logging
from datetime import datetime
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp_server")

app = FastAPI()

demographics_store = []

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
    
    record = {
        "id": len(demographics_store) + 1,
        "preferred_name": preferred_name,
        "age": age,
        "consent": consent,
        "preferred_language": preferred_language,
        "communication_preference": communication_preference,
        "session_notes": session_notes,
        "user_communication_style": user_communication_style,
        "saved_at": datetime.now().isoformat()
    }
    
    demographics_store.append(record)
    
    save_to_file(record)
    
    return {
        "status": "saved",
        "id": record["id"],
        "preferred_name": preferred_name,
        "message": f"Demographics for {preferred_name} saved successfully."
    }

def get_demographics(record_id: int) -> dict:
    """Retrieve a saved demographics record by ID."""
    for record in demographics_store:
        if record["id"] == record_id:
            return record
    return {"status": "not_found", "message": f"No record found with id {record_id}"}

def list_all_demographics() -> dict:
    """List all saved demographic records."""
    return {
        "total": len(demographics_store),
        "records": demographics_store
    }

def save_to_file(record: dict):
    """Save record to a local JSON file for persistence."""
    file_path = "demographics_data.json"
    
    existing = []
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            existing = json.load(f)
    
    existing.append(record)
    
    with open(file_path, "w") as f:
        json.dump(existing, f, indent=2)


def _jsonrpc_result(request_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_error(request_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


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
        logger.info("Incoming MCP request: %s", body)
    except Exception:
        return JSONResponse(
            status_code=400,
            content=_jsonrpc_error(None, -32700, "Parse error"),
        )

    request_id = body.get("id")
    method = body.get("method")
    params = body.get("params", {})

    # Some MCP clients/proxies send wrapper-style method names instead of
    # canonical MCP JSON-RPC names. Normalize them for compatibility.
    method_aliases = {
        "mcp_initialize": "initialize",
        "mcp_list_tools": "tools/list",
        "mcp_call_tool": "tools/call",
    }
    method = method_aliases.get(method, method)

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
        return _jsonrpc_result(
            request_id,
            {
                "tools": [
                    {
                        "name": "save_demographics",
                        "description": "Save user demographics collected by the welcome agent.",
                        "inputSchema": {
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
                        },
                    },
                    {
                        "name": "get_demographics",
                        "description": "Retrieve a saved demographics record by ID.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"record_id": {"type": "integer"}},
                            "required": ["record_id"],
                        },
                    },
                    {
                        "name": "list_all_demographics",
                        "description": "List all saved demographic records.",
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                ]
            },
        )

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
            {"content": [{"type": "text", "text": json.dumps(result)}], "isError": False},
        )

    return _jsonrpc_error(request_id, -32601, f"Method not found: {method}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    logger.info("Starting JSON MCP server on 0.0.0.0:%s", port)
    uvicorn.run(app, host="0.0.0.0", port=port)