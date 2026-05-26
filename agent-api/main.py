"""
BMAD Agent API
==============
Wraps the BMAD 10-agent pipeline in OpenAI-compatible format.
LiteLLM routes "bmad-agent" model calls here.

POST /v1/chat/completions  →  runs agent pipeline  →  returns OpenAI response
GET  /health               →  health check
GET  /pages/{page_id}      →  serves auto-deployed HTML pages
"""

import os, sys, time, uuid, json, re
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

# Base URL for hosted pages
BASE_URL = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "bmad-agent-api-production.up.railway.app")
if not BASE_URL.startswith("http"):
    BASE_URL = f"https://{BASE_URL}"

# Ensure pages directory exists
PAGES_DIR = Path(__file__).parent / "static" / "pages"
PAGES_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="BMAD Agent API", version="1.0.0")


# ── Static page routes ─────────────────────────────────────────────────────────

@app.get("/dashboard")
def dashboard():
    return FileResponse(Path(__file__).parent / "static" / "dashboard.html")

@app.get("/weather")
def weather():
    return FileResponse(Path(__file__).parent / "static" / "weather.html")

@app.get("/pallak")
def pallak():
    return FileResponse(Path(__file__).parent / "static" / "pallak.html")

@app.get("/traces")
def traces():
    return FileResponse(Path(__file__).parent / "static" / "traces.html")

@app.get("/congrats-pallak")
def congrats_pallak():
    return FileResponse(Path(__file__).parent / "static" / "congrats-pallak.html")

@app.get("/pages/{page_id}")
def serve_page(page_id: str):
    page_path = PAGES_DIR / f"{page_id}.html"
    if not page_path.exists():
        raise HTTPException(status_code=404, detail="Page not found")
    return FileResponse(page_path)


# ── Auto-deploy helper ─────────────────────────────────────────────────────────

def auto_deploy_html(content: str) -> tuple[str, str | None]:
    """
    If the agent response contains HTML, save it and return (modified_content, url).
    Otherwise return (content, None).
    """
    html_match = re.search(r'<!DOCTYPE html>.*?</html>', content, re.DOTALL | re.IGNORECASE)
    if not html_match:
        return content, None

    html = html_match.group(0)
    page_id = uuid.uuid4().hex[:10]
    page_path = PAGES_DIR / f"{page_id}.html"
    page_path.write_text(html)

    url = f"{BASE_URL}/pages/{page_id}"

    # Replace the raw HTML block in the response with a clean message + link
    clean_response = content[:html_match.start()].strip()
    if clean_response:
        clean_response += f"\n\n"
    clean_response += f"✅ **Your website is live!**\n\n🔗 **{url}**\n\nOpen the link above to see your website."

    return clean_response, url


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
            agent_id="analyst",
            user_message=user_message,
            session_id=session_id,
        )

        if not result:
            result = "The BMAD agent pipeline completed but returned no output."

        # ── Auto-deploy any HTML in the response ───────────────────────────────
        result, deployed_url = auto_deploy_html(result)

        prompt_tokens     = len(user_message.split()) * 2
        completion_tokens = len(result.split()) * 2
        completion_id     = f"chatcmpl-{uuid.uuid4().hex}"
        created           = int(time.time())

        # ── Streaming response (SSE) ───────────────────────────────────────────
        if request.stream:
            def event_stream():
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
