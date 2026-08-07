"""Live Cursor Auto smoke test."""
from __future__ import annotations

import os
import sys

from applypilot.config import load_env

load_env()

api_key = os.environ.get("CURSOR_API_KEY", "")
if not api_key:
    print("ERROR: CURSOR_API_KEY is not set in environment or ~/.applypilot/.env")
    sys.exit(1)

from applypilot.llm import get_client

client = get_client()
print(f"Provider: cursor, model: {client.model}")

response = client.ask(
    "You are a job fit evaluator. Score this match 1-10.\n"
    "Candidate: Python developer with 5 years experience.\n"
    "Job: Senior Python Engineer.\n\n"
    "RESPOND IN EXACTLY THIS FORMAT (no other text):\n"
    "SCORE: [1-10]\n"
    "KEYWORDS: python\n"
    "REASONING: [2-3 sentences]",
    max_tokens=256,
    temperature=0.2,
)
print("--- response ---")
print(response)
print("---")

if "SCORE:" in response:
    print("LIVE_CURSOR_SCORE_TEST: PASS")
else:
    print("LIVE_CURSOR_SCORE_TEST: FAIL (missing SCORE: prefix)")
    sys.exit(2)
