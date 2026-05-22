"""
BMAD Command Centre  v4  — Production-Grade AI Platform
========================================================
ARCHITECTURAL DECISIONS v4:
  • Local-first data strategy: memory/sessions.json + output/ are PRIMARY data sources.
    Langfuse is secondary (2-second non-blocking timeout with graceful fallback).
    This eliminates the 24-second startup freeze caused by Langfuse network timeouts.
  • @st.cache_data(ttl=60) on ALL expensive functions — filesystem reads, API calls.
    Streamlit re-runs the entire script on every widget interaction; without caching,
    every click triggers a fresh filesystem scan and 3 API calls.
  • st.query_params navigation — makes any HTML element clickable (project cards,
    sidebar logo, recent build items) without Streamlit button limitations.
  • Time-range selector filters both local sessions AND Langfuse fromTimestamp.
  • Activity feed built from local sessions.json — always populated, always fast.
"""
import os, sys, subprocess, time, json, threading, signal
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd

# ── Config ─────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="BMAD Command Centre",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

ROOT        = Path(__file__).parent
OUTPUT_DIR  = ROOT / "output"
APPS_DIR    = ROOT / "apps"
MEMORY_FILE = ROOT / "memory" / "sessions.json"

from dotenv import load_dotenv
load_dotenv(ROOT / "mcp-server" / ".env")
LF_PUBLIC  = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LF_SECRET  = os.getenv("LANGFUSE_SECRET_KEY", "")
LF_BASE    = os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
LF_PROJECT = "cmp3ujz4e0entad073dmg6vvo"
sys.path.insert(0, str(ROOT))

# ══════════════════════════════════════════════════════════════════════════════
# QUERY PARAM NAVIGATION  — must be the FIRST thing after config
# Root Cause Fix: Streamlit buttons can't make HTML elements clickable.
# Solution: HTML <a href="?param=value"> links + st.query_params reader at top.
# Any element can now navigate by setting a query param, which is read here
# before any other rendering happens.
# ══════════════════════════════════════════════════════════════════════════════
_qp = st.query_params
if "goto_home" in _qp:
    st.session_state["active_page"] = "🏠  Mission Control"
    st.query_params.clear(); st.rerun()
if "open_project" in _qp:
    st.session_state["selected_project"] = _qp["open_project"]
    st.session_state["active_page"]      = "📁  Projects"
    st.query_params.clear(); st.rerun()
if "build_prompt" in _qp:
    import urllib.parse
    prompt = urllib.parse.unquote_plus(_qp["build_prompt"])
    st.session_state["prompt_value"]      = prompt
    st.session_state["auto_start_build"]  = True
    st.session_state["active_page"]       = "🚀  Build"
    st.query_params.clear(); st.rerun()
if "toggle_sr" in _qp:
    st.session_state["show_sr_detail"] = not st.session_state.get("show_sr_detail", False)
    st.query_params.clear(); st.rerun()
if "toggle_tok" in _qp:
    st.session_state["show_token_detail"] = not st.session_state.get("show_token_detail", False)
    st.query_params.clear(); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════
AGENT_STEPS = [
    ("🔍","Analyst",        "#a78bfa","analyst",        "Extracting requirements & project brief"),
    ("📋","Product Manager","#60a5fa","product-manager","Writing full functional specification"),
    ("🏗️","Architect",      "#34d399","architect",      "Designing technical architecture"),
    ("🎨","Designer",       "#fbbf24","designer",       "Creating UI/UX design system"),
    ("📅","Scrum Master",   "#fb923c","scrum-master",   "Writing user stories & sprint plan"),
    ("💻","Developer",      "#f43f5e","developer",      "Generating production-quality code"),
    ("👁️","Code Reviewer",  "#8b5cf6","code-reviewer",  "Reviewing code quality & security"),
    ("⚡","Executor",       "#06b6d4","executor",       "Running syntax & import checks"),
    ("🧪","Mock Tester",    "#10b981","mock-tester",    "Writing & running pytest mock tests"),
    ("✅","QA Engineer",    "#84cc16","qa-engineer",    "Final QA strategy & PASS/FAIL verdict"),
]

SUGGESTED_PROJECTS = [
    {"title":"Stock Portfolio Tracker",  "icon":"📈","color":"#4D96FF",
     "prompt":"Build a real-time stock portfolio tracker with live prices, portfolio pie chart, gain/loss tracking and stock alerts using Streamlit and yfinance",
     "category":"Finance"},
    {"title":"AI Expense Manager",       "icon":"💰","color":"#6BCB77",
     "prompt":"Build an AI-powered expense tracker with category auto-detection, monthly budget charts, alerts and CSV export using Streamlit",
     "category":"Finance"},
    {"title":"Health & Fitness Tracker", "icon":"💪","color":"#FF6B6B",
     "prompt":"Build a health and fitness tracker with BMI calculator, calorie counter, workout log, weekly progress charts and goal setting using Streamlit",
     "category":"Health"},
    {"title":"Weather Intelligence",     "icon":"🌤️","color":"#FFD166",
     "prompt":"Build a weather dashboard with 7-day forecast, temperature and humidity charts, UV index and city search using Streamlit",
     "category":"Data"},
    {"title":"Code Review Assistant",    "icon":"🔍","color":"#B983FF",
     "prompt":"Build a Python code review assistant that checks for bugs, style issues, complexity and suggests improvements using Streamlit",
     "category":"Dev Tools"},
    {"title":"Quiz Learning Platform",   "icon":"📚","color":"#FF6B6B",
     "prompt":"Build an interactive quiz platform with multiple choice questions, timer, score tracking, difficulty levels and leaderboard using Streamlit",
     "category":"Education"},
    {"title":"Crypto Dashboard",         "icon":"₿","color":"#f59e0b",
     "prompt":"Build a cryptocurrency price dashboard with live prices, market cap, 24h volume, fear/greed index and portfolio calculator using Streamlit",
     "category":"Finance"},
    {"title":"Resume Builder AI",        "icon":"📄","color":"#ec4899",
     "prompt":"Build an AI-powered resume builder with real-time preview, skill suggestions, multiple sections and download option using Streamlit",
     "category":"Career"},
]

TIME_RANGES = {
    "Today":        1,
    "Last 7 Days":  7,
    "Last 30 Days": 30,
    "Last 90 Days": 90,
    "Last 6 Months":180,
    "Last 1 Year":  365,
    "All Time":     0,
}

# ══════════════════════════════════════════════════════════════════════════════
# CSS — Premium futuristic dark sidebar + warm light main
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;600&display=swap');
html,body,[class*="css"]{font-family:'Inter',sans-serif!important;}

/* ── PALETTE — matches bmad_website.html ───────────────────────────────────────
   BG      : #FFFDF8  cream white
   CORAL   : #FF6B6B  primary (coral red)
   BLUE    : #4D96FF  info / links
   GREEN   : #6BCB77  success
   YELLOW  : #FFD166  highlight
   LAVENDER: #B983FF  accent
   DARK    : #1E293B  text / sidebar
*/

.stApp{background:#FFFDF8!important;}

[data-testid="stSidebar"]{background:#1E293B!important;border-right:1px solid rgba(255,255,255,0.06)!important;}
[data-testid="stSidebar"] *{color:#e2e8f0!important;}
[data-testid="stSidebar"] hr{border-color:rgba(255,255,255,0.08)!important;}

div[data-testid="stSidebar"] div[role="radiogroup"]{gap:3px!important;}
div[data-testid="stSidebar"] div[role="radiogroup"] label{
    background:rgba(255,255,255,0.04)!important;border:1px solid rgba(255,255,255,0.08)!important;
    border-radius:10px!important;padding:10px 14px!important;color:rgba(226,232,240,0.75)!important;
    font-weight:500!important;font-size:0.88rem!important;transition:all 0.18s!important;margin-bottom:2px!important;}
div[data-testid="stSidebar"] div[role="radiogroup"] label:hover{
    background:rgba(255,107,107,0.2)!important;border-color:rgba(255,107,107,0.5)!important;color:#fff!important;}
div[data-testid="stSidebar"] .stRadio>label{display:none!important;}
div[data-testid="stSidebar"] div[role="radiogroup"] span[data-baseweb="radio"]{display:none!important;}
div[data-testid="stSidebar"] div[role="radiogroup"] div[data-testid="stMarkdownContainer"] p{
    color:inherit!important;font-size:inherit!important;font-weight:inherit!important;margin:0!important;}

.bmad-card{background:#fff;border:1.5px solid #e2e8f0;border-radius:16px;padding:20px 22px;
    box-shadow:0 2px 12px rgba(0,0,0,0.05);transition:all 0.22s ease;position:relative;overflow:hidden;}
.bmad-card:hover{transform:translateY(-3px);box-shadow:0 16px 40px rgba(255,107,107,0.12);border-color:#ffc5c5;}

.stat-card{border-radius:14px;padding:18px 14px;text-align:center;color:white;
    transition:transform 0.2s,box-shadow 0.2s;box-shadow:0 4px 16px rgba(0,0,0,0.14);}
.stat-card:hover{transform:translateY(-4px);box-shadow:0 14px 32px rgba(0,0,0,0.2);}
.stat-num{font-size:2.1rem;font-weight:900;line-height:1;}
.stat-label{font-size:0.65rem;text-transform:uppercase;letter-spacing:0.1em;margin-top:6px;opacity:.9;font-weight:800;}

/* Clickable stat card link — no underline, no colour change, no extra space */
a.stat-card-link{display:block;text-decoration:none!important;color:inherit!important;}
a.stat-card-link .stat-card{cursor:pointer;}
a.stat-card-link .stat-card:hover{transform:translateY(-6px);box-shadow:0 18px 40px rgba(0,0,0,0.25);}

.badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:0.7rem;font-weight:700;}
.b-green {background:#6BCB77;color:#fff;}
.b-red   {background:#FF6B6B;color:#fff;}
.b-blue  {background:#4D96FF;color:#fff;}
.b-purple{background:#B983FF;color:#fff;}
.b-amber {background:#FFD166;color:#1E293B;}
.b-pink  {background:#FF6B6B;color:#fff;}
.b-teal  {background:#06b6d4;color:#fff;}
.b-gray  {background:#64748b;color:#fff;}

.prompt-box{background:#fffbf0;border:1.5px solid #fde68a;border-left:4px solid #FFD166;
    border-radius:10px;padding:14px 18px;font-family:'JetBrains Mono',monospace;
    font-size:0.82rem;color:#1E293B;line-height:1.7;}

.terminal{background:#0f172a;border:2px solid #1e293b;border-radius:14px;padding:18px;
    font-family:'JetBrains Mono',monospace;font-size:0.78rem;color:#94a3b8;
    max-height:380px;overflow-y:auto;white-space:pre-wrap;line-height:1.6;}

.step-row{display:flex;align-items:center;gap:12px;padding:10px 14px;border-radius:10px;
    margin-bottom:5px;border:1.5px solid transparent;transition:all 0.25s;}
.step-done   {background:#f0fdf4;border-color:#6BCB77;}
.step-running{background:#fff5f5;border-color:#FF6B6B;animation:stepGlow 1.8s ease-in-out infinite;}
.step-waiting{background:#fafaf9;border-color:#e2e8f0;opacity:0.6;}
.step-failed {background:#fef2f2;border-color:#fca5a5;}
.step-name{font-weight:700;font-size:0.86rem;}
.step-desc{font-size:0.72rem;color:#64748b;}
.step-badge{margin-left:auto;font-size:0.7rem;font-weight:700;padding:3px 10px;border-radius:20px;white-space:nowrap;}
.step-time{font-family:'JetBrains Mono',monospace;font-size:0.68rem;color:#94a3b8;white-space:nowrap;}

.proj-card{background:white;border:2px solid #e2e8f0;border-radius:16px;padding:18px 20px;
    cursor:pointer;transition:all 0.2s ease;box-shadow:0 2px 8px rgba(0,0,0,0.04);display:block;
    text-decoration:none;color:inherit;}
.proj-card:hover{border-color:#FF6B6B;transform:translateY(-3px);
    box-shadow:0 14px 36px rgba(255,107,107,0.14);text-decoration:none;color:inherit;}

.activity-item{display:flex;align-items:center;gap:10px;padding:9px 13px;background:white;
    border:1.5px solid #f1f5f9;border-radius:10px;margin-bottom:5px;transition:all 0.15s;}
.activity-item:hover{border-color:#ffc5c5;background:#fff5f5;}

.sug-card{background:white;border:2px solid #e2e8f0;border-radius:14px;padding:16px;
    transition:all 0.2s;box-shadow:0 2px 8px rgba(0,0,0,0.03);}
.sug-card:hover{transform:translateY(-4px);box-shadow:0 18px 44px rgba(255,107,107,0.1);}

.dot-live{display:inline-block;width:8px;height:8px;border-radius:50%;background:#6BCB77;
    animation:livePulse 1.4s ease-in-out infinite;}
.dot-idle{display:inline-block;width:8px;height:8px;border-radius:50%;background:#94a3b8;}
.dot-warn{display:inline-block;width:8px;height:8px;border-radius:50%;background:#FFD166;}

.page-title{font-size:1.9rem;font-weight:900;color:#1E293B;margin:0;line-height:1.2;}
.page-sub{color:#64748b;font-size:0.9rem;margin-top:5px;}

.insight-card{background:white;border:1.5px solid #e2e8f0;border-radius:12px;padding:16px 18px;
    border-left:4px solid #FF6B6B;margin-bottom:10px;}

.stButton>button{border-radius:10px!important;font-weight:700!important;
    font-family:'Inter',sans-serif!important;transition:all 0.2s!important;}
.stButton>button:hover{transform:translateY(-2px)!important;box-shadow:0 6px 20px rgba(255,107,107,0.25)!important;}
.stButton>button[kind="primary"]{background:#1E293B!important;color:#fff!important;border:none!important;}
.stButton>button[kind="primary"]:hover{background:#FF6B6B!important;box-shadow:0 8px 24px rgba(255,107,107,0.35)!important;}
.stButton>button[kind="secondary"]{background:#fff!important;color:#FF6B6B!important;border:2px solid #FF6B6B!important;}
.stButton>button[kind="secondary"]:hover{background:#FF6B6B!important;color:#fff!important;}
div[data-testid="stMetric"]{background:#fff;border:1.5px solid #e2e8f0;border-radius:12px;padding:14px;}
.stTabs [data-baseweb="tab"]{font-weight:600!important;font-size:0.88rem!important;}
.stTabs [aria-selected="true"]{color:#FF6B6B!important;border-bottom:3px solid #FF6B6B!important;font-weight:800!important;}
textarea,input{border-radius:10px!important;}
[data-testid="stExpander"]{border:1.5px solid #e2e8f0!important;border-radius:12px!important;background:white!important;}
h1,h2,h3{color:#1E293B!important;} p,li{color:#334155;}
hr{border-color:#e2e8f0!important;}
.stAlert{border-radius:12px!important;}

/* Animations */
@keyframes stepGlow{
    0%,100%{box-shadow:0 0 0 0 rgba(255,0,110,0.15);}
    50%{box-shadow:0 0 0 6px rgba(255,0,110,0);}}
@keyframes livePulse{
    0%,100%{box-shadow:0 0 0 0 rgba(0,200,83,0.55);}
    50%{box-shadow:0 0 0 5px rgba(0,200,83,0);}}
@keyframes shimmer{
    0%{background-position:-600px 0;}100%{background-position:600px 0;}}
.skeleton{background:linear-gradient(90deg,#f5eeff 25%,#ead6ff 50%,#f5eeff 75%);
    background-size:600px 100%;animation:shimmer 1.4s infinite;border-radius:8px;
    height:14px;margin-bottom:8px;}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# SESSION STATE
# ══════════════════════════════════════════════════════════════════════════════
_defaults = {
    "active_page":      "🏠  Mission Control",
    "running_apps":     {},
    "pipeline_running": False,
    "prompt_value":     "",
    "selected_project": None,
    "show_app_inline":  {},
    "auto_start_build": False,
    "_show_edit_proj":  None,
    "time_range":       "Last 30 Days",
    # Pipeline threading state
    "_pipeline_buf":    None,   # mutable list filled by reader thread
    "_pipeline_done":   None,   # [False] wrapper — thread sets [0]=True on exit
    "_pipeline_pid":    None,   # subprocess PID for kill
    "_pipeline_start":  0.0,    # wall-clock start time
    "_pipeline_cursor": 0,      # how many lines we've already processed
    "_step_states":     {},     # per-agent status dict
    "_active_agent":    None,   # [agent_name] mutable wrapper
    "_agent_start_t":   None,   # [float] mutable wrapper
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ══════════════════════════════════════════════════════════════════════════════
# CACHED DATA HELPERS
# Performance fix: @st.cache_data prevents re-execution on every widget event.
# TTL=60 means data refreshes every 60 seconds automatically.
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=60, show_spinner=False)
def load_sessions() -> list:
    """
    Load all pipeline sessions from local memory/sessions.json.
    This is the PRIMARY data source — always available, zero latency.
    Contains: date, status, user_request, agents_run, language, debug_iterations.
    """
    try:
        with open(str(MEMORY_FILE), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


@st.cache_data(ttl=30, show_spinner=False)
def get_projects() -> list:
    """
    Scan output/ directory for all generated projects.
    Cached for 30s — without caching, this filesystem scan runs on every
    widget click causing 50-200ms latency per interaction.
    """
    projects = []
    if not OUTPUT_DIR.exists():
        return projects

    for folder in sorted(OUTPUT_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not folder.is_dir() or folder.name == "stories":
            continue
        docs = {}
        for fname in ["prompt.txt","project-brief.md","functional-spec.md",
                      "solution-design.md","user-stories.md","test-strategy.md",
                      "test-plan.md","mock-tests.py","mock-test-results.md"]:
            fp = folder / fname
            docs[fname] = fp.read_text(encoding="utf-8") if fp.exists() else ""

        slug = folder.name
        app_file, app_lang = None, "python"
        for ext, lang in [(".py","python"),(".html","html")]:
            c = APPS_DIR / f"{slug}{ext}"
            if c.exists():
                app_file, app_lang = str(c), lang
                break
        if not app_file:
            j = APPS_DIR / slug / "Main.java"
            if j.exists():
                app_file, app_lang = str(j), "java"
        if not app_file:
            # Spring Boot: project directory contains pom.xml
            sb = APPS_DIR / slug
            if sb.is_dir() and (sb / "pom.xml").exists():
                app_file, app_lang = str(sb), "springboot"

        tp = docs.get("test-plan.md","")
        verdict = "passed" if "VERDICT: PASS" in tp.upper() else (
                  "failed" if "VERDICT: FAIL" in tp.upper() else "unknown")
        mr = docs.get("mock-test-results.md","")
        mock_v = "passed" if "ALL TESTS PASSED" in mr else (
                 "failed" if "SOME TESTS FAILED" in mr else "skipped")

        # Intelligent prompt recovery: prompt.txt → sessions.json → folder name
        prompt = docs.get("prompt.txt","").strip()
        if not prompt:
            sessions = load_sessions()
            # Match by output file path containing slug
            for s in sessions:
                if slug.replace("_","") in (s.get("output_file","") or "").replace("_",""):
                    prompt = s.get("user_request","")
                    break
        if not prompt:
            prompt = folder.name.replace("_"," ").strip()

        projects.append({
            "name":     folder.name.replace("_"," ").title()[:52],
            "slug":     folder.name,
            "folder":   str(folder),
            "app_file": app_file,
            "app_lang": app_lang,
            "docs":     docs,
            "prompt":   prompt,
            "verdict":  verdict,
            "mock":     mock_v,
            "modified": datetime.fromtimestamp(folder.stat().st_mtime).strftime("%b %d %Y, %H:%M"),
            "ts":       folder.stat().st_mtime,
        })
    return projects


@st.cache_data(ttl=60, show_spinner=False)
def fetch_lf(days: int = 0) -> dict:
    """
    Fetch Langfuse traces with a 2-second timeout and graceful fallback.

    Root cause of previous slowness: 8-second timeout × 3 calls = 24s of blocking.
    Fix: 2-second timeout. If Langfuse is unreachable, returns empty dict
    immediately — the rest of the dashboard uses local data as fallback.
    Cached for 90s to avoid hammering the API.
    """
    base_params = {"limit": 200}
    if days > 0:
        from_ts = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        base_params["fromTimestamp"] = from_ts

    def _get(ep, extra=None):
        p = {**base_params, **(extra or {})}
        try:
            r = requests.get(f"{LF_BASE}/api/public/{ep}",
                             auth=(LF_PUBLIC, LF_SECRET), params=p, timeout=5)
            return r.json().get("data", []) if r.ok else []
        except Exception:
            return []

    return {
        "all":      _get("traces"),
        "pipeline": _get("traces", {"name": "bmad-pipeline-summary"}),
    }


def lf_agent_stats(traces: list) -> dict:
    """Compute per-agent stats dict from Langfuse trace list."""
    stats = {}
    for t in traces:
        name = t.get("name","")
        if not name.startswith("bmad-") or name == "bmad-pipeline-summary":
            continue
        key = name.replace("bmad-","")
        lat = t.get("latency") or 0
        ts  = t.get("timestamp","")[:16].replace("T"," ")
        if key not in stats:
            stats[key] = {"runs": 0, "lats": [], "last_run": ts}
        stats[key]["runs"] += 1
        if lat > 0: stats[key]["lats"].append(lat)
        if ts > stats[key]["last_run"]: stats[key]["last_run"] = ts
    return stats


_PREVIEW_PORT = 8510   # single dedicated preview port — always the same


def _kill_port(port: int) -> None:
    """Kill any process listening on port (macOS / Linux)."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True, text=True
        )
        pids = result.stdout.strip().split()
        for pid in pids:
            if pid:
                subprocess.run(["kill", "-9", pid], capture_output=True)
    except Exception:
        pass


def start_python_app(proj) -> str:
    """Start the preview app on _PREVIEW_PORT, killing whatever is there first."""
    slug = proj["slug"]

    # Kill every tracked preview process
    for info in list(st.session_state.running_apps.values()):
        try: info["proc"].terminate()
        except Exception: pass
    st.session_state.running_apps.clear()

    # Hard-kill anything still holding the port
    _kill_port(_PREVIEW_PORT)
    time.sleep(1.2)   # wait for OS to release the port

    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", proj["app_file"],
         "--server.port", str(_PREVIEW_PORT),
         "--server.headless", "true",
         "--server.runOnSave", "false"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(ROOT),
    )
    st.session_state.running_apps[slug] = {"proc": proc, "port": _PREVIEW_PORT}
    time.sleep(3.5)   # let Streamlit fully boot before iframe loads
    return f"http://localhost:{_PREVIEW_PORT}"


def render_app_inline(proj):
    """Render project app inside the dashboard — no external browser."""
    lang = proj.get("app_lang","python")
    fp   = proj.get("app_file")
    if not fp or not Path(fp).exists():
        st.warning("App file not found for this project.")
        return
    if lang == "html":
        st.markdown("**📺 Live Preview** _(HTML rendered inline)_")
        html_src = Path(fp).read_text(encoding="utf-8")
        # Validate HTML is complete — truncated files (from token limit) have no <body>
        if "</body>" not in html_src.lower() and "</html>" not in html_src.lower():
            st.error("⚠️ **HTML file appears truncated** (hit token limit during generation). "
                     "Use **✏️ Edit Prompt & Rebuild** to regenerate with a more focused prompt.")
            st.code(html_src[:500] + "\n\n… [truncated]", language="html")
            return
        components.html(html_src, height=640, scrolling=True)
    elif lang in ("python","streamlit","fastapi"):
        slug    = proj["slug"]
        running = st.session_state.running_apps.get(slug)

        # Validate: process must be alive AND it must be the right project
        app_already_running = False
        if running:
            proc_alive = running["proc"].poll() is None   # None = still running
            right_app  = proj["app_file"] in " ".join(running.get("cmd", []))
            app_already_running = proc_alive  # port is fixed so if alive → right app

        if app_already_running:
            url = f"http://localhost:{_PREVIEW_PORT}"
        else:
            with st.spinner("⚡ Starting preview (~4s)…"):
                url = start_python_app(proj)

        st.markdown(f"**📺 Live Preview** — [{url}]({url})")
        st.caption("Scroll inside the frame to interact.")
        components.iframe(url, height=640, scrolling=True)
    elif lang == "java":
        st.code(Path(fp).read_text(encoding="utf-8"), language="java")

    elif lang == "springboot":
        proj_dir = Path(fp)   # fp is the project directory for Spring Boot
        if not proj_dir.exists() or not proj_dir.is_dir():
            st.warning("Spring Boot project folder not found.")
            return
        # Collect all project files
        all_files = sorted(
            p for p in proj_dir.rglob("*")
            if p.is_file() and ".mvn" not in str(p) and "target" not in str(p)
        )
        if not all_files:
            st.warning("No files found in Spring Boot project folder.")
            return

        st.markdown("**🌱 Spring Boot Project — File Explorer**")
        st.info(f"📂 `{proj_dir}`  |  {len(all_files)} files generated  |  "
                f"Run: `cd {proj_dir} && mvn spring-boot:run`")

        # File tree selector
        file_labels = [str(f.relative_to(proj_dir)) for f in all_files]
        selected    = st.selectbox("📄 View file:", file_labels, key=f"sb_file_{proj.get('slug','')}")
        if selected:
            sel_path = proj_dir / selected
            ext = sel_path.suffix.lower()
            lang_map = {".java": "java", ".xml": "xml", ".properties": "properties",
                        ".yml": "yaml", ".yaml": "yaml", ".json": "json",
                        ".html": "html", ".md": "markdown"}
            code_lang = lang_map.get(ext, "text")
            st.code(sel_path.read_text(encoding="utf-8"), language=code_lang)

        # Show all file names as a tree
        st.markdown("**📁 Project Structure:**")
        tree_lines = []
        for label in file_labels:
            parts = label.split("/")
            indent = "  " * (len(parts) - 1)
            tree_lines.append(f"{indent}📄 {parts[-1]}")
        st.code("\n".join(tree_lines), language="text")


def sessions_in_range(sessions: list, days: int) -> list:
    """Filter sessions by time range (days=0 means all time).
    days=1 means TODAY (since midnight), not last 24 hours.
    """
    if days == 0:
        return sessions
    now = datetime.now()
    if days == 1:
        # "Today" = since midnight of today
        cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        cutoff = now - timedelta(days=days)
    result = []
    for s in sessions:
        try:
            dt = datetime.strptime(s.get("date",""), "%Y-%m-%d %H:%M")
            if dt >= cutoff:
                result.append(s)
        except Exception:
            pass  # skip if date can't be parsed
    return result


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    # Clickable BMAD logo → home (via query param navigation)
    st.markdown("""
    <div style="padding:18px 0 14px;text-align:center;">
        <a href="?goto_home=1" target="_top" style="text-decoration:none;display:block;">
            <div style="font-size:2.6rem;line-height:1;">🤖</div>
            <div style="font-size:1.4rem;font-weight:900;color:#f8fafc;margin-top:6px;
                        letter-spacing:-0.5px;">BMAD</div>
            <div style="color:rgba(255,255,255,0.35);font-size:0.62rem;font-weight:700;
                        letter-spacing:0.14em;text-transform:uppercase;margin-top:2px;">
                Command Centre
            </div>
        </a>
    </div>
    """, unsafe_allow_html=True)
    st.divider()

    nav_pages = [
        "🏠  Mission Control",
        "🚀  Build",
        "📁  Projects",
        "🤖  Agents",
        "📊  Intelligence",
        "🎯  Evals",
    ]
    _cur_page = st.session_state.get("active_page", nav_pages[0])
    _nav_idx  = nav_pages.index(_cur_page) if _cur_page in nav_pages else 0
    page = st.radio("nav", nav_pages, index=_nav_idx, label_visibility="collapsed")
    st.session_state["active_page"] = page
    st.divider()

    # Quick stats from local sessions (zero latency)
    all_sessions = load_sessions()
    total_p  = len(get_projects())
    passed_s = sum(1 for s in all_sessions if s.get("status") == "passed")
    pct      = int(passed_s / len(all_sessions) * 100) if all_sessions else 0

    st.markdown(f"""
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:5px;margin-bottom:10px;">
        <div style="background:rgba(255,255,255,0.07);border-radius:9px;padding:9px;text-align:center;">
            <div style="font-size:1.5rem;font-weight:900;color:#f8fafc;">{total_p}</div>
            <div style="color:rgba(255,255,255,0.4);font-size:0.58rem;font-weight:700;
                        text-transform:uppercase;letter-spacing:0.06em;">Projects</div>
        </div>
        <div style="background:rgba(255,255,255,0.07);border-radius:9px;padding:9px;text-align:center;">
            <div style="font-size:1.5rem;font-weight:900;color:#86efac;">{passed_s}</div>
            <div style="color:rgba(255,255,255,0.4);font-size:0.58rem;font-weight:700;
                        text-transform:uppercase;letter-spacing:0.06em;">Passed</div>
        </div>
    </div>
    <div style="margin-bottom:12px;">
        <div style="display:flex;justify-content:space-between;
                    color:rgba(255,255,255,0.35);font-size:0.62rem;margin-bottom:3px;">
            <span>Success rate</span>
            <span style="color:#86efac;font-weight:700;">{pct}%</span>
        </div>
        <div style="background:rgba(255,255,255,0.1);border-radius:5px;height:5px;overflow:hidden;">
            <div style="background:#86efac;width:{pct}%;height:100%;border-radius:5px;"></div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.divider()

    # Clickable recent builds — open project directly on click
    st.markdown("""<div style="color:rgba(255,255,255,0.3);font-size:0.6rem;font-weight:800;
        text-transform:uppercase;letter-spacing:0.1em;margin-bottom:7px;">Recent Builds</div>""",
        unsafe_allow_html=True)

    projects_sidebar = get_projects()
    for proj in projects_sidebar[:6]:
        dot = "🟢" if proj["verdict"]=="passed" else ("🔴" if proj["verdict"]=="failed" else "🟡")
        # Each recent build is a clickable link via query param
        st.markdown(f"""
        <a href="?open_project={proj['slug']}" target="_top" style="text-decoration:none;display:block;">
        <div style="padding:6px 10px;border-radius:8px;margin-bottom:3px;
                    background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.06);
                    cursor:pointer;transition:all 0.15s;">
            <div style="font-size:0.77rem;font-weight:600;color:#e2e8f0;
                        white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                {dot} {proj['name'][:24]}
            </div>
            <div style="font-size:0.6rem;color:rgba(255,255,255,0.3);margin-top:1px;">
                {proj['modified'][:12]}
            </div>
        </div></a>""", unsafe_allow_html=True)

    st.divider()
    st.markdown(
        f'<div style="color:rgba(255,255,255,0.3);font-size:0.66rem;">'
        f'📅 {datetime.now().strftime("%a %b %d, %Y")}</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<a href="{LF_BASE}/project/{LF_PROJECT}" target="_blank" '
        f'style="color:rgba(255,255,255,0.35);font-size:0.66rem;text-decoration:none;">'
        f'🔗 Langfuse ↗</a>',
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# GLOBAL TIME-RANGE SELECTOR — appears on applicable pages
# Passes `days` to both local sessions filter and Langfuse fromTimestamp.
# ══════════════════════════════════════════════════════════════════════════════
def time_range_bar(key_suffix=""):
    """Render the time-range selector and return selected days integer."""
    col_tr, col_ref = st.columns([4,1])
    with col_tr:
        selected = st.selectbox(
            "📅 Time Range",
            list(TIME_RANGES.keys()),
            index=list(TIME_RANGES.keys()).index(
                st.session_state.get("time_range","Last 30 Days")),
            key=f"tr_{key_suffix}",
            label_visibility="collapsed",
        )
        st.session_state["time_range"] = selected
    with col_ref:
        if st.button("🔄 Refresh", use_container_width=True, key=f"ref_{key_suffix}"):
            st.cache_data.clear()
            st.rerun()
    return TIME_RANGES[selected]


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: MISSION CONTROL
# ══════════════════════════════════════════════════════════════════════════════
if page == "🏠  Mission Control":

    # Hero
    st.markdown("""
    <div style="background:white;border:1.5px solid #e2e8f0;border-radius:20px;
                padding:26px 30px;margin-bottom:22px;box-shadow:0 4px 20px rgba(255,0,110,0.06);">
        <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;">
            <div style="font-size:2.6rem;">🤖</div>
            <div style="flex:1;">
                <div style="font-size:1.9rem;font-weight:900;color:#1e293b;line-height:1.1;">
                    BMAD Command Centre
                </div>
                <div style="color:#64748b;font-size:0.9rem;margin-top:5px;">
                    10-agent AI platform — <strong style="color:#FF6B6B;">design</strong> ·
                    <strong style="color:#FF6B6B;">code</strong> ·
                    <strong style="color:#6BCB77;">test</strong> ·
                    <strong style="color:#4D96FF;">deploy</strong> — all from one prompt.
                </div>
            </div>
            <div style="text-align:right;">
                <div style="font-size:0.7rem;color:#94a3b8;font-weight:600;
                            text-transform:uppercase;letter-spacing:0.08em;">System Status</div>
                <div style="display:flex;align-items:center;gap:6px;margin-top:4px;justify-content:flex-end;">
                    <span class="dot-live"></span>
                    <span style="font-size:0.82rem;font-weight:700;color:#059669;">Online</span>
                </div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Time range
    days = time_range_bar("mc")

    # Load data (local sessions — instant; Langfuse — 2s fallback)
    all_sessions     = load_sessions()
    filtered_sess    = sessions_in_range(all_sessions, days)
    projects_all     = get_projects()
    lf               = fetch_lf(days)
    lf_traces        = lf.get("all", [])
    lf_pipeline      = lf.get("pipeline", [])

    # Compute metrics from local sessions (always available)
    total_runs    = len(filtered_sess)
    passed_runs   = sum(1 for s in filtered_sess if s.get("status")=="passed")
    failed_runs   = sum(1 for s in filtered_sess if s.get("status")!="passed")
    success_rate  = round(passed_runs / total_runs * 100) if total_runs else 0
    total_agents  = sum(len(s.get("agents_run",[])) for s in filtered_sess)
    total_debug   = sum(s.get("debug_iterations",0) for s in filtered_sess)
    # Langfuse extras (when available)
    lf_traces_cnt = len(lf_traces)
    avg_lat_lf    = round(sum(t.get("latency",0) or 0 for t in lf_traces[:30]) /
                          max(len(lf_traces[:30]),1), 1)

    # Token usage — fetch from Langfuse observations, fallback to local estimate
    @st.cache_data(ttl=60, show_spinner=False)
    def _fetch_token_total(days_: int) -> int:
        if not LF_PUBLIC or not LF_SECRET:
            return 0
        try:
            params = {"type": "GENERATION", "limit": 100}
            if days_ == 1:
                from_ts = datetime.now(timezone.utc).replace(
                    hour=0, minute=0, second=0, microsecond=0
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
                params["fromStartTime"] = from_ts
            elif days_ > 1:
                from_ts = (datetime.now(timezone.utc) - timedelta(days=days_)).strftime("%Y-%m-%dT%H:%M:%SZ")
                params["fromStartTime"] = from_ts
            r = requests.get(
                f"{LF_BASE}/api/public/observations",
                auth=(LF_PUBLIC, LF_SECRET),
                params=params,
                timeout=3,
            )
            if r.status_code == 200:
                obs = r.json().get("data", [])
                total = 0
                for o in obs:
                    u = o.get("usage") or {}
                    total += (u.get("input") or 0) + (u.get("output") or 0)
                return total
        except Exception:
            pass
        return 0

    lf_tokens = _fetch_token_total(days)
    # If Langfuse returned 0, estimate from filtered sessions (avg ~18K tokens per run)
    if lf_tokens == 0 and total_runs > 0:
        lf_tokens = total_runs * 18_000
    def _fmt_tokens(n: int) -> str:
        if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
        if n >= 1_000:     return f"{n//1_000}K"
        return str(n)

    # Filter projects count by time range too
    if days == 0:
        projects_in_range = len(projects_all)
    else:
        now_ts = datetime.now()
        if days == 1:
            cutoff_ts = now_ts.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            cutoff_ts = now_ts - timedelta(days=days)
        projects_in_range = sum(
            1 for p in projects_all
            if datetime.fromtimestamp(p["ts"]) >= cutoff_ts
        )

    # Groq free-tier daily limits per model
    MODEL_LIMITS = {
        "llama-3.3-70b-versatile": {"daily": 1_000_000, "color": "#FF6B6B",  "icon": "🦙"},
        "llama-3.1-8b-instant":    {"daily": 1_000_000, "color": "#4D96FF",  "icon": "⚡"},
        "mixtral-8x7b-32768":      {"daily":   500_000, "color": "#B983FF",  "icon": "🌀"},
        "cerebras/qwen-3-235b-a22b-instruct-2507": {"daily": 1_000_000, "color": "#6BCB77", "icon": "🧠"},
    }

    # Fetch per-model token breakdown from Langfuse
    @st.cache_data(ttl=60, show_spinner=False)
    def _fetch_model_tokens(days_: int) -> dict:
        """Returns {model_name: {input, output, total}} from Langfuse observations."""
        if not LF_PUBLIC or not LF_SECRET:
            return {}
        try:
            params = {"type": "GENERATION", "limit": 200}
            if days_ == 1:
                from_ts = datetime.now(timezone.utc).replace(
                    hour=0, minute=0, second=0, microsecond=0
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
                params["fromStartTime"] = from_ts
            elif days_ > 1:
                from_ts = (datetime.now(timezone.utc) - timedelta(days=days_)).strftime("%Y-%m-%dT%H:%M:%SZ")
                params["fromStartTime"] = from_ts
            r = requests.get(
                f"{LF_BASE}/api/public/observations",
                auth=(LF_PUBLIC, LF_SECRET),
                params=params,
                timeout=4,
            )
            if r.status_code != 200:
                return {}
            result = {}
            for o in r.json().get("data", []):
                model = (o.get("model") or "unknown").lower()
                # Normalize model names
                if "70b" in model or "versatile" in model:
                    key = "llama-3.3-70b-versatile"
                elif "8b" in model or "instant" in model:
                    key = "llama-3.1-8b-instant"
                elif "mixtral" in model:
                    key = "mixtral-8x7b-32768"
                elif "cerebras" in model or "qwen" in model:
                    key = "cerebras/qwen-3-235b-a22b-instruct-2507"
                else:
                    key = model
                u = o.get("usage") or {}
                inp = u.get("input") or 0
                out = u.get("output") or 0
                if key not in result:
                    result[key] = {"input": 0, "output": 0, "total": 0}
                result[key]["input"]  += inp
                result[key]["output"] += out
                result[key]["total"]  += inp + out
            return result
        except Exception:
            return {}

    model_tokens = _fetch_model_tokens(days)

    # If no Langfuse data, build estimate from local sessions
    if not model_tokens and total_runs > 0:
        # Distribute estimate: 70% primary model, 20% 8b fallback, 10% cerebras
        est = total_runs * 18_000
        model_tokens = {
            "llama-3.3-70b-versatile": {"input": int(est*0.45), "output": int(est*0.25), "total": int(est*0.70)},
            "llama-3.1-8b-instant":    {"input": int(est*0.12), "output": int(est*0.08), "total": int(est*0.20)},
            "cerebras/qwen-3-235b-a22b-instruct-2507": {"input": int(est*0.06), "output": int(est*0.04), "total": int(est*0.10)},
        }
        lf_tokens = est

    # KPI strip — 6 cards
    k1,k2,k3,k4,k5,k6 = st.columns(6)
    kpi_data = [
        (projects_in_range,          "Total Projects",    "linear-gradient(135deg,#FF6B6B,#e05555)"),
        (total_runs,                 "Pipeline Runs",     "linear-gradient(135deg,#4D96FF,#2d76df)"),
        (f"{success_rate}%",         "Success Rate",      "linear-gradient(135deg,#6BCB77,#4aaa55)"),
        (total_agents,               "Agent Executions",  "linear-gradient(135deg,#FFD166,#e0b040)"),
        (lf_traces_cnt if lf_traces_cnt else "—", "Traces (LF)", "linear-gradient(135deg,#B983FF,#9960e0)"),
        (_fmt_tokens(lf_tokens),     "Tokens Used",       "linear-gradient(135deg,#1E293B,#334155)"),
    ]
    # Render cards — Success Rate and Tokens Used are <a href> links (no buttons)
    for col,(val,lbl,clr) in zip([k1,k2,k3,k4,k5,k6],kpi_data):
        with col:
            is_sr  = lbl.startswith("Success Rate")
            is_tok = lbl.startswith("Tokens Used")
            card_html = (f'<div class="stat-card" style="background:{clr};">'
                         f'<div class="stat-num">{val}</div>'
                         f'<div class="stat-label">{lbl}</div></div>')
            if is_sr:
                st.markdown(f'<a href="?toggle_sr=1" target="_top" class="stat-card-link">{card_html}</a>',
                            unsafe_allow_html=True)
            elif is_tok:
                st.markdown(f'<a href="?toggle_tok=1" target="_top" class="stat-card-link">{card_html}</a>',
                            unsafe_allow_html=True)
            else:
                st.markdown(card_html, unsafe_allow_html=True)

    # ── Success Rate detail panel ──────────────────────────────────────────────
    if st.session_state.get("show_sr_detail", False):
        st.markdown("---")
        st.markdown("### 🏆 Pipeline Success Breakdown")

        passed_list = [s for s in filtered_sess if s.get("status") == "passed"]
        failed_list = [s for s in filtered_sess if s.get("status") != "passed"]

        sr_col1, sr_col2 = st.columns(2)

        with sr_col1:
            st.markdown(f"""
            <div style="background:#f0fdf4;border:1.5px solid #86efac;border-radius:14px;
                        padding:16px 18px;margin-bottom:10px;">
                <div style="font-size:1.1rem;font-weight:900;color:#166534;margin-bottom:12px;">
                    ✅ Passed — {len(passed_list)}
                </div>""", unsafe_allow_html=True)
            if passed_list:
                for s in reversed(passed_list):
                    name = (s.get("user_request","—"))[:52]
                    lang = (s.get("language") or "py").upper()
                    date = s.get("date","")[:10]
                    dbg  = s.get("debug_iterations", 0)
                    dbg_badge = f'<span style="background:#fef9c3;color:#92400e;padding:1px 7px;border-radius:8px;font-size:0.68rem;">🔁 {dbg} retries</span>' if dbg > 0 else ''
                    st.markdown(f"""
                    <div style="background:#fff;border-radius:10px;padding:10px 14px;
                                margin-bottom:8px;border-left:4px solid #6BCB77;
                                box-shadow:0 1px 5px rgba(0,0,0,0.05);">
                        <div style="font-weight:700;color:#1E293B;font-size:0.85rem;">{name}</div>
                        <div style="display:flex;gap:8px;margin-top:5px;align-items:center;">
                            <span style="background:#dcfce7;color:#166534;padding:1px 8px;
                                         border-radius:8px;font-size:0.68rem;font-weight:700;">{lang}</span>
                            {dbg_badge}
                            <span style="color:#94a3b8;font-size:0.7rem;">📅 {date}</span>
                        </div>
                    </div>""", unsafe_allow_html=True)
            else:
                st.info("No passed runs in this range.")
            st.markdown("</div>", unsafe_allow_html=True)

        with sr_col2:
            st.markdown(f"""
            <div style="background:#fff1f2;border:1.5px solid #fecaca;border-radius:14px;
                        padding:16px 18px;margin-bottom:10px;">
                <div style="font-size:1.1rem;font-weight:900;color:#991b1b;margin-bottom:12px;">
                    ❌ Failed — {len(failed_list)}
                </div>""", unsafe_allow_html=True)
            if failed_list:
                for s in reversed(failed_list):
                    name = (s.get("user_request","—"))[:52]
                    lang = (s.get("language") or "py").upper()
                    date = s.get("date","")[:10]
                    dbg  = s.get("debug_iterations", 0)
                    errs = s.get("errors_encountered", [])
                    err_txt = errs[0][:50] if errs else "Unknown error"
                    st.markdown(f"""
                    <div style="background:#fff;border-radius:10px;padding:10px 14px;
                                margin-bottom:8px;border-left:4px solid #FF6B6B;
                                box-shadow:0 1px 5px rgba(0,0,0,0.05);">
                        <div style="font-weight:700;color:#1E293B;font-size:0.85rem;">{name}</div>
                        <div style="color:#ef4444;font-size:0.72rem;margin-top:3px;">⚠️ {err_txt}</div>
                        <div style="display:flex;gap:8px;margin-top:5px;align-items:center;">
                            <span style="background:#fee2e2;color:#991b1b;padding:1px 8px;
                                         border-radius:8px;font-size:0.68rem;font-weight:700;">{lang}</span>
                            <span style="background:#fef9c3;color:#92400e;padding:1px 7px;
                                         border-radius:8px;font-size:0.68rem;">🔁 {dbg} retries</span>
                            <span style="color:#94a3b8;font-size:0.7rem;">📅 {date}</span>
                        </div>
                    </div>""", unsafe_allow_html=True)
            else:
                st.success("🎉 No failures in this time range!")
            st.markdown("</div>", unsafe_allow_html=True)

        # Mini donut-style summary bar
        if total_runs > 0:
            pass_pct = round(passed_runs / total_runs * 100)
            fail_pct = 100 - pass_pct
            st.markdown(f"""
            <div style="background:#fff;border-radius:12px;padding:14px 18px;
                        box-shadow:0 2px 8px rgba(0,0,0,0.06);margin-top:6px;">
                <div style="font-size:0.8rem;font-weight:700;color:#64748b;margin-bottom:8px;">
                    Overall in selected range
                </div>
                <div style="display:flex;border-radius:8px;overflow:hidden;height:18px;">
                    <div style="background:#6BCB77;width:{pass_pct}%;display:flex;align-items:center;
                                justify-content:center;font-size:0.65rem;font-weight:800;color:#fff;">
                        {"✅ "+str(pass_pct)+"%" if pass_pct > 10 else ""}
                    </div>
                    <div style="background:#FF6B6B;width:{fail_pct}%;display:flex;align-items:center;
                                justify-content:center;font-size:0.65rem;font-weight:800;color:#fff;">
                        {"❌ "+str(fail_pct)+"%" if fail_pct > 10 else ""}
                    </div>
                </div>
                <div style="display:flex;gap:20px;margin-top:8px;font-size:0.75rem;">
                    <span>✅ <strong>{passed_runs}</strong> passed</span>
                    <span>❌ <strong>{failed_runs}</strong> failed</span>
                    <span>📊 <strong>{total_runs}</strong> total runs</span>
                </div>
            </div>""", unsafe_allow_html=True)
        st.markdown("---")

    # ── Token detail panel ─────────────────────────────────────────────────────
    if st.session_state.get("show_token_detail", False):
        st.markdown("---")
        st.markdown("### 🔢 Token Usage by Model")
        label_days = {1:"Today", 7:"Last 7 Days", 30:"Last 30 Days",
                      90:"Last 90 Days", 180:"Last 6 Months", 365:"Last 1 Year", 0:"All Time"}
        is_estimate = not _fetch_model_tokens(days)  # True if using local estimate
        if is_estimate:
            st.caption("⚠️ Langfuse not connected — showing estimated distribution based on local session history.")
        else:
            st.caption(f"Live data from Langfuse · {label_days.get(days,'Selected range')}")

        for model_key, minfo in MODEL_LIMITS.items():
            usage   = model_tokens.get(model_key, {"input": 0, "output": 0, "total": 0})
            used    = usage["total"]
            daily   = minfo["daily"]
            pct     = min(100, round(used / daily * 100, 1)) if daily else 0
            left    = max(0, daily - used)
            bar_color = "#6BCB77" if pct < 60 else ("#FFD166" if pct < 85 else "#FF6B6B")
            # Short display name
            display = {
                "llama-3.3-70b-versatile": "llama-3.3-70b-versatile  (Primary)",
                "llama-3.1-8b-instant":    "llama-3.1-8b-instant  (Fallback)",
                "mixtral-8x7b-32768":      "mixtral-8x7b-32768",
                "cerebras/qwen-3-235b-a22b-instruct-2507": "Cerebras Qwen-3-235B  (3rd fallback)",
            }.get(model_key, model_key)

            st.markdown(f"""
            <div style="background:#fff;border-radius:14px;padding:16px 20px;margin-bottom:12px;
                        box-shadow:0 2px 10px rgba(0,0,0,0.07);border-left:5px solid {minfo['color']};">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                    <div style="font-weight:800;color:#1E293B;font-size:0.95rem;">
                        {minfo['icon']} {display}
                    </div>
                    <div style="font-size:0.8rem;color:#64748b;">
                        Daily limit: <strong>{_fmt_tokens(daily)}</strong>
                    </div>
                </div>
                <div style="background:#f1f5f9;border-radius:8px;height:10px;overflow:hidden;margin-bottom:8px;">
                    <div style="background:{bar_color};width:{pct}%;height:10px;border-radius:8px;
                                transition:width 0.8s;"></div>
                </div>
                <div style="display:flex;justify-content:space-between;font-size:0.78rem;">
                    <div style="display:flex;gap:18px;">
                        <span>📤 Input: <strong style="color:#1E293B;">{_fmt_tokens(usage['input'])}</strong></span>
                        <span>📥 Output: <strong style="color:#1E293B;">{_fmt_tokens(usage['output'])}</strong></span>
                        <span>🔢 Total used: <strong style="color:{minfo['color']};">{_fmt_tokens(used)}</strong></span>
                    </div>
                    <div>
                        {"🟢" if pct < 60 else ("🟡" if pct < 85 else "🔴")}
                        <strong style="color:{bar_color};">{_fmt_tokens(left)}</strong>
                        <span style="color:#94a3b8;"> remaining ({100-pct:.1f}%)</span>
                    </div>
                </div>
            </div>""", unsafe_allow_html=True)

        st.markdown("---")

    st.markdown("<br>", unsafe_allow_html=True)

    # Progress bars for quick health view
    pb_col1, pb_col2, pb_col3 = st.columns(3)
    with pb_col1:
        st.markdown(f"""<div class="bmad-card" style="padding:16px;">
            <div style="display:flex;justify-content:space-between;font-size:0.82rem;font-weight:700;color:#1e293b;margin-bottom:6px;">
                <span>🏆 Pipeline Success</span><span style="color:#059669;">{success_rate}%</span>
            </div>
            <div style="background:#f1f5f9;border-radius:8px;height:8px;overflow:hidden;">
                <div style="background:#059669;width:{success_rate}%;height:100%;border-radius:8px;transition:width 1s;"></div>
            </div>
        </div>""", unsafe_allow_html=True)
    with pb_col2:
        proj_lang_counts = {}
        for p in projects_all:
            proj_lang_counts[p["app_lang"]] = proj_lang_counts.get(p["app_lang"],0)+1
        top_lang   = max(proj_lang_counts, key=proj_lang_counts.get) if proj_lang_counts else "python"
        top_lang_pct = round(proj_lang_counts.get(top_lang,0)/max(len(projects_all),1)*100)
        icons = {"python":"🐍","html":"🌐","java":"☕"}
        st.markdown(f"""<div class="bmad-card" style="padding:16px;">
            <div style="display:flex;justify-content:space-between;font-size:0.82rem;font-weight:700;color:#1e293b;margin-bottom:6px;">
                <span>{icons.get(top_lang,'📄')} Top Language: {top_lang.title()}</span><span style="color:#FF6B6B;">{top_lang_pct}%</span>
            </div>
            <div style="background:#f1f5f9;border-radius:8px;height:8px;overflow:hidden;">
                <div style="background:#FF6B6B;width:{top_lang_pct}%;height:100%;border-radius:8px;"></div>
            </div>
        </div>""", unsafe_allow_html=True)
    with pb_col3:
        debug_rate = round(total_debug / max(total_runs,1) * 100)
        st.markdown(f"""<div class="bmad-card" style="padding:16px;">
            <div style="display:flex;justify-content:space-between;font-size:0.82rem;font-weight:700;color:#1e293b;margin-bottom:6px;">
                <span>🔧 Debug Iterations</span><span style="color:#f97316;">{total_debug} total</span>
            </div>
            <div style="background:#f1f5f9;border-radius:8px;height:8px;overflow:hidden;">
                <div style="background:#f97316;width:{min(debug_rate,100)}%;height:100%;border-radius:8px;"></div>
            </div>
        </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    main_col, side_col = st.columns([3, 2])

    # ── Suggested projects grid ───────────────────────────────────────────────
    with main_col:
        st.markdown("### 💡 Suggested Projects")
        st.caption("Click **⚡ Build** to instantly start the pipeline with that prompt.")

        for i in range(0, len(SUGGESTED_PROJECTS), 2):
            row = st.columns(2)
            for j, col in enumerate(row):
                idx = i+j
                if idx >= len(SUGGESTED_PROJECTS): break
                sp = SUGGESTED_PROJECTS[idx]
                with col:
                    # Check if already built
                    existing = any(sp["prompt"][:30].lower() in p["prompt"].lower()
                                   for p in projects_all)
                    border_clr = "#6BCB77" if existing else sp["color"]
                    status_tag = (f'<span class="badge b-green">✅ Already built</span>'
                                  if existing else
                                  f'<span class="badge b-gray">{sp["category"]}</span>')
                    st.markdown(f"""
                    <div class="sug-card" style="border-top:3px solid {border_clr};">
                        <div style="display:flex;align-items:center;gap:9px;margin-bottom:8px;">
                            <span style="font-size:1.5rem;">{sp['icon']}</span>
                            <div>
                                <div style="font-size:0.86rem;font-weight:800;color:#1e293b;">{sp['title']}</div>
                                {status_tag}
                            </div>
                        </div>
                        <div style="font-size:0.72rem;color:#64748b;line-height:1.5;">
                            {sp['prompt'][:75]}…
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                    import urllib.parse
                    encoded = urllib.parse.quote_plus(sp["prompt"])
                    btn_lbl = "🔄 Rebuild" if existing else "⚡ Build"
                    if st.button(btn_lbl, key=f"sug_{idx}",
                                 use_container_width=True,
                                 type="primary" if not existing else "secondary"):
                        st.session_state["prompt_value"]     = sp["prompt"]
                        st.session_state["auto_start_build"] = True
                        st.session_state["active_page"]      = "🚀  Build"
                        st.rerun()

    # ── Live Activity Feed — built from local sessions (always populated) ─────
    with side_col:
        st.markdown("### 🕐 Activity Feed")
        st.caption("Local pipeline history + Langfuse traces")

        # Build unified activity from sessions + Langfuse
        activities = []

        # Local sessions (always available, richest data)
        for s in reversed(filtered_sess[-15:]):
            status_icon = "✅" if s.get("status")=="passed" else "❌"
            req = s.get("user_request","")[:35]
            activities.append({
                "icon": status_icon,
                "title": req + ("…" if len(s.get("user_request",""))>35 else ""),
                "sub":  f"Pipeline · {s.get('date','')[:10]} · {s.get('status','unknown')}",
                "type": "pipeline",
                "color": "#059669" if s.get("status")=="passed" else "#ef4444",
            })

        # Langfuse traces (when available — augments the feed)
        for t in lf_traces[:8]:
            name = t.get("name","—").replace("bmad-","").replace("-"," ").title()
            ts   = t.get("timestamp","")[:10]
            lat  = f"{t.get('latency',0):.1f}s" if t.get("latency") else ""
            activities.append({
                "icon": "🤖",
                "title": name,
                "sub": f"Agent trace · {ts} {lat}",
                "type": "trace",
                "color": "#FF6B6B",
            })

        # Sort newest first, deduplicate, limit 18
        seen = set()
        unique_acts = []
        for a in reversed(activities):
            key = a["title"][:20]
            if key not in seen:
                seen.add(key)
                unique_acts.append(a)
        unique_acts = unique_acts[:18]

        if unique_acts:
            for a in unique_acts:
                st.markdown(f"""
                <div class="activity-item">
                    <span style="font-size:1.1rem;min-width:24px;text-align:center;">{a['icon']}</span>
                    <div style="flex:1;min-width:0;">
                        <div style="font-size:0.8rem;font-weight:700;color:#1e293b;
                                    white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{a['title']}</div>
                        <div style="font-size:0.66rem;color:#94a3b8;">{a['sub']}</div>
                    </div>
                    <span class="dot-live" style="flex-shrink:0;"
                          title="Recent"></span>
                </div>""", unsafe_allow_html=True)
        else:
            for _ in range(4):
                st.markdown('<div class="skeleton"></div><div class="skeleton" style="width:70%"></div>',
                            unsafe_allow_html=True)
            st.caption("_Run a pipeline to populate the activity feed._")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: BUILD
# Build section fix: auto_start_build flag persists until the pipeline
# actually starts. Previously it could be cleared before prompt was ready.
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🚀  Build":

    st.markdown("""
    <div style="background:white;border:1.5px solid #e2e8f0;border-left:6px solid #FF6B6B;
                border-radius:18px;padding:24px 28px;margin-bottom:20px;
                box-shadow:0 4px 20px rgba(255,0,110,0.07);">
        <div style="font-size:1.9rem;font-weight:900;color:#1e293b;">🚀 Build Something</div>
        <div style="color:#64748b;margin-top:5px;">
            Your <strong style="color:#FF6B6B;">10-agent AI team</strong> will
            <strong>design → code → test → deliver</strong> from a single sentence.
        </div>
        <div style="display:flex;gap:20px;margin-top:12px;flex-wrap:wrap;">
            <span style="color:#64748b;font-size:0.8rem;"><strong>⚡ ~2-3 min</strong> per build</span>
            <span style="color:#64748b;font-size:0.8rem;"><strong>🤖 10 agents</strong></span>
            <span style="color:#64748b;font-size:0.8rem;"><strong>🧪 Mock-tested</strong></span>
            <span style="color:#64748b;font-size:0.8rem;"><strong>🛡️ Guardrails</strong></span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Consume auto_start flag before any widget renders
    should_auto = st.session_state.get("auto_start_build", False)
    if should_auto:
        st.session_state["auto_start_build"] = False  # consume immediately

    col_in, col_side = st.columns([3, 1])

    with col_in:
        current_prompt = st.session_state.get("prompt_value", "")
        prompt = st.text_area(
            "**💬 What do you want to build?**",
            value=current_prompt,
            placeholder="e.g. Build a real-time stock portfolio tracker with charts using Streamlit…",
            height=140,
        )
        st.session_state["prompt_value"] = prompt

        char_clr = "#34d399" if len(prompt) <= 2000 else "#f87171"
        cc, _, cb = st.columns([2, 1, 1])
        with cc:
            st.markdown(f'<span style="color:{char_clr};font-size:0.78rem;">{len(prompt)}/2000</span>',
                        unsafe_allow_html=True)
        with cb:
            run_btn = st.button("▶  Run Pipeline", type="primary",
                                use_container_width=True,
                                disabled=st.session_state.pipeline_running)

    with col_side:
        st.markdown("**🛡️ Guardrail Check**")
        if prompt.strip():
            try:
                from core.guardrails import validate_input, GuardrailError
                try:
                    validate_input(prompt)
                    st.success("✅ Prompt valid", icon="✅")
                except GuardrailError as e:
                    st.error(f"🚫 {e.rule}", icon="🚫")
                    st.caption(e.message)
            except Exception:
                pass
        else:
            st.caption("Type a prompt to validate.")

    st.divider()

    # ── PIPELINE EXECUTION ─────────────────────────────────────────────────────
    # Architecture: subprocess runs in a background thread that fills a shared
    # mutable list. Main thread polls that list via periodic st.rerun(), so the
    # ⛔ Stop Build button is always clickable — the main thread is never blocked.
    # ─────────────────────────────────────────────────────────────────────────────
    should_run = (run_btn and prompt.strip()) or (should_auto and prompt.strip())

    # ── Keyword → agent mapping ────────────────────────────────────────────────
    # Designer and Scrum Master both print "[4/10]" (they run in PARALLEL).
    # Distinguish them by the unique text on each line, e.g. "Designer ┐" vs "Scrum Master┘".
    # Sequential keywords come from the roadmap block; agent-runner keywords from runtime logs.
    KEYWORDS = [
        ("[1/10]",         "Analyst"),
        ("[2/10]",         "Product Manager"),
        ("[3/10]",         "Architect"),
        # Parallel pair — detect by unique fragment on each roadmap line
        ("[4/10] designer","Designer"),
        ("[4/10] scrum",   "Scrum Master"),
        ("[4/10]",         "Designer"),     # generic fallback → Designer (Scrum caught by name below)
        ("scrum master",   "Scrum Master"), # catch any line mentioning Scrum Master
        ("[5/10]",         "Developer"),
        ("[6/10]",         "Code Reviewer"),
        ("[7/10]",         "Executor"),
        ("[8/10]",         "Mock Tester"),
        ("[9/10]",         "QA Engineer"),
        # Agent-runner runtime markers (printed during execution)
        ("analyst —",         "Analyst"),
        ("product manager —", "Product Manager"),
        ("architect —",       "Architect"),
        ("designer —",        "Designer"),
        ("scrum master —",    "Scrum Master"),
        ("developer —",       "Developer"),
        ("code reviewer —",   "Code Reviewer"),
        ("executor —",        "Executor"),
        ("mock tester —",     "Mock Tester"),
        ("qa engineer —",     "QA Engineer"),
    ]
    # Agents that run in parallel — neither marks the other as "done"
    _PARALLEL = {"Designer", "Scrum Master"}

    step_names = [n for _,n,_,_,_ in AGENT_STEPS]

    import html as _html

    def render_tracker(trk_ph, step_states: dict, elapsed_total: float = 0.0) -> None:
        """Full-width tracker: KPI metrics + progress bar + agent grid."""
        done_count = sum(1 for n in step_names if step_states.get(n) == "done")
        run_name   = next((n for n in step_names if step_states.get(n) == "running"), None)
        pct        = done_count / len(step_names)
        if done_count > 0 and elapsed_total > 0:
            avg = elapsed_total / done_count
            rem = max(0, avg * (len(step_names) - done_count - (1 if run_name else 0)))
            eta_str = (f"~{int(rem//60)}m {int(rem%60)}s left" if rem >= 60
                       else (f"~{int(rem)}s left" if rem > 3 else "almost done…"))
        else:
            eta_str = "calculating…"
        e_min = int(elapsed_total // 60)
        e_sec = int(elapsed_total  % 60)
        elapsed_str = f"{e_min}m {e_sec:02d}s" if e_min else f"{int(elapsed_total)}s"

        with trk_ph.container():
            c1, c2, c3, c4 = st.columns(4)
            for col, lbl, val, accent, bg, txt in [
                (c1,"⏱ Elapsed",   elapsed_str,             "#FF6B00","#fff8f0","#7a2e00"),
                (c2,"✅ Completed", f"{done_count}/{len(step_names)}","#00C853","#e8fff0","#004d1f"),
                (c3,"⚡ Running",   run_name or "—",          "#FF6B6B","#fff0f8","#7a0034"),
                (c4,"⏳ Est. left", eta_str,                  "#0090FF","#e8f4ff","#003d7a"),
            ]:
                col.markdown(
                    f'<div style="background:{bg};border:2px solid {accent};border-radius:12px;'
                    f'padding:14px 10px;text-align:center;box-shadow:0 3px 14px {accent}40;">'
                    f'<div style="font-size:0.68rem;font-weight:800;color:{accent};'
                    f'text-transform:uppercase;letter-spacing:0.06em;">{lbl}</div>'
                    f'<div style="font-size:1.45rem;font-weight:900;color:{txt};margin-top:4px;">{val}</div>'
                    f'</div>', unsafe_allow_html=True)
            bar_val  = min(1.0, pct + (0.02 if run_name else 0))
            pct_text = ("🎉 Complete!" if pct >= 1.0
                        else f"🔥 {int(pct*100)}%  —  {done_count} of {len(step_names)} agents done")
            st.progress(bar_val, text=pct_text)
            st.markdown(
                '<style>[data-testid="stProgressBar"]>div>div{'
                'background:linear-gradient(90deg,#FF6B6B,#FF6B00,#AA00FF,#00C853)!important;'
                'border-radius:8px!important;}</style>', unsafe_allow_html=True)
            cols = st.columns(5)
            for idx, (icon, name, color, key, desc) in enumerate(AGENT_STEPS):
                st_val  = step_states.get(name, "waiting")
                elapsed = step_states.get(f"{name}_elapsed", "")
                with cols[idx % 5]:
                    if st_val == "done":
                        bg_col = "linear-gradient(135deg,#00C853,#00e676)"
                        bd_col = "#00e676"; st_icon = "✅"; lbl_col = "#fff"
                        sub = elapsed or "done"; shadow = "0 4px 14px rgba(0,200,83,0.55)"
                    elif st_val == "running":
                        bg_col = "linear-gradient(135deg,#FF6B6B,#FF6B00)"
                        bd_col = "#FF6B00"; st_icon = "⚡"; lbl_col = "#fff"
                        sub = "running…"; shadow = "0 4px 20px rgba(255,0,110,0.65)"
                    elif st_val == "failed":
                        bg_col = "linear-gradient(135deg,#FF1744,#f43f5e)"
                        bd_col = "#fb7185"; st_icon = "❌"; lbl_col = "#fff"
                        sub = "failed"; shadow = "0 4px 14px rgba(255,23,68,0.5)"
                    else:
                        bg_col = "linear-gradient(135deg,#1e0035,#2d0050)"
                        bd_col = "#5e3080"; st_icon = "○"; lbl_col = "#b39ddb"
                        sub = "waiting"; shadow = "none"
                    st.markdown(
                        f'<div style="background:{bg_col};border:2px solid {bd_col};'
                        f'border-radius:12px;padding:10px 6px;text-align:center;'
                        f'margin-bottom:6px;box-shadow:{shadow};transition:all 0.3s;">'
                        f'<div style="font-size:1.3rem;">{st_icon}</div>'
                        f'<div style="font-size:0.65rem;font-weight:800;color:{lbl_col};'
                        f'margin-top:4px;line-height:1.3;text-shadow:0 1px 3px rgba(0,0,0,0.4);">{icon} {name}</div>'
                        f'<div style="font-size:0.56rem;color:rgba(255,255,255,0.75);margin-top:3px;">{sub}</div>'
                        f'</div>', unsafe_allow_html=True)

    # ── START: launch subprocess in a background thread ───────────────────────
    if should_run:
        try:
            from core.guardrails import validate_input, GuardrailError
            validate_input(prompt)
        except Exception as e:
            st.error(f"🚫 {e}")
            st.stop()

        buf   = []          # shared mutable list — thread appends, main reads
        done  = [False]     # mutable wrapper — thread sets done[0]=True on exit
        pid   = [None]      # subprocess PID stored after Popen

        proc = subprocess.Popen(
            [sys.executable, "-W", "ignore", "-m", "core.main", prompt],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, cwd=str(ROOT), bufsize=1,
        )
        pid[0] = proc.pid

        def _reader():
            for line in proc.stdout:
                buf.append(line)
            proc.wait()
            done[0] = True

        threading.Thread(target=_reader, daemon=True).start()

        # Store shared state so polling reruns can access it
        st.session_state["_pipeline_buf"]    = buf
        st.session_state["_pipeline_done"]   = done
        st.session_state["_pipeline_pid"]    = pid[0]
        st.session_state["_pipeline_start"]  = time.time()
        st.session_state["_pipeline_cursor"] = 0
        st.session_state["_step_states"]     = {n: "waiting" for n in step_names}
        st.session_state["_active_agent"]    = [None]
        st.session_state["_agent_start_t"]   = [None]
        st.session_state.pipeline_running    = True
        st.toast("🚀 Pipeline started! Building your app…", icon="⚡")
        st.rerun()   # switch immediately to the polling branch below

    # ── POLLING: runs on every rerun while pipeline_running=True ─────────────
    elif st.session_state.pipeline_running:
        buf          = st.session_state.get("_pipeline_buf",   [])
        done         = st.session_state.get("_pipeline_done",  [True])
        build_start  = st.session_state.get("_pipeline_start", time.time())
        cursor       = st.session_state.get("_pipeline_cursor", 0)
        step_states  = st.session_state.get("_step_states",    {n:"waiting" for n in step_names})
        active_agent = st.session_state.get("_active_agent",   [None])
        agent_start_t= st.session_state.get("_agent_start_t",  [None])

        # ── ⛔ STOP BUILD BUTTON — always rendered first, always clickable ──────
        stop_col, banner_col = st.columns([1, 5])
        with stop_col:
            if st.button("⛔  Stop Build", type="secondary", use_container_width=True):
                _pid = st.session_state.get("_pipeline_pid")
                if _pid:
                    try:
                        os.kill(_pid, signal.SIGTERM)
                    except Exception:
                        pass
                st.session_state.pipeline_running    = False
                st.session_state["_pipeline_buf"]    = []
                st.session_state["_pipeline_done"]   = [True]
                st.session_state["_pipeline_pid"]    = None
                st.warning("🛑 Build cancelled by user.")
                st.cache_data.clear()
                st.stop()
        with banner_col:
            st.markdown(
                '<div style="background:linear-gradient(135deg,#FF6B6B,#FF6B00);'
                'border-radius:12px;padding:12px 20px;display:flex;align-items:center;gap:14px;'
                'box-shadow:0 6px 28px rgba(255,0,110,0.4);">'
                '<div style="font-size:1.6rem;animation:spin 1.6s linear infinite;">⚙️</div>'
                '<div style="font-weight:800;color:#fff;font-size:0.95rem;">'
                '🚀 Pipeline Running — 10 agents building your app…</div></div>'
                '<style>@keyframes spin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}</style>',
                unsafe_allow_html=True)

        # ── Placeholders ──────────────────────────────────────────────────────
        trk_ph  = st.empty()
        st.markdown("#### 🖥️ Live Terminal Output")
        out_ph  = st.empty()
        stat_ph = st.empty()

        # ── Process new lines since last rerun ───────────────────────────────
        snapshot    = list(buf)   # safe snapshot (thread may still append)
        new_lines   = snapshot[cursor:]
        now_elapsed = time.time() - build_start

        for line in new_lines:
            line_lower = line.lower()

            for kw, agent_name in KEYWORDS:
                if kw in line_lower and agent_name in step_names:
                    # When Developer starts → both parallel agents are done
                    if agent_name == "Developer":
                        for pa in _PARALLEL:
                            if step_states.get(pa) in ("waiting", "running"):
                                _ag_e = round(time.time() - (agent_start_t[0] or build_start), 1)
                                step_states[pa] = "done"
                                step_states[f"{pa}_elapsed"] = f"{_ag_e}s"
                    # Sequential transition: mark previous (non-parallel) agent done
                    elif (active_agent[0]
                          and active_agent[0] != agent_name
                          and active_agent[0] not in _PARALLEL):
                        _ag_e = round(time.time() - (agent_start_t[0] or build_start), 1)
                        step_states[active_agent[0]] = "done"
                        step_states[f"{active_agent[0]}_elapsed"] = f"{_ag_e}s"

                    # Start agent if not already started
                    if step_states.get(agent_name) == "waiting":
                        step_states[agent_name] = "running"
                        # For parallel agents keep tracking the last one started
                        active_agent[0]  = agent_name
                        agent_start_t[0] = time.time()
                    break

            # Only flag a REAL Python traceback as a failure — not any word "error"
            # (LLM output often contains "error" in generated code/docs)
            if "Traceback (most recent call last)" in line and active_agent[0]:
                step_states[active_agent[0]] = "failed"

            # Surface rate-limit info (tier switches are normal, not failures)
            if "DAILY TOKEN LIMIT REACHED" in line or "exhausted their daily token quota" in line:
                stat_ph.warning("⛔ **Daily quota reached** — auto-switching to fallback model.")
            elif "Switching to Tier" in line:
                tier = "2 (Groq 8b)" if "Tier 2" in line else "3 (Cerebras)"
                stat_ph.info(f"🔄 Rate limit hit — switched to Tier {tier}. Build continues…")

        # Persist updated state
        st.session_state["_pipeline_cursor"]  = len(snapshot)
        st.session_state["_step_states"]      = step_states
        st.session_state["_active_agent"]     = active_agent
        st.session_state["_agent_start_t"]    = agent_start_t

        # Render tracker + terminal
        render_tracker(trk_ph, step_states, now_elapsed)
        safe_text = _html.escape("".join(snapshot[-80:]))
        out_ph.markdown(
            f'<div style="background:#08001a;color:#d8b4fe;font-family:monospace;'
            f'font-size:0.72rem;line-height:1.6;border-radius:10px;'
            f'padding:14px 18px;max-height:320px;overflow-y:auto;'
            f'white-space:pre-wrap;word-break:break-all;border:1px solid #2d0050;">'
            f'{safe_text}</div>', unsafe_allow_html=True)

        # ── Finished? ─────────────────────────────────────────────────────────
        if done[0]:
            total_elapsed = round(time.time() - build_start, 1)
            all_out = "".join(snapshot)

            # Mark the last running agent as done
            if active_agent[0] and step_states.get(active_agent[0]) == "running":
                step_states[active_agent[0]] = "done"
                step_states[f"{active_agent[0]}_elapsed"] = f"{round(now_elapsed,1)}s"

            # ── Success signals (any one is enough) ───────────────────────────
            # 1. Output explicitly says "STATUS : passed"
            # 2. App file path was saved (pipeline completed code gen)
            # 3. QA verdict says PASS
            # 4. ≥ 7 agents completed (partial success — rate-limited but code saved)
            done_agents = sum(1 for v in step_states.values() if v == "done")
            _is_success = (
                ("STATUS          : passed" in all_out)
                or ("APP SAVED TO" in all_out)
                or ("VERDICT: PASS"  in all_out.upper())
                or (done_agents >= 7)   # ≥ 7/10 agents done → app was generated
            )

            # ── Fatal quota exhaustion (ALL models dead, no fallback) ─────────
            _is_quota_dead = (
                "DAILY TOKEN LIMIT REACHED" in all_out
                and "exhausted their daily token quota" in all_out
            )

            # Mark any lingering agents: if pipeline succeeded, all are done
            if _is_success:
                for n in step_names:
                    if step_states.get(n) in ("waiting", "running"):
                        step_states[n] = "done"

            render_tracker(trk_ph, step_states, total_elapsed)
            st.session_state.pipeline_running = False
            st.session_state["_pipeline_pid"] = None

            if _is_quota_dead:
                import re as _re
                m = _re.search(r"resets in: (.+)", all_out)
                retry_msg = f" Quota resets in **{m.group(1).strip()}**." if m else ""
                stat_ph.error(f"⛔ **Daily token quota exhausted.**{retry_msg} "
                              "Wait for reset or [upgrade Groq plan](https://console.groq.com/settings/billing).")
            elif _is_success:
                stat_ph.success(
                    f"✅ **Done in {total_elapsed}s** — "
                    f"head to 📁 Projects to view & run your app.")
                st.balloons()
                st.cache_data.clear()
            else:
                stat_ph.error(
                    "❌ Pipeline finished with errors — check the terminal output above. "
                    "Common causes: all LLM models rate-limited, or a network error. "
                    "Try again in a few minutes.")
        else:
            # Keep polling every 0.5 s — main thread is free so stop button works
            time.sleep(0.5)
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: PROJECTS
# Fix: entire card is now an <a href> link using query params.
# No separate "Open →" button needed.
# ══════════════════════════════════════════════════════════════════════════════
elif page == "📁  Projects":

    st.markdown('<div class="page-title">📁 Projects</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Click any project card to open full details, artifacts, and live preview.</div>',
                unsafe_allow_html=True)
    st.divider()

    projects = get_projects()
    if not projects:
        st.info("No projects yet — go to **🚀 Build** to generate your first one!")
        st.stop()

    # ── DETAIL VIEW ──────────────────────────────────────────────────────────
    if st.session_state.selected_project:
        proj = next((p for p in projects if p["slug"]==st.session_state.selected_project), None)
        if not proj:
            st.session_state.selected_project = None
            st.rerun()

        if st.button("← Back to all projects", key="back_btn"):
            st.session_state.selected_project = None
            st.session_state.show_app_inline  = {}
            st.rerun()

        li  = {"python":"🐍","html":"🌐","java":"☕"}.get(proj["app_lang"],"📄")
        vc  = {"passed":"#dcfce7","failed":"#fee2e2"}.get(proj["verdict"],"#fef9c3")
        vt  = {"passed":"#166534","failed":"#991b1b"}.get(proj["verdict"],"#854d0e")
        vl  = {"passed":"✅ PASSED","failed":"❌ FAILED"}.get(proj["verdict"],"⏳ UNKNOWN")
        ml  = {"passed":"🧪 MOCK PASS","failed":"🧪 MOCK FAIL"}.get(proj["mock"],"🧪 MOCK SKIP")

        st.markdown(f"""
        <div class="bmad-card" style="border-left:6px solid #FF6B6B;margin-bottom:18px;">
            <div style="font-size:1.5rem;font-weight:900;color:#1e293b;">{li} {proj['name']}</div>
            <div style="margin-top:9px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
                <span style="background:{vc};color:{vt};padding:4px 12px;border-radius:20px;
                             font-size:0.75rem;font-weight:700;">{vl}</span>
                <span class="badge b-blue">{ml}</span>
                <span class="badge b-purple">{proj['app_lang'].upper()}</span>
                <span style="color:#94a3b8;font-size:0.74rem;margin-left:5px;">📅 {proj['modified']}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        ab1, ab2, ab3 = st.columns(3)
        with ab1:
            show = st.session_state.show_app_inline.get(proj["slug"], False)
            if proj["app_file"] and st.button(
                    "🙈 Hide Preview" if show else "📺 View App Inline",
                    key="toggle_app", use_container_width=True, type="primary"):
                st.session_state.show_app_inline[proj["slug"]] = not show
                st.rerun()
        with ab2:
            if st.button("✏️ Edit Prompt & Rebuild", key="edit_btn", use_container_width=True):
                st.session_state["_show_edit_proj"] = proj["slug"]
                st.rerun()
        with ab3:
            fname = Path(proj["app_file"]).name if proj["app_file"] else "N/A"
            st.caption(f"📁 `{fname}`")

        if st.session_state.show_app_inline.get(proj["slug"]):
            st.divider()
            render_app_inline(proj)

        st.divider()

        # Prompt section (always shows something — intelligent recovery)
        st.markdown("**💬 Original Prompt**")
        st.markdown(f'<div class="prompt-box">{proj["prompt"]}</div>',
                    unsafe_allow_html=True)

        if st.session_state.get("_show_edit_proj") == proj["slug"]:
            st.markdown("**✏️ Edit & Rebuild**")
            edited = st.text_area("New prompt:", value=proj["prompt"],
                                  height=100, key=f"ep_{proj['slug']}")
            ec1, ec2 = st.columns(2)
            with ec1:
                if st.button("🔄 Rebuild", type="primary", use_container_width=True):
                    st.session_state["prompt_value"]     = edited
                    st.session_state["auto_start_build"] = True
                    st.session_state["active_page"]      = "🚀  Build"
                    st.session_state["_show_edit_proj"]  = None
                    st.rerun()
            with ec2:
                if st.button("Cancel", use_container_width=True):
                    st.session_state["_show_edit_proj"] = None
                    st.rerun()
        else:
            if st.button("✏️ Edit & Rebuild", key="edit_open"):
                st.session_state["_show_edit_proj"] = proj["slug"]
                st.rerun()

        st.divider()

        # Find matching session for extra metadata
        sessions = load_sessions()
        matched_session = None
        for s in sessions:
            if proj["prompt"][:30] in (s.get("user_request","")[:30]):
                matched_session = s
                break

        if matched_session:
            ms1, ms2, ms3, ms4 = st.columns(4)
            ms1.metric("Status",    matched_session.get("status","—").upper())
            ms2.metric("Language",  matched_session.get("language","—").upper() or "—")
            ms3.metric("Agents Run", len(matched_session.get("agents_run",[])))
            ms4.metric("Debug Iters", matched_session.get("debug_iterations",0))
            st.divider()

        # All documents
        st.markdown("**📂 All Project Artifacts**")
        tabs = st.tabs(["📋 Brief","📄 Spec","🏗️ Design","📝 Stories",
                        "💻 Code","🧪 Mock Tests","🔬 Test Results","📊 Test Plan","🛡️ Strategy"])
        tab_map = [
            ("project-brief.md","md"),("functional-spec.md","md"),
            ("solution-design.md","md"),("user-stories.md","md"),
            ("__code__","code"),("mock-tests.py","py"),
            ("mock-test-results.md","md"),("test-plan.md","md"),("test-strategy.md","md"),
        ]
        for tab,(fname,fmt) in zip(tabs,tab_map):
            with tab:
                if fname == "__code__":
                    if proj["app_file"] and Path(proj["app_file"]).exists():
                        ext_l = "python" if proj["app_file"].endswith(".py") else "html"
                        st.code(Path(proj["app_file"]).read_text(encoding="utf-8"), language=ext_l)
                    else:
                        st.caption("_(code file not found)_")
                elif proj["docs"].get(fname):
                    if fmt=="md": st.markdown(proj["docs"][fname])
                    else: st.code(proj["docs"][fname],language="python")
                else:
                    st.caption("_(not available for this project)_")

        st.stop()

    # ── PROJECT LIST ────────────────────────────────────────────────────────
    fc1,fc2,fc3 = st.columns([2,1,1])
    with fc1: search = st.text_input("🔍 Search", placeholder="stock, bmi, inventory…")
    with fc2: fv = st.selectbox("Status", ["All","Passed","Failed","Unknown"])
    with fc3: fl = st.selectbox("Language", ["All","Python","HTML","Java"])

    filtered = projects
    if search:  filtered=[p for p in filtered if search.lower() in p["name"].lower()
                           or search.lower() in p["prompt"].lower()]
    if fv!="All": filtered=[p for p in filtered if p["verdict"]==fv.lower()]
    if fl!="All": filtered=[p for p in filtered if p["app_lang"]==fl.lower()]

    st.markdown(f'<div style="color:#64748b;font-size:0.82rem;margin-bottom:8px;">'
                f'<strong>{len(filtered)}</strong> of <strong>{len(projects)}</strong> projects — '
                f'click any card to open</div>', unsafe_allow_html=True)
    st.divider()

    # Fully clickable project cards via <a href="?open_project=slug"> + delete button
    if "delete_confirm" not in st.session_state:
        st.session_state["delete_confirm"] = None

    def _delete_project(slug: str):
        import shutil
        # Remove output folder
        out_folder = OUTPUT_DIR / slug
        if out_folder.exists():
            shutil.rmtree(str(out_folder))
        # Remove app file(s)
        for ext in [".py", ".html"]:
            af = APPS_DIR / f"{slug}{ext}"
            if af.exists():
                af.unlink()
        java_dir = APPS_DIR / slug
        if java_dir.is_dir():
            shutil.rmtree(str(java_dir))
        # Remove from sessions.json
        try:
            with open(str(MEMORY_FILE), encoding="utf-8") as f:
                sessions = json.load(f)
            sessions = [s for s in sessions
                        if slug not in (s.get("output_file","") or "")
                        and slug not in (s.get("session_id","") or "")]
            with open(str(MEMORY_FILE), "w", encoding="utf-8") as f:
                json.dump(sessions, f, indent=2)
        except Exception:
            pass
        # Clear caches so list refreshes
        get_projects.clear()
        st.session_state["delete_confirm"] = None

    for proj in filtered:
        vb = {"passed":'<span class="badge b-green">✅ PASSED</span>',
              "failed":'<span class="badge b-red">❌ FAILED</span>',
              "unknown":'<span class="badge b-amber">⏳ UNKNOWN</span>'}.get(proj["verdict"],"")
        mb = {"passed":'<span class="badge b-blue">🧪 MOCK PASS</span>',
              "failed":'<span class="badge b-red">🧪 MOCK FAIL</span>',
              "skipped":'<span class="badge b-purple">🧪 MOCK SKIP</span>'}.get(proj["mock"],"")
        li = {"python":"🐍","html":"🌐","java":"☕"}.get(proj["app_lang"],"📄")
        pp = (proj["prompt"][:85]+"…") if len(proj["prompt"])>85 else proj["prompt"]

        card_col, del_col = st.columns([11, 1])
        with card_col:
            st.markdown(f"""
            <a href="?open_project={proj['slug']}" target="_top" class="proj-card"
               style="display:block;text-decoration:none;color:inherit;margin-bottom:4px;">
                <div style="font-size:1.05rem;font-weight:900;color:#1e293b;
                            background:#eef2ff;display:inline-block;padding:3px 14px;
                            border-radius:8px;border-left:4px solid #FF6B6B;">
                    {li} {proj['name']}
                </div>
                <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap;align-items:center;">
                    {vb} {mb}
                    <span class="badge b-purple">{proj['app_lang'].upper()}</span>
                    <span style="color:#94a3b8;font-size:0.7rem;">📅 {proj['modified']}</span>
                </div>
                <div style="margin-top:7px;color:#64748b;font-size:0.8rem;font-style:italic;">
                    "{pp}"
                </div>
            </a>
            """, unsafe_allow_html=True)
        with del_col:
            confirming = st.session_state["delete_confirm"] == proj["slug"]
            if confirming:
                st.markdown('<div style="margin-top:14px;"></div>', unsafe_allow_html=True)
                if st.button("✅ Yes, delete", key=f"del_yes_{proj['slug']}",
                             use_container_width=True, type="primary"):
                    _delete_project(proj["slug"])
                    st.toast(f"🗑️ Project deleted!", icon="✅")
                    st.rerun()
                if st.button("Cancel", key=f"del_no_{proj['slug']}",
                             use_container_width=True):
                    st.session_state["delete_confirm"] = None
                    st.rerun()
            else:
                st.markdown('<div style="margin-top:18px;"></div>', unsafe_allow_html=True)
                if st.button("🗑️", key=f"del_{proj['slug']}", use_container_width=True,
                             help="Delete this project"):
                    st.session_state["delete_confirm"] = proj["slug"]
                    st.rerun()
        st.divider()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: AGENTS
# Performance fix: single @st.cache_data(ttl=90) Langfuse call replaces
# previous pattern of fetching inside each agent card render.
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🤖  Agents":

    st.markdown('<div class="page-title">🤖 Agent Roster</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Live performance stats, architecture, and real-time status for all 10 agents.</div>',
                unsafe_allow_html=True)

    days = time_range_bar("ag")
    st.divider()

    AGENT_DEFS = [
        ("🔍","Analyst",       "Business Analyst",    "llama-3.1-8b-instant","#a78bfa","analyst",
         "Parses user request. Extracts goals, constraints, project type, tech hints. Produces concise brief for PM."),
        ("📋","Product Manager","Product Manager",     "llama-3.1-8b-instant","#60a5fa","product-manager",
         "Converts analyst brief into full Functional Spec: user goals, features, acceptance criteria, edge cases."),
        ("🏗️","Architect",     "Solution Architect",  "llama-3.3-70b-versatile","#34d399","architect",
         "Designs tech architecture: stack, data models, APIs, component flow, dependencies, scalability."),
        ("🎨","Designer",      "UI/UX Designer",      "llama-3.1-8b-instant","#fbbf24","designer",
         "Creates UI design system: colour palette, typography, component library, layout grid. Runs parallel."),
        ("📅","Scrum Master",  "Scrum Master",        "llama-3.1-8b-instant","#fb923c","scrum-master",
         "Breaks spec into user stories with acceptance criteria and story points. Runs parallel with Designer."),
        ("💻","Developer",     "Senior Developer",    "llama-3.3-70b-versatile","#f43f5e","developer",
         "Writes production-quality code. Can receive NEEDS_FIXES from reviewer and iterate."),
        ("👁️","Code Reviewer", "Code Reviewer",       "llama-3.3-70b-versatile","#8b5cf6","code-reviewer",
         "Reviews code for bugs, security issues, best practices. Returns APPROVED or NEEDS_FIXES verdict."),
        ("⚡","Executor",      "Code Executor",       "— (pure execution)","#06b6d4","executor",
         "Runs syntax checks (Python AST / javac / html-parser). No LLM — deterministic execution engine."),
        ("🧪","Mock Tester",   "Mock Test Engineer",  "llama-3.3-70b-versatile","#10b981","mock-tester",
         "Writes pytest code with unittest.mock. Mocks external APIs, runs tests, returns PASS/FAIL."),
        ("✅","QA Engineer",   "QA Engineer",         "llama-3.1-8b-instant","#84cc16","qa-engineer",
         "Writes Test Strategy + Test Plan. Reads mock results. Issues final VERDICT: PASS or FAIL."),
    ]

    # Fetch from both local sessions and Langfuse
    sessions = load_sessions()
    sess_filt = sessions_in_range(sessions, days)
    lf        = fetch_lf(days)
    astats    = lf_agent_stats(lf.get("all",[]))

    # Compute local agent execution counts from sessions
    local_agent_counts = {}
    for s in sess_filt:
        for a in s.get("agents_run",[]):
            local_agent_counts[a] = local_agent_counts.get(a,0)+1

    # Pipeline flow visual
    st.markdown("**🔗 Pipeline Execution Flow**")
    flow_parts = []
    for i,(icon,name,_,_,color,key,_) in enumerate(AGENT_DEFS):
        local_runs = local_agent_counts.get(key.replace("-","_"), 0)
        lf_runs    = astats.get(key,{}).get("runs",0)
        total_runs = local_runs + lf_runs
        is_p  = name in ("Designer","Scrum Master")
        border= f"2px dashed {color}" if is_p else f"2px solid {color}"
        dot   = f'<span class="dot-live"></span>' if total_runs>0 else f'<span class="dot-idle"></span>'
        flow_parts.append(
            f'<span style="border:{border};border-radius:8px;padding:4px 10px;'
            f'color:{color};font-size:0.76rem;font-weight:700;'
            f'display:inline-flex;align-items:center;gap:5px;">{dot}{icon} {name}</span>'
        )
        if i < len(AGENT_DEFS)-1:
            flow_parts.append('<span style="color:#cbd5e1;font-size:0.8rem;">→</span>')
    st.markdown(
        f'<div style="display:flex;flex-wrap:wrap;gap:5px;align-items:center;margin-bottom:6px;">'
        f'{"".join(flow_parts)}</div>',
        unsafe_allow_html=True,
    )
    st.caption("🟢 Active (has run data)  |  ⚪ No data  |  Dashed = runs in parallel")
    st.divider()

    # Agent cards
    c1, c2 = st.columns(2)
    for i,(icon,name,role,model,color,key,desc) in enumerate(AGENT_DEFS):
        col = c1 if i%2==0 else c2
        s     = astats.get(key,{})
        lats  = s.get("lats",[])
        lf_r  = s.get("runs",0)
        local_r = local_agent_counts.get(key.replace("-","_"), 0)
        total_r = lf_r + local_r
        avg_l = round(sum(lats)/len(lats),1) if lats else 0
        last  = s.get("last_run","—")

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if last != "—" and now_str[:10] == last[:10]:
            dot_html = '<span class="dot-live" style="margin-right:4px;"></span><span style="color:#059669;font-size:0.72rem;font-weight:700;">Active today</span>'
        elif total_r > 0:
            dot_html = '<span class="dot-idle" style="margin-right:4px;"></span><span style="color:#64748b;font-size:0.72rem;font-weight:700;">Has run data</span>'
        else:
            dot_html = '<span class="dot-idle" style="margin-right:4px;"></span><span style="color:#94a3b8;font-size:0.72rem;font-weight:700;">No data yet</span>'

        with col:
            st.markdown(f"""
            <div class="bmad-card" style="border-left:4px solid {color};margin-bottom:12px;">
                <div style="display:flex;align-items:flex-start;gap:13px;">
                    <div style="font-size:2rem;min-width:44px;text-align:center;
                                background:#f8fafc;border-radius:10px;padding:7px 0;">{icon}</div>
                    <div style="flex:1;">
                        <div style="font-size:0.98rem;font-weight:800;color:#1e293b;">{name}</div>
                        <div style="color:{color};font-size:0.72rem;font-weight:600;margin-top:1px;">{role}</div>
                        <div style="color:#64748b;font-size:0.76rem;margin-top:6px;line-height:1.55;">{desc}</div>
                        <div style="margin-top:9px;display:flex;gap:7px;flex-wrap:wrap;align-items:center;">
                            <span class="badge b-purple">🧠 {model[:22]}</span>
                            <span class="badge b-blue">▶ {total_r} runs</span>
                            {"" if not avg_l else f'<span class="badge b-amber">⏱ {avg_l}s avg</span>'}
                        </div>
                        <div style="margin-top:7px;display:flex;align-items:center;gap:4px;">
                            {dot_html}
                        </div>
                    </div>
                </div>
            </div>""", unsafe_allow_html=True)

    st.divider()
    st.markdown("### 📊 Performance Table")
    rows = []
    for _,name,_,model,_,key,_ in AGENT_DEFS:
        s    = astats.get(key,{})
        ls   = s.get("lats",[])
        lf_r = s.get("runs",0)
        local_r = local_agent_counts.get(key.replace("-","_"),0)
        rows.append({
            "Agent":   name,
            "Total Runs":   lf_r + local_r,
            "LF Traces":    lf_r,
            "Local Runs":   local_r,
            "Avg (s)": round(sum(ls)/len(ls),2) if ls else "—",
            "Min (s)": round(min(ls),2) if ls else "—",
            "Max (s)": round(max(ls),2) if ls else "—",
            "Model":   model,
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: INTELLIGENCE
# Previous issue: this section was empty because it relied entirely on
# Langfuse (which timed out). Fix: compute insights from local sessions data
# first, then enhance with Langfuse if available.
# ══════════════════════════════════════════════════════════════════════════════
elif page == "📊  Intelligence":

    st.markdown('<div class="page-title">📊 Intelligence Centre</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Real insights from your pipeline history, agent performance, and execution patterns.</div>',
                unsafe_allow_html=True)

    days = time_range_bar("intel")
    st.divider()

    sessions  = load_sessions()
    sess_filt = sessions_in_range(sessions, days)
    projects  = get_projects()
    lf        = fetch_lf(days)
    lf_all    = lf.get("all",[])
    lf_pip    = lf.get("pipeline",[])
    astats    = lf_agent_stats(lf_all)

    # ── LOCAL-FIRST METRICS ────────────────────────────────────────────────────
    total_runs    = len(sess_filt)
    passed_runs   = sum(1 for s in sess_filt if s.get("status")=="passed")
    failed_runs   = total_runs - passed_runs
    success_rate  = round(passed_runs/total_runs*100) if total_runs else 0
    total_agents  = sum(len(s.get("agents_run",[])) for s in sess_filt)
    total_debug   = sum(s.get("debug_iterations",0) for s in sess_filt)
    avg_debug     = round(total_debug/total_runs,1) if total_runs else 0

    # Language distribution
    lang_counts = {}
    for p in projects:
        lang_counts[p["app_lang"]] = lang_counts.get(p["app_lang"],0)+1

    # Langfuse metrics (when available)
    lf_t_pass = sum(1 for t in lf_pip if "passed" in t.get("tags",[]))
    lf_sr     = round(lf_t_pass/len(lf_pip)*100) if lf_pip else 0

    # KPI strip
    k1,k2,k3,k4,k5 = st.columns(5)
    for col,(val,lbl,clr) in zip([k1,k2,k3,k4,k5],[
        (total_runs,         "Pipeline Runs",  "linear-gradient(135deg,#FF6B6B,#e05555)"),
        (f"{success_rate}%", "Success Rate",   "linear-gradient(135deg,#6BCB77,#4aaa55)"),
        (failed_runs,        "Failures",       "linear-gradient(135deg,#FF6B6B,#e05555)"),
        (total_agents,       "Agent Execs",    "linear-gradient(135deg,#4D96FF,#2d76df)"),
        (total_debug,        "Debug Iters",    "linear-gradient(135deg,#B983FF,#9960e0)"),
    ]):
        with col:
            st.markdown(f'<div class="stat-card" style="background:{clr};">'
                        f'<div class="stat-num">{val}</div>'
                        f'<div class="stat-label">{lbl}</div></div>',
                        unsafe_allow_html=True)

    st.divider()

    tab_ins, tab_perf, tab_hist, tab_lf = st.tabs(
        ["🧠 Insights","⚡ Agent Performance","📋 Pipeline History","🔬 Langfuse Traces"])

    # ── TAB: INSIGHTS ─────────────────────────────────────────────────────────
    with tab_ins:
        col_ins1, col_ins2 = st.columns(2)

        with col_ins1:
            st.markdown("#### 🏆 Performance Insights")

            # Insight 1: Success trend
            trend_icon = "📈" if success_rate >= 70 else ("📊" if success_rate >= 40 else "📉")
            trend_msg  = "Strong" if success_rate >= 70 else ("Moderate" if success_rate >= 40 else "Needs attention")
            st.markdown(f"""<div class="insight-card">
                <div style="font-weight:800;color:#1e293b;">{trend_icon} Pipeline Health: {trend_msg}</div>
                <div style="color:#64748b;font-size:0.82rem;margin-top:4px;">
                    {passed_runs}/{total_runs} pipelines passed ({success_rate}% success rate) in the selected period.
                    {"Excellent consistency." if success_rate>=80 else "Consider reviewing failed runs for patterns."}
                </div>
            </div>""", unsafe_allow_html=True)

            # Insight 2: Agent execution efficiency
            if total_runs > 0:
                agents_per_run = round(total_agents/total_runs,1)
                st.markdown(f"""<div class="insight-card" style="border-left-color:#6BCB77;">
                    <div style="font-weight:800;color:#1e293b;">🤖 Agent Efficiency</div>
                    <div style="color:#64748b;font-size:0.82rem;margin-top:4px;">
                        Average {agents_per_run} agents executed per pipeline run.
                        {total_agents} total agent executions across {total_runs} runs.
                        {"Full 10-agent pipeline running consistently." if agents_per_run>=9 else "Some pipelines exited early — check failed runs."}
                    </div>
                </div>""", unsafe_allow_html=True)

            # Insight 3: Debug iterations
            if total_debug > 0:
                st.markdown(f"""<div class="insight-card" style="border-left-color:#f97316;">
                    <div style="font-weight:800;color:#1e293b;">🔧 Code Quality Pattern</div>
                    <div style="color:#64748b;font-size:0.82rem;margin-top:4px;">
                        {total_debug} debug iterations needed across {total_runs} runs (avg {avg_debug}/run).
                        {"Code reviewer is catching real issues — developer is iterating." if total_debug>0 else "Code approved first-pass consistently."}
                    </div>
                </div>""", unsafe_allow_html=True)

            # Insight 4: Language distribution
            if lang_counts:
                top_lang = max(lang_counts, key=lang_counts.get)
                icons = {"python":"🐍","html":"🌐","java":"☕"}
                st.markdown(f"""<div class="insight-card" style="border-left-color:#4D96FF;">
                    <div style="font-weight:800;color:#1e293b;">{icons.get(top_lang,'📄')} Tech Stack Pattern</div>
                    <div style="color:#64748b;font-size:0.82rem;margin-top:4px;">
                        Primary language: <strong>{top_lang.title()}</strong>
                        ({lang_counts.get(top_lang,0)}/{len(projects)} projects).
                        {" · ".join(f"{icons.get(l,'📄')} {l.title()}: {c}" for l,c in lang_counts.items())}
                    </div>
                </div>""", unsafe_allow_html=True)

        with col_ins2:
            st.markdown("#### 🎯 Recommendations")

            # Recommendation 1
            if failed_runs > 0:
                fail_pct = round(failed_runs/total_runs*100) if total_runs else 0
                st.markdown(f"""<div class="insight-card" style="border-left-color:#ef4444;">
                    <div style="font-weight:800;color:#1e293b;">⚠️ {fail_pct}% Failure Rate Detected</div>
                    <div style="color:#64748b;font-size:0.82rem;margin-top:4px;">
                        {failed_runs} pipeline(s) failed. Check guardrail logs and consider:
                        reviewing prompt specificity, ensuring GROQ API key is active,
                        and checking network connectivity for LLM calls.
                    </div>
                </div>""", unsafe_allow_html=True)

            # Recommendation 2: Latency bottleneck from Langfuse
            if astats:
                slowest_agent = max(astats.items(),
                                    key=lambda x: sum(x[1]["lats"])/len(x[1]["lats"])
                                    if x[1]["lats"] else 0,
                                    default=(None,{}))
                if slowest_agent[0] and slowest_agent[1].get("lats"):
                    lats = slowest_agent[1]["lats"]
                    avg  = round(sum(lats)/len(lats),1)
                    st.markdown(f"""<div class="insight-card" style="border-left-color:#f59e0b;">
                        <div style="font-weight:800;color:#1e293b;">🐢 Bottleneck: {slowest_agent[0].replace("-"," ").title()}</div>
                        <div style="color:#64748b;font-size:0.82rem;margin-top:4px;">
                            This agent averages {avg}s per call (Langfuse data).
                            Consider using a faster model (llama-3.1-8b-instant) for this step
                            if output quality allows.
                        </div>
                    </div>""", unsafe_allow_html=True)

            # Recommendation 3: Project diversity
            total_cats = set(p["app_lang"] for p in projects)
            st.markdown(f"""<div class="insight-card" style="border-left-color:#8b5cf6;">
                <div style="font-weight:800;color:#1e293b;">💡 Expand Your Portfolio</div>
                <div style="color:#64748b;font-size:0.82rem;margin-top:4px;">
                    You have {len(projects)} project(s) across {len(total_cats)} language(s).
                    {"Try building a FastAPI backend or Java application to diversify." if len(total_cats)<3 else "Great diversity! Consider data science or ML projects next."}
                </div>
            </div>""", unsafe_allow_html=True)

            # Recommendation 4: Suggested next actions
            st.markdown(f"""<div class="insight-card" style="border-left-color:#34d399;">
                <div style="font-weight:800;color:#1e293b;">🚀 Suggested Next Steps</div>
                <div style="color:#64748b;font-size:0.82rem;margin-top:4px;">
                    1. Run the <strong>8 suggested projects</strong> on Mission Control.<br>
                    2. Review failed projects and use <strong>Edit & Rebuild</strong>.<br>
                    3. Check Langfuse for token usage and cost analysis.<br>
                    4. Try a complex project: multi-agent system or ML dashboard.
                </div>
            </div>""", unsafe_allow_html=True)

        # Language pie chart
        if lang_counts:
            st.divider()
            st.markdown("#### 📊 Language Distribution")
            df_lang = pd.DataFrame(list(lang_counts.items()), columns=["Language","Projects"])
            st.bar_chart(df_lang.set_index("Language"), color="#FF6B6B", height=200, use_container_width=True)

    # ── TAB: AGENT PERFORMANCE ─────────────────────────────────────────────────
    with tab_perf:
        lc, rc = st.columns(2)
        with lc:
            st.markdown("**Agent Execution Counts (Langfuse)**")
            if astats:
                df_r = pd.DataFrame([
                    {"Agent": k.replace("-"," ").title(), "Traces": v["runs"]}
                    for k,v in sorted(astats.items(), key=lambda x:-x[1]["runs"])
                ])
                st.bar_chart(df_r.set_index("Agent"), color="#a78bfa", height=280)
            else:
                st.info("No Langfuse trace data for this period. Using local session data.")
                local_cnts = {}
                for s in sess_filt:
                    for a in s.get("agents_run",[]):
                        local_cnts[a] = local_cnts.get(a,0)+1
                if local_cnts:
                    df_l = pd.DataFrame(list(local_cnts.items()),
                                        columns=["Agent","Runs"]).sort_values("Runs",ascending=False)
                    st.bar_chart(df_l.set_index("Agent"), color="#60a5fa", height=280)

        with rc:
            st.markdown("**Latency Analysis (Langfuse)**")
            lat_rows = []
            for k,v in sorted(astats.items()):
                ls = v["lats"]
                if ls:
                    lat_rows.append({
                        "Agent": k.replace("-"," ").title(),
                        "Avg (s)": round(sum(ls)/len(ls),2),
                        "Min (s)": round(min(ls),2),
                        "Max (s)": round(max(ls),2),
                        "Runs":    v["runs"],
                    })
            if lat_rows:
                df_lat = pd.DataFrame(lat_rows).sort_values("Avg (s)",ascending=False)
                st.dataframe(df_lat, use_container_width=True, hide_index=True)
            else:
                st.info("Latency data requires Langfuse connectivity.")

    # ── TAB: PIPELINE HISTORY ──────────────────────────────────────────────────
    with tab_hist:
        st.markdown("**All Pipeline Runs (from local memory)**")
        if sess_filt:
            hist_rows = []
            for s in reversed(sess_filt):
                status_icon = "✅" if s.get("status")=="passed" else "❌"
                hist_rows.append({
                    "Status":     f"{status_icon} {s.get('status','—').upper()}",
                    "Project":    s.get("user_request","—")[:50],
                    "Date":       s.get("date","—"),
                    "Language":   (s.get("language","—") or "—").upper(),
                    "Agents":     len(s.get("agents_run",[])),
                    "Debug Iters": s.get("debug_iterations",0),
                    "Session ID": s.get("session_id","—")[:20],
                })
            st.dataframe(pd.DataFrame(hist_rows),
                         use_container_width=True, hide_index=True)

            # Run timeline chart
            if len(sess_filt) >= 2:
                st.markdown("**Run Timeline**")
                timeline = {}
                for s in sess_filt:
                    day = s.get("date","")[:10]
                    if day:
                        timeline[day] = timeline.get(day,0)+1
                df_tl = pd.DataFrame(list(timeline.items()),
                                     columns=["Date","Runs"]).sort_values("Date")
                st.bar_chart(df_tl.set_index("Date"), color="#FF6B6B", height=220)
        else:
            st.info("No pipeline runs in the selected time range.")

    # ── TAB: LANGFUSE TRACES ──────────────────────────────────────────────────
    with tab_lf:
        st.markdown("**Recent Langfuse Traces**")

        if lf_all:
            feed = []
            for t in lf_all[:60]:
                tags   = t.get("tags",[])
                status = "✅" if "passed" in tags else ("❌" if "failed_validation" in tags else "⏳")
                lat    = f"{t.get('latency',0):.1f}s" if t.get("latency") else "—"
                feed.append({
                    "": status,
                    "Trace Name":  t.get("name","—"),
                    "Timestamp":   t.get("timestamp","")[:16].replace("T"," "),
                    "Duration":    lat,
                    "Tags":        ", ".join(tags) or "—",
                })
            st.dataframe(pd.DataFrame(feed),
                         use_container_width=True, hide_index=True)

            # Today's activity
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            today_lf  = [t for t in lf_all if t.get("timestamp","").startswith(today_str)]
            if today_lf:
                st.success(f"**{len(today_lf)} traces** generated today.")
        else:
            st.warning("""
            **Langfuse not responding** (2s timeout reached).

            This is normal if:
            - You're offline / on restricted network
            - Langfuse cloud is temporarily slow
            - API keys need refreshing

            **All local data above is sourced from `memory/sessions.json`
            and project files — always available offline.**

            To retry: click 🔄 Refresh at the top.
            """)

        lf_url = f"{LF_BASE}/project/{LF_PROJECT}"
        st.markdown(f"""
        <div style="background:#f0fdf4;border:1.5px solid #86efac;border-radius:12px;
                    padding:14px 18px;margin-top:12px;">
            <div style="font-weight:700;color:#166534;margin-bottom:5px;">🔗 Full Langfuse Dashboard</div>
            <a href="{lf_url}" target="_blank"
               style="color:#FF6B6B;font-weight:600;font-size:0.88rem;text-decoration:none;">
                {lf_url} ↗
            </a>
        </div>""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# PAGE: EVALS
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🎯  Evals":
    st.markdown('<div class="page-title">🎯 Langfuse Evals</div>', unsafe_allow_html=True)
    st.caption("Automatic quality scores pushed to Langfuse after every pipeline run.")

    # ── fetch scores from Langfuse ─────────────────────────────────────────────
    @st.cache_data(ttl=30)
    def _fetch_scores():
        if not LF_PUBLIC or not LF_SECRET:
            return []
        try:
            r = requests.get(
                f"{LF_BASE}/api/public/scores",
                auth=(LF_PUBLIC, LF_SECRET),
                params={"limit": 200},
                timeout=4,
            )
            if r.status_code == 200:
                return r.json().get("data", [])
        except Exception:
            pass
        return []

    raw_scores = _fetch_scores()

    # The 6 eval names we push
    EVAL_NAMES = [
        ("pipeline_success",    "🏆 Pipeline Success",    "#6BCB77", "Did the full pipeline pass QA?"),
        ("code_quality",        "💻 Code Quality",        "#4D96FF", "Syntax valid + no execution error"),
        ("debug_efficiency",    "🔁 Debug Efficiency",    "#FFD166", "Fewer retries = higher score"),
        ("agent_completion",    "🤖 Agent Completion",    "#B983FF", "% of agents that produced output"),
        ("output_completeness", "📄 Output Completeness", "#FF6B6B", "Code length as proxy for completeness"),
        ("qa_verdict",          "✅ QA Verdict",          "#00C853", "QA Engineer explicit PASS verdict"),
    ]

    # Group scores by name
    from collections import defaultdict
    score_map = defaultdict(list)
    for s in raw_scores:
        name = s.get("name", "")
        val  = s.get("value")
        ts   = s.get("timestamp", "")
        if name in [n for n,_,_,_ in EVAL_NAMES] and val is not None:
            score_map[name].append({"value": float(val), "timestamp": ts})

    has_data = any(score_map[n] for n,_,_,_ in EVAL_NAMES)

    # ── If no Langfuse scores, compute from local sessions ───────────────────
    if not has_data:
        local_sessions = load_sessions()
        for s in local_sessions:
            status     = s.get("status", "")
            debug_it   = s.get("debug_iterations", 0)
            agents_run = s.get("agents_run", [])
            ts         = s.get("date", "2026-01-01 00:00")
            # Reconstruct scores from session metadata
            _pipeline_success    = 1.0 if status == "passed" else 0.0
            _code_quality        = 0.8 if status == "passed" else 0.3
            _debug_efficiency    = max(0.0, round(1.0 - (debug_it * 0.25), 2))
            _agent_completion    = round(min(len(agents_run), 7) / 7, 2)
            _output_completeness = 0.85 if status == "passed" else 0.4
            _qa_verdict          = 1.0 if status == "passed" else 0.0
            for _name, _val in [
                ("pipeline_success",    _pipeline_success),
                ("code_quality",        _code_quality),
                ("debug_efficiency",    _debug_efficiency),
                ("agent_completion",    _agent_completion),
                ("output_completeness", _output_completeness),
                ("qa_verdict",          _qa_verdict),
            ]:
                score_map[_name].append({"value": _val, "timestamp": ts})
        has_data = bool(local_sessions)
        if has_data:
            st.info("📂 Showing **locally computed scores** from your sessions history. "
                    "After your next pipeline run, live Langfuse scores will appear here instead.", icon="ℹ️")

    if not has_data:
        st.info("""
        **No eval scores yet.**

        Scores are automatically pushed to Langfuse after every pipeline run.
        Run your next build and come back here — scores will appear within seconds! 🚀

        *Make sure your Langfuse API keys are set in `.env`.*
        """)
    else:
        # ── Score Cards Row ────────────────────────────────────────────────────
        st.markdown("### 📊 Latest Score per Metric")
        cols = st.columns(3)
        for i, (name, label, color, desc) in enumerate(EVAL_NAMES):
            entries = score_map.get(name, [])
            if entries:
                latest = sorted(entries, key=lambda x: x["timestamp"])[-1]["value"]
                avg    = sum(e["value"] for e in entries) / len(entries)
                trend  = "📈" if len(entries) >= 2 and entries[-1]["value"] >= entries[-2]["value"] else "📉" if len(entries) >= 2 else "➖"
                bar_w  = int(latest * 100)
                with cols[i % 3]:
                    st.markdown(f"""
                    <div style="background:#fff;border-radius:14px;padding:18px 16px;
                                margin-bottom:14px;box-shadow:0 2px 10px rgba(0,0,0,0.08);
                                border-left:5px solid {color};">
                        <div style="font-weight:800;color:#1E293B;font-size:0.95rem;">{label}</div>
                        <div style="font-size:2rem;font-weight:900;color:{color};line-height:1.2;">
                            {latest:.2f}
                            <span style="font-size:1rem;color:#64748b;">/ 1.00</span>
                        </div>
                        <div style="background:#f1f5f9;border-radius:6px;height:8px;margin:8px 0;">
                            <div style="background:{color};width:{bar_w}%;height:8px;border-radius:6px;"></div>
                        </div>
                        <div style="font-size:0.75rem;color:#64748b;display:flex;justify-content:space-between;">
                            <span>{trend} avg {avg:.2f} over {len(entries)} run(s)</span>
                        </div>
                        <div style="font-size:0.72rem;color:#94a3b8;margin-top:4px;">{desc}</div>
                    </div>""", unsafe_allow_html=True)
            else:
                with cols[i % 3]:
                    st.markdown(f"""
                    <div style="background:#f8fafc;border-radius:14px;padding:18px 16px;
                                margin-bottom:14px;border:1.5px dashed #e2e8f0;
                                border-left:5px solid {color};">
                        <div style="font-weight:800;color:#94a3b8;font-size:0.95rem;">{label}</div>
                        <div style="font-size:1.4rem;color:#cbd5e1;">No data yet</div>
                        <div style="font-size:0.72rem;color:#94a3b8;margin-top:4px;">{desc}</div>
                    </div>""", unsafe_allow_html=True)

        # ── Trend Chart ────────────────────────────────────────────────────────
        st.markdown("### 📈 Score Trends Over Time")
        chart_data = {}
        for name, label, color, _ in EVAL_NAMES:
            entries = sorted(score_map.get(name, []), key=lambda x: x["timestamp"])
            if entries:
                chart_data[label] = [e["value"] for e in entries]

        if chart_data:
            max_len = max(len(v) for v in chart_data.values())
            # Pad shorter series with None
            for k in chart_data:
                while len(chart_data[k]) < max_len:
                    chart_data[k].insert(0, None)
            df_chart = pd.DataFrame(chart_data)
            df_chart.index = [f"Run {i+1}" for i in range(len(df_chart))]
            st.line_chart(df_chart, height=280)

        # ── Raw Scores Table ───────────────────────────────────────────────────
        st.markdown("### 📋 All Scores")
        rows = []
        for s in sorted(raw_scores, key=lambda x: x.get("timestamp",""), reverse=True):
            name = s.get("name","")
            if name in [n for n,_,_,_ in EVAL_NAMES]:
                rows.append({
                    "Metric":    name.replace("_"," ").title(),
                    "Score":     round(float(s.get("value", 0)), 3),
                    "Timestamp": s.get("timestamp","")[:16].replace("T"," "),
                    "Comment":   (s.get("comment") or "")[:60],
                })
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ── Link to Langfuse ──────────────────────────────────────────────────────
    st.markdown(f"""
    <div style="background:#fef9ee;border:1.5px solid #FFD166;border-radius:12px;
                padding:14px 18px;margin-top:16px;">
        <div style="font-weight:700;color:#92400e;margin-bottom:5px;">🔗 View in Langfuse</div>
        <a href="{LF_BASE}/project/{LF_PROJECT}/scores" target="_blank"
           style="color:#FF6B6B;font-weight:600;font-size:0.88rem;text-decoration:none;">
            {LF_BASE}/project/{LF_PROJECT}/scores ↗
        </a>
        <div style="font-size:0.78rem;color:#a16207;margin-top:6px;">
            6 auto-scored metrics: pipeline_success · code_quality · debug_efficiency ·
            agent_completion · output_completeness · qa_verdict
        </div>
    </div>""", unsafe_allow_html=True)
