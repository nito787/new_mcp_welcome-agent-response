from mcp.server.fastmcp import FastMCP
import json
import os
import uvicorn
from datetime import datetime

mcp = FastMCP("mental-health-mcp")
app = mcp.streamable_http_app()

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