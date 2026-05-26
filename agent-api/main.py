"""
BMAD Agent API
==============
Wraps the BMAD 10-agent pipeline in OpenAI-compatible format.
LiteLLM routes "bmad-agent" model calls here.

POST /v1/chat/completions  →  runs agent pipeline  →  returns OpenAI response
GET  /health               →  health check
GET  /chat                 →  custom chat UI
GET  /pages/{page_id}      →  serves auto-deployed HTML pages
"""

import os, sys, time, uuid, json, re
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse, HTMLResponse
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

app = FastAPI(title="BMAD Agent API", version="1.0.0")


# ── Postgres page storage ──────────────────────────────────────────────────────

def _get_db_conn():
    """Return a psycopg2 connection using DATABASE_URL env var."""
    import psycopg2
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(db_url)

def _ensure_pages_table():
    """Create the pages table if it doesn't exist."""
    try:
        conn = _get_db_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pages (
                id      TEXT PRIMARY KEY,
                html    TEXT NOT NULL,
                created TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"⚠️  Could not ensure pages table: {e}")

def _save_page(page_id: str, html: str):
    """Save HTML to Postgres."""
    conn = _get_db_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO pages (id, html) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET html = EXCLUDED.html",
        (page_id, html)
    )
    conn.commit()
    cur.close()
    conn.close()

def _load_page(page_id: str) -> str | None:
    """Load HTML from Postgres. Returns None if not found."""
    conn = _get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT html FROM pages WHERE id = %s", (page_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else None

# Ensure table exists on startup
_ensure_pages_table()


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
    # Try Postgres first (persistent)
    try:
        html = _load_page(page_id)
        if html:
            return HTMLResponse(content=html)
    except Exception as e:
        print(f"⚠️  DB load failed, trying filesystem: {e}")

    # Fallback: filesystem (ephemeral, works during same container session)
    page_path = Path(__file__).parent / "static" / "pages" / f"{page_id}.html"
    if page_path.exists():
        return FileResponse(page_path)

    raise HTTPException(status_code=404, detail="Page not found")


# ── Auto-deploy helper ─────────────────────────────────────────────────────────

def auto_deploy_html(content: str) -> tuple[str, str | None]:
    """
    If the agent response contains HTML, save it to Postgres and return (modified_content, url).
    Handles both complete HTML (with </html>) and truncated output from smaller models.
    """
    stripped = content.strip()

    # Detect HTML: either a full doc or any response that starts with <!DOCTYPE
    html_match = re.search(r'<!DOCTYPE html>.*</html>', stripped, re.DOTALL | re.IGNORECASE)
    if html_match:
        html = html_match.group(0)
    elif re.match(r'<!DOCTYPE html>', stripped, re.IGNORECASE):
        # Model output is HTML but may be truncated — close it cleanly
        html = stripped
        if not re.search(r'</html>', html, re.IGNORECASE):
            html += "\n</body></html>"
    else:
        return content, None
    page_id = uuid.uuid4().hex[:10]

    try:
        _save_page(page_id, html)
    except Exception as e:
        print(f"⚠️  DB save failed, falling back to filesystem: {e}")
        # Fallback: save to disk if DB is unavailable
        pages_dir = Path(__file__).parent / "static" / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)
        (pages_dir / f"{page_id}.html").write_text(html)

    url = f"{BASE_URL}/pages/{page_id}"
    clean_response = f"Your website is live!\n\n{url}"
    return clean_response, url


async def _run_html_specialist(user_request: str) -> str:
    """
    Dedicated HTML generation.
    Fallback chain: Groq-70b → Cerebras-235b → Groq-8b
    Cerebras is tier-2 (not 8b) because 235b produces quality output.
    """
    from langchain_groq import ChatGroq
    from langchain_openai import ChatOpenAI
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.messages import SystemMessage, HumanMessage

    # ── System prompt: concise but includes the KEY CSS patterns ──────────────
    system = """You are an elite frontend developer. Output ONE complete HTML file. No markdown, no explanations.

MANDATORY VISUAL STYLE — these exact CSS patterns must be used:
```
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700;800&display=swap');
body { font-family:'Outfit',sans-serif; background:#080812; color:#e2e8f0; overflow-x:hidden; }

/* Floating glow orbs */
.orb{position:fixed;border-radius:50%;filter:blur(80px);opacity:0.4;animation:drift 14s ease-in-out infinite;pointer-events:none;z-index:0;}
.orb1{width:500px;height:500px;top:-150px;left:-150px;}
.orb2{width:400px;height:400px;bottom:-100px;right:-100px;animation-delay:-7s;}
@keyframes drift{0%,100%{transform:translate(0,0)}50%{transform:translate(50px,40px)}}

/* Frosted navbar */
nav{position:fixed;top:0;left:0;right:0;z-index:100;padding:18px 48px;display:flex;align-items:center;justify-content:space-between;background:rgba(8,8,18,0.6);backdrop-filter:blur(24px);border-bottom:1px solid rgba(255,255,255,0.08);}

/* Glassmorphism card */
.card{background:rgba(255,255,255,0.06);backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,0.10);border-radius:20px;padding:32px;transition:all 0.3s;}
.card:hover{transform:translateY(-6px);border-color:rgba(255,255,255,0.2);box-shadow:0 24px 64px rgba(0,0,0,0.4);}

/* Gradient text */
.grad{background:linear-gradient(135deg,VAR_P1,VAR_P2);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;}

/* Fade-up animation */
.fade-up{opacity:0;transform:translateY(36px);transition:opacity 0.6s,transform 0.6s;}
.fade-up.visible{opacity:1;transform:translateY(0);}
```

Replace VAR_P1 and VAR_P2 with gradient colors that match the theme.
Add canvas particle animation that matches the theme colors.
IntersectionObserver to trigger .fade-up on scroll.
Include: fixed navbar, fullscreen hero (giant headline with .grad class + subtext + 2 pill buttons), 3-4 feature cards in grid, stats row, CTA section, footer.
Hero headline must be at least 4rem. Make it feel like a $50k design agency built it."""

    user_prompt = f"""Build a complete stunning website for: "{user_request}"

REQUIRED — must include a <canvas id="particles"> with this JS pattern:
  const canvas=document.getElementById('particles'),ctx=canvas.getContext('2d');
  canvas.style.cssText='position:fixed;top:0;left:0;z-index:0;pointer-events:none;';
  // resize + create 80 particles + animate them with ctx.arc + requestAnimationFrame

Output ONLY the HTML file starting with <!DOCTYPE html>"""

    messages = [SystemMessage(content=system), HumanMessage(content=user_prompt)]

    groq_key     = os.getenv("GROQ_API_KEY") or None
    cerebras_key = os.getenv("CEREBRAS_API_KEY") or None
    gemini_key   = os.getenv("GEMINI_API_KEY") or None
    errors       = []

    def _strip_fences(text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r'^```[a-z]*\n?', '', text)
            text = re.sub(r'\n?```$', '', text)
        return text.strip()

    def _try_llm(llm, name: str) -> str | None:
        try:
            response = llm.invoke(messages)
            return _strip_fences(response.content)
        except Exception as e:
            errors.append(f"{name}: {e}")
            print(f"  ⚠️  {name} failed: {e}")
            return None

    # 1️⃣  Groq llama-3.3-70b — best quality, fast (100k tokens/day)
    if groq_key:
        result = _try_llm(ChatGroq(model="llama-3.3-70b-versatile", temperature=0.7,
                                   api_key=groq_key, max_tokens=8192), "Groq-70b")
        if result: return result

    # 2️⃣  Cerebras qwen-3-235b — 235B params, no daily cap
    if cerebras_key:
        result = _try_llm(ChatOpenAI(model="qwen-3-235b-a22b-instruct-2507",
                                     api_key=cerebras_key,
                                     base_url="https://api.cerebras.ai/v1",
                                     max_tokens=8192, temperature=0.7), "Cerebras-235b")
        if result: return result

    # 3️⃣  Google Gemini Flash — 1M tokens/day free, very reliable
    if gemini_key:
        result = _try_llm(ChatGoogleGenerativeAI(model="gemini-2.0-flash",
                                                  google_api_key=gemini_key,
                                                  temperature=0.7,
                                                  max_output_tokens=8192), "Gemini-Flash")
        if result: return result

    # 4️⃣  Groq llama-3.1-8b — last resort
    if groq_key:
        result = _try_llm(ChatGroq(model="llama-3.1-8b-instant", temperature=0.7,
                                   api_key=groq_key, max_tokens=4096), "Groq-8b")
        if result: return result

    raise RuntimeError(f"All LLM providers failed: {' | '.join(errors)}")


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
