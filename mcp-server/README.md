# BMAD Langfuse Intelligence — MCP Server

A smart MCP server that combines **Langfuse** (your trace data) with **Ollama** (local LLM brain) to give intelligent answers about your BMAD pipeline.

## Folder Structure
```
mcp-server/
├── server.py          ← Main MCP server (all tools live here)
├── .env               ← API keys + Ollama model config
├── requirements.txt   ← Python dependencies
└── README.md          ← This file
```

## Available Tools

| Tool | What it does |
|------|-------------|
| `ask_pipeline` | Ask anything in plain English |
| `get_agent_performance` | Stats for one or all agents |
| `get_model_usage` | How many traces per model |
| `get_recent_activity` | Latest pipeline runs (always newest first) |
| `compare_agents` | Side-by-side agent comparison |
| `get_pipeline_health` | Overall health score + bottlenecks |
| `search_sessions` | Find sessions by project keyword |

## How to change Ollama model
Edit `.env` and change `OLLAMA_MODEL`:
- `llama3`   → best quality
- `mistral`  → faster
- `aman`     → your own custom model!
