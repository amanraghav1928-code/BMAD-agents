"""
LiteLLM Proxy Test Suite
========================
Tests BMAD agents + MCP through the LiteLLM proxy.

Run:
  1. Start proxy first:  ./start_litellm.sh
  2. Run tests:          python tests/test_litellm.py
"""

import os, sys, requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

PROXY_URL = os.getenv("LITELLM_PROXY_URL", "http://localhost:4000")
PROXY_KEY = os.getenv("LITELLM_MASTER_KEY", "bmad-litellm-key-2025")
HEADERS   = {
    "Authorization": f"Bearer {PROXY_KEY}",
    "Content-Type":  "application/json",
}

PASS = "✅"
FAIL = "❌"
results = []

def test(name, fn):
    try:
        fn()
        print(f"  {PASS}  {name}")
        results.append((name, True))
    except Exception as e:
        print(f"  {FAIL}  {name} — {e}")
        results.append((name, False))

def chat(model, content, max_tokens=30):
    r = requests.post(f"{PROXY_URL}/v1/chat/completions", headers=HEADERS,
        json={"model": model,
              "messages": [{"role": "user", "content": content}],
              "max_tokens": max_tokens}, timeout=40)
    assert r.status_code == 200, f"HTTP {r.status_code} — {r.text[:300]}"
    return r.json()

# ── 1. Health check ────────────────────────────────────────────────────────────
def test_health():
    r = requests.get(f"{PROXY_URL}/health", headers=HEADERS, timeout=5)
    assert r.status_code == 200, f"Status {r.status_code}"

# ── 2. List models ─────────────────────────────────────────────────────────────
def test_list_models():
    r = requests.get(f"{PROXY_URL}/v1/models", headers=HEADERS, timeout=5)
    assert r.status_code == 200, f"Status {r.status_code}"
    models = [m["id"] for m in r.json().get("data", [])]
    assert len(models) > 0, "No models returned"
    print(f"\n     Models registered: {models}")

# ── 3. bmad-primary (Groq llama-3.3-70b) ──────────────────────────────────────
def test_bmad_primary():
    d = chat("bmad-primary", "Say exactly: 'BMAD primary works!'")
    answer = d["choices"][0]["message"]["content"]
    print(f"\n     bmad-primary → {answer.strip()[:80]}")

# ── 4. bmad-fast (Groq llama-3.1-8b) ─────────────────────────────────────────
def test_bmad_fast():
    d = chat("bmad-fast", "What is 5 + 5? Reply with only the number.")
    answer = d["choices"][0]["message"]["content"]
    print(f"\n     bmad-fast → {answer.strip()[:80]}")

# ── 5. bmad-cerebras (Cerebras qwen-3) ────────────────────────────────────────
def test_bmad_cerebras():
    d = chat("bmad-cerebras", "What is the capital of France? One word only.")
    answer = d["choices"][0]["message"]["content"]
    print(f"\n     bmad-cerebras → {answer.strip()[:80]}")

# ── 6. llama-3.3-70b-versatile alias ──────────────────────────────────────────
def test_groq_alias():
    d = chat("llama-3.3-70b-versatile", "Say exactly: 'Groq alias works!'")
    answer = d["choices"][0]["message"]["content"]
    print(f"\n     llama-3.3-70b alias → {answer.strip()[:80]}")

# ── 7. Token usage returned ────────────────────────────────────────────────────
def test_token_usage():
    d = chat("bmad-primary", "Hello!")
    usage = d.get("usage", {})
    assert usage.get("prompt_tokens", 0) > 0, f"No token usage: {usage}"
    print(f"\n     Tokens — prompt:{usage['prompt_tokens']} completion:{usage['completion_tokens']}")

# ── 8. BMAD agent routed via LiteLLM ──────────────────────────────────────────
def test_bmad_agent():
    os.environ["USE_LITELLM"] = "true"
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from core.agent_runner import run_agent
    result = run_agent(
        agent_id="analyst",
        user_message="In one sentence, what does a Business Analyst do?",
        session_id="litellm-test"
    )
    assert result and len(result) > 10, "Empty response"
    print(f"\n     Agent (via LiteLLM) → {result[:100]}...")

# ── 9. MCP server exists & is valid ───────────────────────────────────────────
def test_mcp():
    """
    The MCP server uses stdio transport (not HTTP) — it has no /health endpoint.
    We verify it exists and has the correct tools instead.
    """
    mcp_path = Path(__file__).parent.parent / "mcp-server" / "server.py"
    assert mcp_path.exists(), f"MCP server file missing: {mcp_path}"

    content = mcp_path.read_text()
    expected_tools = ["ask_pipeline", "get_agent_performance", "get_model_usage",
                      "get_recent_activity", "compare_agents", "get_pipeline_health",
                      "search_sessions"]
    missing = [t for t in expected_tools if t not in content]
    assert not missing, f"MCP server missing tools: {missing}"

    print(f"\n     MCP server ✓  ({len(expected_tools)} tools registered, stdio transport)")

# ── Run ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "═"*58)
    print("  🧪  BMAD × LiteLLM Proxy — Test Suite")
    print("═"*58)

    try:
        requests.get(f"{PROXY_URL}/health", headers=HEADERS, timeout=3)
    except Exception:
        print(f"\n  ❌  LiteLLM proxy not running at {PROXY_URL}")
        print("  👉  Start it first:  ./start_litellm.sh\n")
        sys.exit(1)

    print(f"\n  Proxy : {PROXY_URL}")
    print(f"  Key   : {PROXY_KEY}\n")

    test("1. Health check",                test_health)
    test("2. List models",                 test_list_models)
    test("3. bmad-primary (Groq 70b)",     test_bmad_primary)
    test("4. bmad-fast    (Groq 8b)",      test_bmad_fast)
    test("5. bmad-cerebras (Cerebras)",    test_bmad_cerebras)
    test("6. llama-3.3-70b alias",         test_groq_alias)
    test("7. Token usage tracking",        test_token_usage)
    test("8. BMAD agent via LiteLLM",      test_bmad_agent)
    test("9. MCP server health",           test_mcp)

    passed = sum(1 for _, ok in results if ok)
    total  = len(results)
    print("\n" + "═"*58)
    print(f"  Results : {passed}/{total} passed")
    if passed == total:
        print("  🎉  All tests passed!")
    else:
        print("  ⚠️   Some failed — check output above.")
    print("═"*58 + "\n")
