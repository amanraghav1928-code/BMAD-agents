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

@app.get("/chat")
def chat_ui():
    return FileResponse(Path(__file__).parent / "static" / "chat.html")

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

    # Plain text only — LiteLLM playground does NOT render markdown
    clean_response = f"Your website is live!\n\n{url}"

    return clean_response, url


# HTML_SYSTEM_PROMPT — focused prompt for the HTML specialist path
_HTML_SYSTEM_PROMPT = """You are an elite frontend developer and UI/UX designer. You create STUNNING, BEAUTIFUL, PROFESSIONAL single-page HTML websites that look like they were built by a world-class design agency.

CRITICAL RULES:
- Output ONLY raw HTML. First character must be < from <!DOCTYPE html>
- Absolutely NO markdown, NO code fences (```), NO explanations before or after
- Single self-contained file — all CSS and JS must be inline in the HTML

DESIGN STANDARDS (mandatory for every website):

FONTS: Always import 2+ Google Fonts. Choose fonts that match the mood (Pacifico for fun/celebration, Playfair Display for elegant, Outfit/Inter for modern tech, Quicksand for friendly).

BACKGROUNDS: Never use plain dark gray (#333) or plain white. Use animated gradient backgrounds:
  body { background: linear-gradient(135deg, #0f0f2d, #1a1a4e, #0d2137); background-size: 400% 400%; animation: gradShift 8s ease infinite; }
  @keyframes gradShift { 0%{background-position:0% 50%} 50%{background-position:100% 50%} 100%{background-position:0% 50%} }

CSS VARIABLES: Define a full color palette with --primary, --secondary, --accent, --text, --bg, --card-bg.

GLASSMORPHISM CARDS (required on every card/section):
  background: rgba(255,255,255,0.08);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255,255,255,0.15);
  border-radius: 24px;
  box-shadow: 0 20px 60px rgba(0,0,0,0.3);

GRADIENT TEXT (on all main headings):
  background: linear-gradient(135deg, #a78bfa, #ec4899);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;

ANIMATIONS (all mandatory):
  - @keyframes fadeInUp { from{opacity:0;transform:translateY(40px)} to{opacity:1;transform:translateY(0)} }
  - @keyframes float { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-15px)} }
  - @keyframes shimmer/pulse on buttons and highlights
  - CSS transitions: transition: all 0.3s ease on all interactive elements
  - Hover effects: transform: translateY(-6px) + stronger glow/shadow

LAYOUT:
  - CSS Grid or Flexbox everywhere (never floats or tables for layout)
  - Full sections: hero, features/cards, call-to-action, footer minimum
  - @media (max-width: 768px) responsive breakpoints
  - Styled scrollbar: ::-webkit-scrollbar { width: 8px; } ::-webkit-scrollbar-thumb { background: var(--primary); border-radius: 4px; }

JAVASCRIPT INTERACTIVITY (required — pick what fits the theme):
  - Particle/star/confetti canvas animation in the background
  - Countdown timer, animated counter, typewriter text effect
  - Interactive buttons with particle burst on click
  - Quote/testimonial rotator
  - Smooth scroll with IntersectionObserver for scroll-triggered animations

QUALITY BAR:
  - Every section must be VISUALLY DISTINCT and polished
  - Buttons must have gradient backgrounds and glow on hover
  - No boring plain text sections — every block needs visual interest
  - The result must make the user say "WOW" when they open it"""


async def _run_html_specialist(user_request: str) -> str:
    """
    Dedicated HTML generation path — bypasses the complex developer agent
    and calls the LLM directly with a focused HTML specialist system prompt.
    """
    from langchain_groq import ChatGroq
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import SystemMessage, HumanMessage

    user_prompt = f"""Create a complete, stunning, production-ready single-page HTML website for this request:

{user_request}

Remember: output ONLY raw HTML starting with <!DOCTYPE html>. Make it absolutely beautiful — glassmorphism cards, animated gradients, gradient text headings, impressive JavaScript interactivity, and professional typography. This should look like it cost $10,000 to design."""

    messages = [
        SystemMessage(content=_HTML_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]

    groq_key = os.getenv("GROQ_API_KEY", "")
    cerebras_key = os.getenv("CEREBRAS_API_KEY", "")

    # Try Groq 70b first (best quality + speed), fall back to Cerebras
    try:
        llm = ChatGroq(
            model="llama-3.3-70b-versatile",
            temperature=0.4,
            api_key=groq_key,
            max_tokens=8192,
        )
        response = llm.invoke(messages)
        return response.content.strip()
    except Exception as e:
        print(f"  ⚠️  Groq failed for HTML specialist: {e} — trying Cerebras...")

    # Cerebras fallback
    llm = ChatOpenAI(
        model="qwen-3-235b-a22b-instruct-2507",
        api_key=cerebras_key,
        base_url="https://api.cerebras.ai/v1",
        max_tokens=8192,
        temperature=0.4,
    )
    response = llm.invoke(messages)
    return response.content.strip()


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

        # Smart routing — HTML/website requests → dedicated HTML specialist
        #                  everything else    → analyst agent (BMAD pipeline)
        code_keywords = [
            "html", "website", "webpage", "css", "javascript", "build me",
            "create a", "make a", "develop", "app", "dashboard", "landing page",
            "portfolio", "ui", "frontend", "page for", "page about",
        ]
        user_lower = user_message.lower()
        is_html_request = any(kw in user_lower for kw in code_keywords)

        session_id = f"litellm-{uuid.uuid4().hex[:8]}"

        if is_html_request:
            # ── HTML specialist: direct LLM call, focused system prompt ───────
            result = await _run_html_specialist(user_message)
        else:
            # ── BMAD analyst pipeline ─────────────────────────────────────────
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
