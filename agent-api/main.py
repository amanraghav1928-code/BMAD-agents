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


async def _run_html_specialist(user_request: str) -> str:
    """
    Dedicated HTML generation — calls Groq 70b directly with a concrete
    CSS-scaffold prompt so the model always produces beautiful output.
    Falls back to Cerebras if Groq is rate-limited.
    """
    from langchain_groq import ChatGroq
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import SystemMessage, HumanMessage

    # ── System prompt with ACTUAL CODE the model must copy ────────────────────
    system = """You are an elite frontend developer. Output ONE complete HTML file.

HARD RULES:
1. Start with <!DOCTYPE html> — first character is <
2. No markdown fences, no explanations, no text before or after the HTML
3. All CSS and JS inline inside the file
4. Output at least 300 lines of real, non-repetitive code

MANDATORY CSS FOUNDATION — copy this base and adapt colors/content:

  /* === COPY THIS BASE === */
  @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700;800&family=Pacifico&display=swap');
  :root {
    --p1: /* primary gradient start — pick for the theme */;
    --p2: /* primary gradient end */;
    --bg: /* page bg color */;
    --card: rgba(255,255,255,0.07);
    --border: rgba(255,255,255,0.12);
    --text: #e2e8f0;
    --text2: #94a3b8;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  html { scroll-behavior:smooth; }
  body {
    font-family:'Outfit',sans-serif;
    min-height:100vh;
    background: var(--bg);
    background-image: radial-gradient(ellipse at 20% 50%, rgba(VAR_P1_RGB,0.18) 0%, transparent 50%),
                      radial-gradient(ellipse at 80% 20%, rgba(VAR_P2_RGB,0.15) 0%, transparent 50%);
    color: var(--text);
    overflow-x:hidden;
  }
  /* Animated background orbs */
  .orb { position:fixed; border-radius:50%; filter:blur(80px); opacity:0.35; animation:drift 12s ease-in-out infinite; pointer-events:none; z-index:0; }
  .orb1 { width:500px;height:500px; top:-100px;left:-100px; background:var(--p1); animation-delay:0s; }
  .orb2 { width:400px;height:400px; bottom:-80px;right:-80px; background:var(--p2); animation-delay:-6s; }
  @keyframes drift { 0%,100%{transform:translate(0,0) scale(1);} 50%{transform:translate(40px,30px) scale(1.08);} }

  /* Scrollbar */
  ::-webkit-scrollbar{width:6px;} ::-webkit-scrollbar-thumb{background:var(--p1);border-radius:3px;}

  /* Navbar */
  nav { position:fixed;top:0;left:0;right:0;z-index:100; padding:16px 40px;
    display:flex;align-items:center;justify-content:space-between;
    background:rgba(0,0,0,0.3); backdrop-filter:blur(20px);
    border-bottom:1px solid var(--border); }
  .nav-logo { font-size:22px;font-weight:800;
    background:linear-gradient(135deg,var(--p1),var(--p2));
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text; }
  .nav-links { display:flex;gap:28px; }
  .nav-links a { color:var(--text2);text-decoration:none;font-size:14px;font-weight:500;
    transition:color 0.2s; }
  .nav-links a:hover { color:var(--text); }
  .nav-cta { padding:9px 20px;border-radius:50px;font-weight:600;font-size:13px;cursor:pointer;
    background:linear-gradient(135deg,var(--p1),var(--p2));
    color:#fff;border:none;transition:all 0.3s;box-shadow:0 4px 20px rgba(0,0,0,0.3); }
  .nav-cta:hover { transform:translateY(-2px);box-shadow:0 8px 30px rgba(0,0,0,0.4); }

  /* Section wrapper */
  section { position:relative;z-index:1;padding:100px 40px; }

  /* Glassmorphism card — COPY THIS EXACTLY */
  .card {
    background: rgba(255,255,255,0.07);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 24px;
    padding: 32px;
    box-shadow: 0 20px 60px rgba(0,0,0,0.3);
    transition: all 0.3s ease;
  }
  .card:hover { transform:translateY(-8px); box-shadow:0 32px 80px rgba(0,0,0,0.4); border-color:rgba(255,255,255,0.2); }

  /* Gradient heading — COPY THIS EXACTLY */
  .grad-text {
    background: linear-gradient(135deg, var(--p1), var(--p2));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }

  /* Hero */
  .hero { min-height:100vh;display:flex;flex-direction:column;align-items:center;
    justify-content:center;text-align:center;padding-top:80px; }
  .hero h1 { font-size:clamp(2.8rem,7vw,5.5rem);font-weight:800;line-height:1.1;letter-spacing:-2px;margin-bottom:20px; }
  .hero p { font-size:clamp(1rem,2vw,1.25rem);color:var(--text2);max-width:580px;line-height:1.7;margin-bottom:36px; }

  /* Buttons */
  .btn-primary { padding:15px 36px;border-radius:50px;font-size:16px;font-weight:700;cursor:pointer;
    background:linear-gradient(135deg,var(--p1),var(--p2));
    color:#fff;border:none;transition:all 0.3s;
    box-shadow:0 8px 30px rgba(0,0,0,0.35); }
  .btn-primary:hover { transform:translateY(-3px);box-shadow:0 16px 48px rgba(0,0,0,0.5);filter:brightness(1.1); }
  .btn-primary:active { transform:translateY(-1px); }
  .btn-outline { padding:14px 32px;border-radius:50px;font-size:15px;font-weight:600;cursor:pointer;
    background:transparent;color:var(--text);
    border:1px solid var(--border);transition:all 0.3s; }
  .btn-outline:hover { background:rgba(255,255,255,0.07);border-color:rgba(255,255,255,0.25); }

  /* Feature grid */
  .grid { display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:24px;max-width:1100px;margin:0 auto; }

  /* Card icon */
  .card-icon { font-size:36px;margin-bottom:16px;display:block; }
  .card h3 { font-size:20px;font-weight:700;margin-bottom:10px;color:var(--text); }
  .card p { font-size:14px;color:var(--text2);line-height:1.7; }

  /* Section title */
  .section-title { font-size:clamp(2rem,4vw,3rem);font-weight:800;letter-spacing:-1px;margin-bottom:14px; }
  .section-sub { font-size:16px;color:var(--text2);max-width:520px;margin:0 auto 52px;line-height:1.7; }

  /* Entrance animation */
  .fade-up { opacity:0;transform:translateY(40px);transition:opacity 0.6s ease,transform 0.6s ease; }
  .fade-up.visible { opacity:1;transform:translateY(0); }

  /* Stats row */
  .stats { display:flex;gap:48px;justify-content:center;flex-wrap:wrap;margin:40px 0; }
  .stat-num { font-size:3rem;font-weight:800;line-height:1; }
  .stat-label { font-size:13px;color:var(--text2);margin-top:4px; }

  /* Footer */
  footer { text-align:center;padding:40px;border-top:1px solid var(--border);color:var(--text2);font-size:13px; }

  /* Responsive */
  @media(max-width:768px) {
    nav { padding:14px 20px; } .nav-links{display:none;}
    section { padding:80px 20px; }
    .hero h1 { font-size:2.5rem; }
    .stats { gap:28px; }
  }
  /* === END BASE === */

JAVASCRIPT — always add IntersectionObserver for .fade-up elements:
  const io = new IntersectionObserver(els => els.forEach(e => { if(e.isIntersecting) e.target.classList.add('visible'); }), {threshold:0.1});
  document.querySelectorAll('.fade-up').forEach(e => io.observe(e));

Pick ONE additional JS feature that fits the theme (particles canvas, typewriter, confetti, animated counter, etc.) and implement it fully."""

    # ── User prompt — very specific ───────────────────────────────────────────
    user_prompt = f"""Build a complete, STUNNING, production-ready single-page HTML website for:

"{user_request}"

REQUIREMENTS:
- Pick a color scheme that perfectly matches the vibe/theme of the request
- Replace all VAR_P1_RGB / VAR_P2_RGB placeholders with actual RGB values matching your chosen colors
- Include: navbar, hero section with big headline + subtext + 2 buttons, features/cards section (3-4 cards with glassmorphism), stats row, CTA section, footer
- Every heading uses .grad-text gradient
- Every card uses the glassmorphism .card class
- All sections use .fade-up animation with IntersectionObserver
- Add a canvas particle/star animation that matches the theme
- The result should look like a real $50k startup website

Output ONLY the complete HTML file starting with <!DOCTYPE html>"""

    messages = [
        SystemMessage(content=system),
        HumanMessage(content=user_prompt),
    ]

    groq_key = os.getenv("GROQ_API_KEY") or None
    cerebras_key = os.getenv("CEREBRAS_API_KEY") or None

    def _strip_fences(text: str) -> str:
        """Remove markdown code fences if the model wraps output in them."""
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r'^```[a-z]*\n?', '', text)
            text = re.sub(r'\n?```$', '', text)
        return text.strip()

    last_error = None

    # Try Groq 70b first
    if groq_key:
        try:
            llm = ChatGroq(
                model="llama-3.3-70b-versatile",
                temperature=0.7,
                api_key=groq_key,
                max_tokens=8192,
            )
            response = llm.invoke(messages)
            return _strip_fences(response.content)
        except Exception as e:
            last_error = f"Groq: {e}"
            print(f"  ⚠️  Groq failed for HTML specialist: {e} — trying Cerebras...")
    else:
        last_error = "GROQ_API_KEY not set"
        print("  ⚠️  GROQ_API_KEY not set — skipping Groq, trying Cerebras...")

    # Cerebras fallback
    if not cerebras_key:
        raise RuntimeError(
            f"All LLM providers failed. Last error: {last_error}. "
            "Ensure GROQ_API_KEY and/or CEREBRAS_API_KEY are set in Railway service variables."
        )
    try:
        llm = ChatOpenAI(
            model="qwen-3-235b-a22b-instruct-2507",
            api_key=cerebras_key,
            base_url="https://api.cerebras.ai/v1",
            max_tokens=8192,
            temperature=0.7,
        )
        response = llm.invoke(messages)
        return _strip_fences(response.content)
    except Exception as e:
        raise RuntimeError(f"All LLM providers failed. Groq: {last_error} | Cerebras: {e}")


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
