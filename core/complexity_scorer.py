"""
core/complexity_scorer.py
────────────────────────────────────────────────────────────────────────────────
Scores the user request 1-10 for complexity.
- score ≤ 4  → use light model (llama-3.1-8b-instant) for all agents
- score > 4  → use heavy model (llama-3.3-70b-versatile) as normal

This saves Groq tokens on simple builds, reserving quota for complex ones.
────────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations
import re
from typing import Any

_SCORER_PROMPT = """\
You are a software complexity classifier. Rate this app request 1-10.

Complexity scale:
  1-2  Trivial    — single feature, no persistence
  3-4  Simple     — 1-2 features, basic CRUD on one entity
  5-6  Moderate   — 3-5 features, multi-table DB, charts
  7-8  Complex    — many features, multiple entities, complex logic
  9-10 Very complex — enterprise-grade, multi-service, external APIs

Request: {prompt}

Respond ONLY in this format:
SCORE: <integer 1-10>
REASON: <one sentence>"""

SIMPLE_THRESHOLD = 4
SIMPLE_MODEL     = "llama-3.1-8b-instant"
HEAVY_MODEL      = "llama-3.3-70b-versatile"


def score_complexity(request: str, session_id: str = "") -> tuple[int, str]:
    """Score the request and return (score, reason)."""
    from core.agent_runner import run_agent
    try:
        raw = run_agent(
            "analyst",
            _SCORER_PROMPT.format(prompt=request[:1000]),
            session_id=session_id,
        )
        return _parse_score(raw)
    except Exception:
        return 5, "Scoring failed — defaulting to moderate"


def get_model_for_complexity(score: int) -> str:
    """Return the appropriate model name based on complexity score."""
    if score <= SIMPLE_THRESHOLD:
        print(f"\n  [ComplexityScorer] Score {score}/10 — SIMPLE → using light model")
        return SIMPLE_MODEL
    print(f"\n  [ComplexityScorer] Score {score}/10 — COMPLEX → using heavy model")
    return HEAVY_MODEL


def _parse_score(raw: str) -> tuple[int, str]:
    score = 5
    reason = raw.strip()
    m = re.search(r"SCORE:\s*(\d+)", raw, re.IGNORECASE)
    if m:
        score = max(1, min(10, int(m.group(1))))
    r = re.search(r"REASON:\s*(.+)", raw, re.IGNORECASE)
    if r:
        reason = r.group(1).strip()
    return score, reason
