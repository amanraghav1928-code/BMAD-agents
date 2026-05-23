"""
BMAD MCP HTTP Server
====================
Exposes MCP tools over HTTP so LiteLLM can discover and call them.

GET  /tools          →  list all available tools
POST /tools/call     →  call a specific tool
GET  /health         →  health check
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, Optional

load_dotenv(Path(__file__).parent.parent / ".env")

# Import tool functions from the existing MCP server
import sys
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

app = FastAPI(title="BMAD MCP HTTP Server", version="1.0.0")


TOOLS = [
    {
        "name": "ask_pipeline",
        "description": "Ask any question about your BMAD pipeline in plain English. E.g. 'Which agent is slowest?'",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Your question about the pipeline"}
            },
            "required": ["question"]
        }
    },
    {
        "name": "get_agent_performance",
        "description": "Get performance stats for a specific agent or all agents.",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string", "description": "Agent name e.g. 'analyst', 'developer'. Leave blank for all."}
            },
            "required": []
        }
    },
    {
        "name": "get_model_usage",
        "description": "See how many traces each model has generated across your pipeline.",
        "parameters": {
            "type": "object",
            "properties": {
                "model_name": {"type": "string", "description": "Model name. Leave blank for all."}
            },
            "required": []
        }
    },
    {
        "name": "get_recent_activity",
        "description": "Get a summary of the most recent pipeline runs.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "How many recent traces to look at (default 10)"}
            },
            "required": []
        }
    },
    {
        "name": "compare_agents",
        "description": "Compare performance between two agents side by side.",
        "parameters": {
            "type": "object",
            "properties": {
                "agent1": {"type": "string", "description": "First agent name"},
                "agent2": {"type": "string", "description": "Second agent name"}
            },
            "required": ["agent1", "agent2"]
        }
    },
    {
        "name": "get_pipeline_health",
        "description": "Get an overall health report of your entire BMAD pipeline.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "search_sessions",
        "description": "Search pipeline sessions by project keyword e.g. 'stock', 'inventory'.",
        "parameters": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "Keyword to search for"}
            },
            "required": ["keyword"]
        }
    },
]


class ToolCallRequest(BaseModel):
    name: str
    arguments: Optional[dict] = {}


@app.get("/health")
def health():
    return {"status": "ok", "service": "bmad-mcp-http", "tools": len(TOOLS)}


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
