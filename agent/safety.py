"""Input safety for Dormio.

Three lightweight checks run before any model call:

1. Validation: empty, over-long, or obviously off-topic input is rejected for free.
2. Rate limiting in session state, so a double click or a script cannot fire the
   agent repeatedly (OWASP LLM10, unbounded consumption).
3. Two-layer abuse screening: a regex pre-filter for prompt injection, which
   Mistral's moderation does not flag, plus Mistral moderation for harmful
   content like hate, violence, or personal data (OWASP LLM01).

Moderation fails open. If the classifier is unreachable we log and let a
legitimate traveller through rather than block them.
"""
from __future__ import annotations

import re
import time
import logging

import httpx

import config

logger = logging.getLogger(__name__)

MAX_QUERY_LEN = 500

# Blatant prompt-injection and jailbreak phrasing. This is the fast first pass,
# not the whole defence; the prompts also fence user content as data.
_INJECTION_PATTERNS = [
    r"ignore (all |the |your )?(previous|prior|above|earlier) (instructions|prompts|messages)",
    r"disregard (all |the |your )?(previous|prior|above)",
    r"forget (all |everything|your|the) (instructions|rules|prompt)",
    r"you are now (a|an|in)",
    r"(reveal|show|print|repeat|tell me) (your |the )?(system )?(prompt|instructions)",
    r"act as (a |an )?(dan|jailbreak)",
    r"developer mode",
    r"</?(system|assistant|user)>",
    r"<\|im_(start|end)\|>",
    r"new instructions\s*:",
    r"system prompt",
    r"repeat the (words|text|message)",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)


def validate_input(text: str) -> tuple:
    """Cheap offline checks. Returns (ok, reason)."""
    if not text or not text.strip():
        return False, "Please enter where you want to travel from and to."
    if len(text) > MAX_QUERY_LEN:
        return False, f"That is quite long. Please keep it under {MAX_QUERY_LEN} characters."
    if _INJECTION_RE.search(text):
        return False, (
            "That looks like an attempt to change how the assistant works. "
            "Please ask about a train route in Europe."
        )
    return True, ""


def check_rate_limit(session_state) -> tuple:
    """Reject rapid or excessive submits using session state. Returns (ok, reason)."""
    now = time.time()
    last = session_state.get("_last_submit_ts", 0.0)
    count = session_state.get("_submit_count", 0)
    if now - last < config.RATE_LIMIT_MIN_SECONDS:
        return False, "Just a moment, please wait a few seconds between searches."
    if count >= config.RATE_LIMIT_MAX_PER_SESSION:
        return False, "You have reached the search limit for this session. Refresh the page to continue."
    session_state["_last_submit_ts"] = now
    session_state["_submit_count"] = count + 1
    return True, ""


def moderate(text: str) -> tuple:
    """Mistral moderation for harmful content. Returns (flagged, categories). Fails open."""
    if not config.MISTRAL_API_KEY:
        return False, ""
    try:
        resp = httpx.post(
            f"{config.MISTRAL_BASE_URL}/moderations",
            headers={"Authorization": f"Bearer {config.MISTRAL_API_KEY}"},
            json={"model": config.MODERATION_MODEL, "input": [text]},
            timeout=10.0,
        )
        resp.raise_for_status()
        result = (resp.json().get("results") or [{}])[0]
        categories = result.get("categories", {}) or {}
        flagged = [name for name, hit in categories.items() if hit]
        return (bool(flagged), ", ".join(flagged))
    except Exception as exc:
        logger.warning("Moderation unavailable, allowing input: %s", exc)
        return False, ""


def screen_query(text: str, session_state) -> tuple:
    """Full pre-flight before calling the agent. Returns (ok, reason)."""
    ok, reason = validate_input(text)
    if not ok:
        return False, reason
    ok, reason = check_rate_limit(session_state)
    if not ok:
        return False, reason
    flagged, categories = moderate(text)
    if flagged:
        logger.info("Moderation flagged input (%s)", categories)
        return False, (
            "This request was flagged by the safety filter. "
            "Please keep questions to train travel in Europe."
        )
    return True, ""
