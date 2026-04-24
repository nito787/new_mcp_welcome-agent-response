import json
import os
import logging
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
logger = logging.getLogger("demographic_server")

app = FastAPI()

# ── Email config (set via environment variables) ──────────────────────────────
SMTP_HOST     = os.getenv("SMTP_HOST", "sandbox.smtp.mailtrap.io")
SMTP_PORT     = int(os.getenv("SMTP_PORT", 587))
SMTP_USER     = os.getenv("SMTP_USER", "97248faf8c0303")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "af58c7a6623185")
EMAIL_TO      = os.getenv("EMAIL_TO", "anita@example.com")

# ── In-memory session store ────────────────────────────────────────────────────
from dataclasses import dataclass, field, asdict
from typing import Optional

@dataclass
class Session:
    session_id: str
    name: Optional[str] = None
    gender: Optional[str] = None
    age_range: Optional[str] = None
    region: Optional[str] = None
    ethnicity: Optional[str] = None
    language: Optional[str] = None
    preferred_channel: Optional[str] = None

_sessions: dict[str, Session] = {}

def _get_or_create(session_id: str) -> Session:
    if session_id not in _sessions:
        _sessions[session_id] = Session(session_id=session_id)
    return _sessions[session_id]

# ── Email helper ───────────────────────────────────────────────────────────────
def _send_email(subject: str, body: str) -> bool:
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        msg = MIMEMultipart()
        msg["From"]    = SMTP_USER
        msg["To"]      = EMAIL_TO
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, EMAIL_TO, msg.as_string())
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False

# ── Tool functions ─────────────────────────────────────────────────────────────
def save_demographics(
    session_id: str,
    name: Optional[str] = None,
    gender: Optional[str] = None,
    age_range: Optional[str] = None,
    region: Optional[str] = None,
    ethnicity: Optional[str] = None,
    language: Optional[str] = None,
    preferred_channel: Optional[str] = None,
) -> dict:
    """Save user demographics and send them via email."""
    session = _get_or_create(session_id)

    # Update only provided fields
    if name:             session.name              = name
    if gender:           session.gender            = gender
    if age_range:        session.age_range         = age_range
    if region:           session.region            = region
    if ethnicity:        session.ethnicity         = ethnicity
    if language:         session.language          = language
    if preferred_channel: session.preferred_channel = preferred_channel

    body = f"""
Demographics saved — Session: {session_id}

Name:              {session.name or 'Not provided'}
Gender:            {session.gender or 'Not provided'}
Age Range:         {session.age_range or 'Not provided'}
Region:            {session.region or 'Not provided'}
Ethnicity:         {session.ethnicity or 'Not provided'}
Language:          {session.language or 'Not provided'}
Preferred Channel: {session.preferred_channel or 'Not provided'}
    """.strip()

    ok = _send_email(f"[Demographics] Session {session_id}", body)
    return {
        "status": "saved" if ok else "saved_locally",
        "session_id": session_id,
        "message": "Demographics saved and emailed." if ok else "Demographics saved locally but email failed.",
        "emailed": ok
    }


def get_demographics(session_id: str) -> dict:
    """Retrieve stored demographics for a given session."""
    session = _sessions.get(session_id)
    if not session or (not session.name and not session.region):
        return {"status": "not_found", "message": f"No demographics found for session {session_id}"}

    return {
        "status": "found",
        "session_id": session_id,
        "demographics": {
            "name": session.name,
            "gender": session.gender,
            "age_range": session.age_range,
            "region": session.region,
            "ethnicity": session.ethnicity,
            "language": session.language,
            "preferred_channel": session.preferred_channel
        }
    }


def check_demographics_complete(session_id: str) -> dict:
    """Check if all required demographics have been collected."""
    session = _sessions.get(session_id)
    if not session:
        return {"status": "not_found", "message": f"Session {session_id} not found."}

    required = {
        "Name": session.name,
        "Gender": session.gender,
        "Age Range": session.age_range,
        "Region": session.region,
        "Ethnicity": session.ethnicity,
    }
    missing = [k for k, v in required.items() if not v]

    return {
        "session_id": session_id,
        "complete": not missing,
        "missing": missing if missing else None
    }


def send_complete_session(session_id: str) -> str:
    """Send the full session data via email."""
    session = _sessions.get(session_id)
    if not session or (not session.name and not session.region):
        return {"status": "error", "message": f"Cannot send — no demographics for session {session_id}."}

    data = asdict(session)
    body = "Complete Session Report\n" + "=" * 40 + "\n"
    for k, v in data.items():
        body += f"{k.replace('_', ' ').title()}: {v or 'Not provided'}\n"

    ok = _send_email(f"[Complete Session] {session_id}", body)
    return {
        "status": "sent" if ok else "failed",
        "session_id": session_id,
        "message": "Complete session emailed." if ok else "Failed to send email."
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


@app.get("/")
async def root():
    return {
        "ok": True,
        "service": "demographic-server",
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
                "serverInfo": {"name": "demographic-server", "version": "1.0.0"},
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
                "session_id": {"type": "string"},
                "name": {"type": "string"},
                "gender": {"type": "string"},
                "age_range": {"type": "string"},
                "region": {"type": "string"},
                "ethnicity": {"type": "string"},
                "language": {"type": "string"},
                "preferred_channel": {"type": "string"},
            },
            "required": ["session_id"],
        }
        get_schema = {
            "type": "object",
            "properties": {"session_id": {"type": "string"}},
            "required": ["session_id"],
        }
        check_schema = {
            "type": "object",
            "properties": {"session_id": {"type": "string"}},
            "required": ["session_id"],
        }
        send_schema = {
            "type": "object",
            "properties": {"session_id": {"type": "string"}},
            "required": ["session_id"],
        }
        tools_payload = {
            "tools": [
                _mcp_tool(
                    "save_demographics_mail",
                    "Save user demographics and send them via email.",
                    save_schema,
                ),
                _mcp_tool(
                    "get_demographics_mail",
                    "Retrieve stored demographics for a given session.",
                    get_schema,
                ),
                _mcp_tool(
                    "check_demographics_complete_mail",
                    "Check if all required demographics have been collected.",
                    check_schema,
                ),
                _mcp_tool(
                    "send_complete_session_mail",
                    "Send the full session data via email.",
                    send_schema,
                ),
            ]
        }
        return JSONResponse(content=_jsonrpc_result(request_id, tools_payload))

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments", {})
        try:
            if name == "save_demographics_mail":
                result = save_demographics(**arguments)
            elif name == "get_demographics_mail":
                result = get_demographics(**arguments)
            elif name == "check_demographics_complete_mail":
                result = check_demographics_complete(**arguments)
            elif name == "send_complete_session_mail":
                result = send_complete_session(**arguments)
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
    port = int(os.environ.get("PORT", 8000))
    logger.info("Starting demographic server on 0.0.0.0:%s", port)
    uvicorn.run(app, host="0.0.0.0", port=port)