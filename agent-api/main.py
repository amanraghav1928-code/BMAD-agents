"""
BMAD Agent API
==============
Wraps the BMAD 10-agent pipeline in OpenAI-compatible format.
LiteLLM routes "bmad-agent" model calls here.

POST /v1/chat/completions  →  runs agent pipeline  →  returns OpenAI response
GET  /health               →  health check
"""

import os, sys, time, uuid, json
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

# Load env
load_dotenv(Path(__file__).parent.parent / ".env")

# Add parent to path so we can import core/
sys.path.insert(0, str(Path(__file__).parent.parent))

app = FastAPI(title="BMAD Agent API", version="1.0.0")

@app.get("/dashboard")
def dashboard():
    return FileResponse(Path(__file__).parent / "static" / "dashboard.html")


# ── Request / Response models ──────────────────────────────────────────────────

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    model: Optional[str] = "bmad-agent"
    messages: list[Message]
    max_tokens: Optional[int] = 8192
    temperature: Optional[float] = 0.7
    stream: Optional[bool] = False

class Choice(BaseModel):
    index: int
    message: Message
    finish_reason: str

class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

class ChatResponse(BaseModel):
    id: str
    object: str
    created: int
    model: str
    choices: list[Choice]
    usage: Usage


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "bmad-agent-api"}


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest):
    # Extract the user's prompt from the last user message
    user_message = ""
    for msg in reversed(request.messages):
        if msg.role == "user":
            user_message = msg.content
            break

    if not user_message:
        raise HTTPException(status_code=400, detail="No user message found")

    try:
        from core.agent_runner import run_agent

        # Run the BMAD pipeline
        session_id = f"litellm-{uuid.uuid4().hex[:8]}"
        result = run_agent(
            agent_id="analyst",        # entry point of the pipeline
            user_message=user_message,
            session_id=session_id,
        )

        if not result:
            result = "The BMAD agent pipeline completed but returned no output."

        # Estimate token counts
        prompt_tokens     = len(user_message.split()) * 2
        completion_tokens = len(result.split()) * 2
        completion_id     = f"chatcmpl-{uuid.uuid4().hex}"
        created           = int(time.time())

        # ── Streaming response (SSE) ───────────────────────────────────────────
        if request.stream:
            def event_stream():
                # Send content in one chunk
                chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": "bmad-agent",
                    "choices": [{
                        "index": 0,
                        "delta": {"role": "assistant", "content": result},
                        "finish_reason": None,
                    }],
                }
                yield f"data: {json.dumps(chunk)}\n\n"
                # Send final chunk with finish_reason
                final = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": "bmad-agent",
                    "choices": [{
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop",
                    }],
                }
                yield f"data: {json.dumps(final)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(event_stream(), media_type="text/event-stream")

        # ── Non-streaming response ─────────────────────────────────────────────
        return ChatResponse(
            id=completion_id,
            object="chat.completion",
            created=created,
            model="bmad-agent",
            choices=[Choice(
                index=0,
                message=Message(role="assistant", content=result),
                finish_reason="stop",
            )],
            usage=Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")


@app.get("/v1/models")
def list_models():
    return {
        "object": "list",
        "data": [{
            "id": "bmad-agent",
            "object": "model",
            "created": 1700000000,
            "owned_by": "bmad",
        }]
    }
