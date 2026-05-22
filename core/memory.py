"""
Project Memory
--------------
Saves a rich summary of every pipeline run to memory/sessions.json.
On new runs, injects relevant past context into the Developer agent
so it can learn from past successes AND failures.
"""

import os
import json
from datetime import datetime
from difflib import SequenceMatcher

_ROOT        = os.path.join(os.path.dirname(__file__), "..")
_MEMORY_DIR  = os.path.join(_ROOT, "memory")
_MEMORY_FILE = os.path.join(_MEMORY_DIR, "sessions.json")
_MAX_SESSIONS = 50   # keep last 50 runs


def _load() -> list:
    os.makedirs(_MEMORY_DIR, exist_ok=True)
    if not os.path.exists(_MEMORY_FILE):
        return []
    with open(_MEMORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(sessions: list) -> None:
    os.makedirs(_MEMORY_DIR, exist_ok=True)
    with open(_MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(sessions[-_MAX_SESSIONS:], f, indent=2)


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def save_session(
    session_id: str,
    user_request: str,
    status: str,
    output_file: str,
    agents_run: list,
    total_tokens: int,
    total_cost: float,
    language: str = "",
    errors_encountered: list = None,
    debug_iterations: int = 0,
) -> None:
    """Call this at the end of every pipeline run."""
    sessions = _load()
    sessions.append({
        "session_id":        session_id,
        "user_request":      user_request,
        "status":            status,
        "output_file":       output_file,
        "agents_run":        agents_run,
        "total_tokens":      total_tokens,
        "total_cost":        round(total_cost, 6),
        "date":              datetime.now().strftime("%Y-%m-%d %H:%M"),
        "language":          language,
        "errors_encountered": errors_encountered or [],
        "debug_iterations":  debug_iterations,
        "succeeded":         status == "passed",
    })
    _save(sessions)


def get_relevant_context(user_request: str, threshold: float = 0.35) -> str:
    """
    Find past sessions similar to the current request.
    Returns a rich context string injected into the Developer prompt.
    Includes: what worked, what failed, language used, error patterns.
    """
    sessions = _load()
    if not sessions:
        return ""

    matches = []
    for s in sessions:
        score = _similarity(user_request, s["user_request"])
        if score >= threshold:
            matches.append((score, s))

    if not matches:
        return ""

    matches.sort(key=lambda x: x[0], reverse=True)
    top_matches = matches[:3]  # top 3 similar projects

    context = f"\n\n{'='*60}\n📚 MEMORY: {len(top_matches)} similar project(s) found\n{'='*60}\n"

    for i, (score, s) in enumerate(top_matches, 1):
        context += f"\n[Project {i}] Similarity: {score:.0%}\n"
        context += f"  Request   : {s['user_request'][:100]}\n"
        context += f"  Date      : {s['date']}\n"
        context += f"  Language  : {s.get('language', 'unknown')}\n"
        context += f"  Status    : {s['status']}\n"
        context += f"  Retries   : {s.get('debug_iterations', 0)}\n"

        if s.get('errors_encountered'):
            context += f"  ⚠️ Past errors  : {', '.join(s['errors_encountered'][:3])}\n"
            context += f"  → AVOID these same errors!\n"

        if s.get('succeeded'):
            context += f"  ✅ This project PASSED — use same language & patterns\n"
        else:
            context += f"  ❌ This project FAILED — try a different approach\n"

    context += f"\n{'='*60}\n"
    context += "Use these past projects as learning. Avoid past errors. Improve on past successes.\n"
    context += f"{'='*60}\n"

    return context


def list_sessions() -> list:
    return _load()
