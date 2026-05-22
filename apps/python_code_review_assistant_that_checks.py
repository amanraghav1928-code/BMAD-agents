import streamlit as st
import subprocess
import sys
import os
import tempfile
import ast
import re
import io
import time

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Python Code Review Assistant",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&family=JetBrains+Mono:wght@400;600&display=swap');

    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .stApp { background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 50%, #16213e 100%); }

    [data-testid="metric-container"] {
        background: rgba(255,255,255,0.05);
        border: 1px solid rgba(255,255,255,0.1);
        border-radius: 16px;
        padding: 20px;
        backdrop-filter: blur(10px);
    }
    [data-testid="stSidebar"] {
        background: rgba(255,255,255,0.03);
        border-right: 1px solid rgba(255,255,255,0.08);
    }
    .stButton > button {
        background: linear-gradient(135deg, #6C63FF, #F50057);
        color: white; border: none; border-radius: 12px;
        padding: 12px 24px; font-weight: 600;
        transition: all 0.3s ease; width: 100%;
    }
    .stButton > button:hover { transform: translateY(-2px); box-shadow: 0 8px 25px rgba(108,99,255,0.4); }
    h1 { background: linear-gradient(135deg, #6C63FF, #F50057);
         -webkit-background-clip: text; -webkit-text-fill-color: transparent;
         font-size: 2.5rem !important; font-weight: 700 !important; }
    h2, h3 { color: #E0E0E0 !important; }
    p, li, label { color: #B0B0C0 !important; }
    hr { border-color: rgba(255,255,255,0.1) !important; }
    .stTextArea textarea {
        background: rgba(255,255,255,0.05) !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        border-radius: 10px !important;
        color: #e2e8f0 !important;
        font-family: 'JetBrains Mono', monospace !important;
        font-size: 13px !important;
    }
    .stSelectbox > div {
        background: rgba(255,255,255,0.05) !important;
        border-radius: 10px !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
    }
    .issue-error {
        background: rgba(255,82,82,0.1); border-left: 3px solid #FF5252;
        border-radius: 8px; padding: 10px 14px; margin: 6px 0;
        font-family: 'JetBrains Mono', monospace; font-size: 13px; color: #ffcdd2;
    }
    .issue-warning {
        background: rgba(255,215,64,0.08); border-left: 3px solid #FFD740;
        border-radius: 8px; padding: 10px 14px; margin: 6px 0;
        font-family: 'JetBrains Mono', monospace; font-size: 13px; color: #fff9c4;
    }
    .issue-info {
        background: rgba(100,181,246,0.08); border-left: 3px solid #64B5F6;
        border-radius: 8px; padding: 10px 14px; margin: 6px 0;
        font-family: 'JetBrains Mono', monospace; font-size: 13px; color: #bbdefb;
    }
    .score-badge {
        display: inline-block; padding: 6px 16px; border-radius: 20px;
        font-weight: 700; font-size: 1.1rem; margin: 4px 0;
    }
    .stSuccess { background: rgba(0,230,118,0.1); border: 1px solid #00E676; border-radius: 10px; }
    .stError   { background: rgba(255,82,82,0.1);  border: 1px solid #FF5252; border-radius: 10px; }
    .stWarning { background: rgba(255,215,64,0.1); border: 1px solid #FFD740; border-radius: 10px; }
    .stInfo    { background: rgba(100,181,246,0.1);border: 1px solid #64B5F6; border-radius: 10px; }
</style>
""", unsafe_allow_html=True)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _install_if_missing(pkg: str) -> bool:
    try:
        __import__(pkg)
        return True
    except ImportError:
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", pkg, "-q"],
                           check=True, capture_output=True)
            return True
        except Exception:
            return False


def run_pylint(code: str) -> tuple[list[dict], float]:
    """Run pylint and return (issues, score)."""
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as f:
        f.write(code)
        tmp = f.name
    issues = []
    score = 0.0
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pylint", tmp,
             "--output-format=text", "--score=yes",
             "--disable=C0114,C0115,C0116",   # skip missing docstring noise
             "--max-line-length=100"],
            capture_output=True, text=True, timeout=30
        )
        raw = result.stdout + result.stderr
        # Parse score
        m = re.search(r"Your code has been rated at\s+([\-\d.]+)/10", raw)
        if m:
            score = float(m.group(1))
        # Parse issues
        for line in raw.splitlines():
            m = re.match(r".+:(\d+):\d+:\s+([CWEF]\d+):\s+(.+)", line)
            if m:
                lineno, code_id, msg = m.groups()
                sev = {"C": "info", "W": "warning", "E": "error", "F": "error"}.get(code_id[0], "info")
                issues.append({"line": lineno, "code": code_id, "msg": msg.strip(), "severity": sev})
    except Exception as e:
        issues.append({"line": "?", "code": "ERR", "msg": str(e), "severity": "error"})
    finally:
        os.unlink(tmp)
    return issues, score


def run_pyflakes(code: str) -> list[dict]:
    """Run pyflakes and return issues."""
    try:
        import pyflakes.api as pf
        import pyflakes.checker as pfc
        tree = compile(code, "<string>", "exec", ast.PyCF_ONLY_AST)
        w = pfc.Checker(tree, "<string>")
        issues = []
        for msg in w.messages:
            issues.append({
                "line": str(msg.lineno),
                "code": msg.__class__.__name__,
                "msg": str(msg.message % msg.message_args),
                "severity": "warning",
            })
        return issues
    except SyntaxError as e:
        return [{"line": str(e.lineno), "code": "SyntaxError", "msg": str(e.msg), "severity": "error"}]
    except Exception as e:
        return [{"line": "?", "code": "ERR", "msg": str(e), "severity": "error"}]


def check_syntax(code: str) -> tuple[bool, str]:
    """Check Python syntax using ast.parse."""
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        return False, f"Line {e.lineno}: {e.msg}"


def analyze_complexity(code: str) -> list[dict]:
    """Detect long functions, deep nesting, and magic numbers."""
    issues = []
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end = getattr(node, "end_lineno", node.lineno)
                length = end - node.lineno
                if length > 50:
                    issues.append({
                        "line": str(node.lineno), "code": "C001",
                        "msg": f"Function '{node.name}' is {length} lines long (recommend ≤ 50)",
                        "severity": "warning",
                    })
    except Exception:
        pass
    # Magic numbers
    for i, line in enumerate(code.splitlines(), 1):
        nums = re.findall(r"\b(?<![\.\w])((?:[2-9]|[1-9]\d+))\b", line)
        if nums and not line.strip().startswith("#"):
            issues.append({
                "line": str(i), "code": "C002",
                "msg": f"Magic number(s) detected: {', '.join(set(nums))} — consider named constants",
                "severity": "info",
            })
    return issues


def check_security(code: str) -> list[dict]:
    """Basic security pattern checks."""
    patterns = [
        (r"\beval\s*\(", "S001", "Use of eval() is dangerous — avoid or sanitise input"),
        (r"\bexec\s*\(", "S002", "Use of exec() is dangerous"),
        (r"os\.system\s*\(", "S003", "Prefer subprocess over os.system()"),
        (r"pickle\.loads?\s*\(", "S004", "pickle.load on untrusted data is unsafe"),
        (r"password\s*=\s*['\"][^'\"]+['\"]", "S005", "Hardcoded password detected"),
        (r"secret\s*=\s*['\"][^'\"]+['\"]", "S006", "Hardcoded secret detected"),
        (r"sha1\b|md5\b", "S007", "Weak hash algorithm (SHA-1 / MD5) — use SHA-256+"),
        (r"\bopen\s*\(.+\bw\b", "S008", "File opened for writing — ensure path is validated"),
        (r"random\.(random|randint|choice)\b", "S009", "Use secrets module for cryptographic randomness"),
        (r"subprocess\.call\(.+shell\s*=\s*True", "S010", "shell=True in subprocess is a command injection risk"),
    ]
    issues = []
    lines = code.splitlines()
    for i, line in enumerate(lines, 1):
        if line.strip().startswith("#"):
            continue
        for pattern, code_id, msg in patterns:
            if re.search(pattern, line, re.IGNORECASE):
                issues.append({"line": str(i), "code": code_id, "msg": msg, "severity": "error"})
    return issues


def score_color(score: float) -> str:
    if score >= 8:
        return "#00E676"
    if score >= 5:
        return "#FFD740"
    return "#FF5252"


def render_issues(issues: list[dict]) -> None:
    if not issues:
        st.success("✅ No issues found!")
        return
    for iss in issues:
        cls = f"issue-{iss['severity']}"
        icon = {"error": "🔴", "warning": "🟡", "info": "🔵"}.get(iss["severity"], "⚪")
        st.markdown(
            f'<div class="{cls}">'
            f'{icon} <b>Line {iss["line"]}</b> &nbsp;[{iss["code"]}]&nbsp; {iss["msg"]}'
            f'</div>',
            unsafe_allow_html=True,
        )


# ── Install optional deps silently ────────────────────────────────────────────
_install_if_missing("pylint")
_install_if_missing("pyflakes")

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Settings")
    st.divider()
    checks = st.multiselect(
        "Enable checks",
        ["Syntax", "Pylint", "Pyflakes", "Complexity", "Security"],
        default=["Syntax", "Pylint", "Pyflakes", "Security"],
    )
    st.divider()
    st.markdown("### 📋 Quick Paste")
    sample = st.selectbox("Load sample snippet", [
        "None",
        "eval() misuse",
        "Long function",
        "Hardcoded password",
        "Magic numbers",
    ])

SAMPLES = {
    "eval() misuse": '''\
def process(user_input):
    result = eval(user_input)
    return result
''',
    "Long function": "\n".join(
        [f"def big_function():"] + [f"    x_{i} = {i} * 2" for i in range(60)]
    ),
    "Hardcoded password": '''\
password = "super_secret_123"
db_host = "localhost"
db_user = "admin"
conn = connect(db_host, db_user, password)
''',
    "Magic numbers": '''\
def calc_total(price):
    tax = price * 0.18
    discount = price * 25
    return tax + discount - 500
''',
}

# ── Main ──────────────────────────────────────────────────────────────────────
st.title("🔍 Python Code Review Assistant")
st.markdown('<p style="color:#B0B0C0;font-size:1.05rem;">Paste your Python code below and get instant feedback on syntax, quality, complexity, and security.</p>', unsafe_allow_html=True)
st.divider()

default_code = SAMPLES.get(sample, "") if sample != "None" else (
    st.session_state.get("last_code", "")
)

code_input = st.text_area(
    "📝 Your Python code",
    value=default_code,
    height=320,
    placeholder="# Paste your Python code here...",
    label_visibility="visible",
)

col_btn, col_clear = st.columns([3, 1])
with col_btn:
    run_clicked = st.button("🚀 Run Code Review", use_container_width=True)
with col_clear:
    if st.button("🗑 Clear", use_container_width=True):
        st.session_state["last_code"] = ""
        st.rerun()

if run_clicked and code_input.strip():
    st.session_state["last_code"] = code_input
    st.divider()

    # ── Counters ────────────────────────────────────────────────────────────
    total_errors   = 0
    total_warnings = 0
    total_infos    = 0
    pylint_score   = None

    with st.spinner("Analysing your code…"):
        time.sleep(0.3)  # let spinner render

        # ── Collect all results ──────────────────────────────────────────────
        syntax_ok, syntax_err = check_syntax(code_input) if "Syntax" in checks else (True, "")
        pylint_issues, pylint_score = run_pylint(code_input) if "Pylint" in checks else ([], 0.0)
        pyflakes_issues = run_pyflakes(code_input) if "Pyflakes" in checks else []
        complexity_issues = analyze_complexity(code_input) if "Complexity" in checks else []
        security_issues = check_security(code_input) if "Security" in checks else []

        all_issues = pylint_issues + pyflakes_issues + complexity_issues + security_issues
        for iss in all_issues:
            if iss["severity"] == "error":   total_errors   += 1
            elif iss["severity"] == "warning": total_warnings += 1
            else:                              total_infos    += 1

    # ── KPI row ─────────────────────────────────────────────────────────────
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("🔴 Errors",   total_errors,   delta=None)
    k2.metric("🟡 Warnings", total_warnings, delta=None)
    k3.metric("🔵 Info",     total_infos,    delta=None)
    if pylint_score is not None and "Pylint" in checks:
        color = score_color(pylint_score)
        k4.markdown(
            f'<div style="background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);'
            f'border-radius:16px;padding:20px;text-align:center;">'
            f'<div style="color:#B0B0C0;font-size:0.85rem;margin-bottom:4px;">Pylint Score</div>'
            f'<div style="color:{color};font-size:2rem;font-weight:700;">{pylint_score:.1f}<span style="font-size:1rem;color:#B0B0C0;">/10</span></div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.divider()

    # ── Syntax ──────────────────────────────────────────────────────────────
    if "Syntax" in checks:
        with st.expander("🧩 Syntax Check", expanded=not syntax_ok):
            if syntax_ok:
                st.success("✅ Syntax is valid Python.")
            else:
                st.error(f"❌ Syntax Error — {syntax_err}")

    # ── Tabs for each tool ────────────────────────────────────────────────────
    tab_labels = []
    if "Pylint"     in checks: tab_labels.append(f"Pylint ({len(pylint_issues)})")
    if "Pyflakes"   in checks: tab_labels.append(f"Pyflakes ({len(pyflakes_issues)})")
    if "Complexity" in checks: tab_labels.append(f"Complexity ({len(complexity_issues)})")
    if "Security"   in checks: tab_labels.append(f"🔒 Security ({len(security_issues)})")

    if tab_labels:
        tabs = st.tabs(tab_labels)
        tab_idx = 0

        if "Pylint" in checks:
            with tabs[tab_idx]:
                st.caption(f"Pylint score: **{pylint_score:.1f}/10** — issues below")
                render_issues(pylint_issues)
            tab_idx += 1

        if "Pyflakes" in checks:
            with tabs[tab_idx]:
                st.caption("Pyflakes detects unused imports, undefined names, and more")
                render_issues(pyflakes_issues)
            tab_idx += 1

        if "Complexity" in checks:
            with tabs[tab_idx]:
                st.caption("Long functions and magic numbers hurt maintainability")
                render_issues(complexity_issues)
            tab_idx += 1

        if "Security" in checks:
            with tabs[tab_idx]:
                st.caption("Common security anti-patterns in your code")
                render_issues(security_issues)
            tab_idx += 1

    # ── Summary ──────────────────────────────────────────────────────────────
    st.divider()
    if total_errors == 0 and total_warnings == 0:
        st.success("🎉 Great job! No critical issues found.")
    elif total_errors == 0:
        st.warning(f"⚠️ {total_warnings} warning(s) found — worth reviewing before shipping.")
    else:
        st.error(f"🚨 {total_errors} error(s) found — fix these before running in production.")

elif run_clicked:
    st.warning("⚠️ Please paste some Python code first.")
else:
    # Landing state
    st.markdown("""
    <div style="text-align:center;padding:60px 20px;color:#B0B0C0;">
        <div style="font-size:4rem;">🔍</div>
        <h3 style="color:#E0E0E0!important;margin-top:16px;">Ready to review your code</h3>
        <p>Paste any Python code above and click <b>Run Code Review</b>.</p>
        <p>Checks include: syntax validation · pylint quality · pyflakes lint · complexity · security patterns.</p>
    </div>
    """, unsafe_allow_html=True)
