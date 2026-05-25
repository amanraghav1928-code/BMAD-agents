"""
BMAD MCP HTTP Server
====================
Exposes BMAD tools over both REST and MCP protocol (for LiteLLM playground).

GET  /health         →  health check
GET  /tools          →  list all tools (REST)
POST /tools/call     →  call a tool (REST)
*    /mcp            →  MCP protocol endpoint (for LiteLLM MCP Servers)
"""

import os, sys
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, Optional

load_dotenv(Path(__file__).parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent))

from server import (
    ask_pipeline,
    get_agent_performance,
    get_model_usage,
    get_recent_activity,
    compare_agents,
    get_pipeline_health,
    search_sessions,
)

# ── FastMCP server (MCP protocol) ─────────────────────────────────────────────
from fastmcp import FastMCP

mcp = FastMCP("BMAD Intelligence")

@mcp.tool()
def ask_pipeline_tool(question: str) -> str:
    """Ask any question about your BMAD pipeline in plain English. E.g. 'Which agent is slowest?'"""
    return str(ask_pipeline(question))

@mcp.tool()
def get_agent_performance_tool(agent_name: str = "") -> str:
    """Get performance stats for a specific agent or all agents. Leave agent_name blank for all."""
    return str(get_agent_performance(agent_name))

@mcp.tool()
def get_model_usage_tool(model_name: str = "") -> str:
    """See how many traces each model has generated. Leave model_name blank for all."""
    return str(get_model_usage(model_name))

@mcp.tool()
def get_recent_activity_tool(limit: int = 10) -> str:
    """Get a summary of the most recent pipeline runs."""
    return str(get_recent_activity(limit))

@mcp.tool()
def compare_agents_tool(agent1: str, agent2: str) -> str:
    """Compare performance between two agents side by side."""
    return str(compare_agents(agent1, agent2))

@mcp.tool()
def get_pipeline_health_tool() -> str:
    """Get an overall health report of your entire BMAD pipeline."""
    return str(get_pipeline_health())

@mcp.tool()
def search_sessions_tool(keyword: str) -> str:
    """Search pipeline sessions by project keyword e.g. 'stock', 'inventory'."""
    return str(search_sessions(keyword))


# ── FastAPI app ────────────────────────────────────────────────────────────────
app = FastAPI(title="BMAD MCP Server", version="2.0.0")

# Mount MCP protocol at /mcp (LiteLLM connects here)
app.mount("/mcp", mcp.http_app())


# ── REST endpoints (kept for backward compatibility) ──────────────────────────
TOOLS = [
    {"name": "ask_pipeline", "description": "Ask any question about your BMAD pipeline in plain English.", "parameters": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}},
    {"name": "get_agent_performance", "description": "Get performance stats for a specific agent or all agents.", "parameters": {"type": "object", "properties": {"agent_name": {"type": "string"}}, "required": []}},
    {"name": "get_model_usage", "description": "See how many traces each model has generated.", "parameters": {"type": "object", "properties": {"model_name": {"type": "string"}}, "required": []}},
    {"name": "get_recent_activity", "description": "Get a summary of recent pipeline runs.", "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}, "required": []}},
    {"name": "compare_agents", "description": "Compare performance between two agents.", "parameters": {"type": "object", "properties": {"agent1": {"type": "string"}, "agent2": {"type": "string"}}, "required": ["agent1", "agent2"]}},
    {"name": "get_pipeline_health", "description": "Get an overall health report of your pipeline.", "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "search_sessions", "description": "Search pipeline sessions by keyword.", "parameters": {"type": "object", "properties": {"keyword": {"type": "string"}}, "required": ["keyword"]}},
]

class ToolCallRequest(BaseModel):
    name: str
    arguments: Optional[dict] = {}

@app.get("/health")
def health():
    return {"status": "ok", "service": "bmad-mcp-server", "tools": len(TOOLS), "mcp_endpoint": "/mcp"}

@app.get("/tools")
def list_tools():
    return {"tools": TOOLS}

@app.post("/tools/call")
def call_tool(req: ToolCallRequest):
    args = req.arguments or {}
    try:
        if req.name == "ask_pipeline":
            result = ask_pipeline(args.get("question", ""))
        elif req.name == "get_agent_performance":
            result = get_agent_performance(args.get("agent_name", ""))
        elif req.name == "get_model_usage":
            result = get_model_usage(args.get("model_name", ""))
        elif req.name == "get_recent_activity":
            result = get_recent_activity(args.get("limit", 10))
        elif req.name == "compare_agents":
            result = compare_agents(args.get("agent1", ""), args.get("agent2", ""))
        elif req.name == "get_pipeline_health":
            result = get_pipeline_health()
        elif req.name == "search_sessions":
            result = search_sessions(args.get("keyword", ""))
        else:
            raise HTTPException(status_code=404, detail=f"Tool '{req.name}' not found")
        return {"result": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tool error: {str(e)}")
