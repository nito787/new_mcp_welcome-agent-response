from mcp.server.fastmcp import FastMCP
import json
import os
import uvicorn
from datetime import datetime

from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

# FastMCP defaults host=127.0.0.1, which enables DNS rebinding protection with
# Host allowed only for localhost. Railway sends Host: <name>.up.railway.app → "Invalid Host header".
# Binding metadata host to 0.0.0.0 skips that default so public deployments work.
_mcp_host = os.getenv("FASTMCP_HOST", "0.0.0.0")
mcp = FastMCP("mental-health-mcp", host=_mcp_host)
app = mcp.streamable_http_app()

# Some hosted MCP clients still use HTTP-over-SSE (GET /sse + POST /messages/).
# Expose the same FastMCP instance on both transports so discovery can fall back.
_sse_starlette = mcp.sse_app()
for _route in _sse_starlette.routes:
    app.routes.append(_route)


async def _health(request):
    return PlainTextResponse("ok")


async def _root(request):
    return JSONResponse(
        {
            "ok": True,
            "service": "mental-health-mcp",
            "mcp": "/mcp",
            "sse": "/sse",
            "messages": "/messages/",
            "health": "/health",
            "note": (
                "Opening /mcp in a browser is not supported. Streamable MCP requires an MCP client that sends "
                "Accept: text/event-stream on GET to /mcp, and Accept including both application/json and "
                "text/event-stream on POST with Content-Type: application/json. "
                "Clients that only support the older transport can use /sse and POST JSON-RPC to /messages/."
            ),
        }
    )


# Railway and browsers hit GET / — the MCP app only registers /mcp.
app.routes.insert(0, Route("/health", endpoint=_health, methods=["GET", "HEAD"]))
app.routes.insert(0, Route("/", endpoint=_root, methods=["GET", "HEAD"]))

demographics_store = []

@mcp.tool()
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

@mcp.tool()
def get_demographics(record_id: int) -> dict:
    """Retrieve a saved demographics record by ID."""
    for record in demographics_store:
        if record["id"] == record_id:
            return record
    return {"status": "not_found", "message": f"No record found with id {record_id}"}

@mcp.tool()
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

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)