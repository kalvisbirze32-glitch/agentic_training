"""Canonical token counting for the retail_context project.

Methodology — two paths planned:

1. **SDK path (preferred)** — Anthropic `messages.count_tokens` endpoint
   (model-authoritative). Active when `ANTHROPIC_API_KEY` is set.
2. **Heuristic path (fallback)** — `len(text) / 3.8` (a documented Claude
   tokenizer approximation, ~3.8 characters per token in English). Active when
   no API key is available (e.g., local development against the Claude Code
   subscription, where the count_tokens endpoint is not exposed via the CLI).

Tokenization specifics are out of scope, so the choice of algorithm does not
matter here. What matters is that *every* measurement in this
project flows through this single function. The active methodology is recorded
in `runs/<run_id>/budget.json` so the reviewer can interpret the numbers.

Both paths are implemented below; the SDK path is chosen whenever the API key is
present in the environment.
"""
from __future__ import annotations

import os
from functools import lru_cache

from retail_context.client import get_client, get_model

_CHARS_PER_TOKEN = 3.8


def _use_sdk() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def methodology() -> str:
    # Recorded verbatim in budget.json, so it must state which path is live.
    if _use_sdk():
        return "Anthropic messages.count_tokens endpoint (model-authoritative)"
    return f"len(text) / {_CHARS_PER_TOKEN} heuristic (no API key available)"


@lru_cache(maxsize=4096)
def count(text: str) -> int:
    if not text:
        return 0
    if _use_sdk():
        resp = get_client().messages.count_tokens(
            model=get_model(),
            messages=[{"role": "user", "content": text}],
        )
        return int(resp.input_tokens)
    # A non-empty string is never reported as 0 tokens.
    return max(1, int(len(text) / _CHARS_PER_TOKEN))


def count_many(texts: list[str]) -> int:
    return sum(count(t) for t in texts)
