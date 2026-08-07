# Cursor Auto LLM provider

This fork adds **Cursor Auto mode** as a first-class LLM provider so pipeline stages (score, tailor, cover, enrichment, smart-extract) can run on a Cursor subscription instead of a Gemini API key.

## Why this exists

Gemini's free tier is limited to ~15 requests per minute. Batch-scoring hundreds of jobs hits rate limits quickly. Cursor's **Auto** model (`model="auto"`) is billed against the Cursor plan and is the preferred provider in this checkout.

**Not used:** Cursor Automations (cron/Git/Slack-triggered agents). Those are for event-driven workflows, not synchronous per-job LLM calls inside a Python loop.

## Architecture

```
scorer / tailor / cover_letter / detail / smartextract
                    │
                    ▼
            get_client().chat() / .ask()
                    │
                    ▼
              llm.py LLMClient
                    │
        ┌───────────┴───────────┐
        │ Provider priority:    │
        │ 1. CURSOR_API_KEY     │
        │ 2. OPENROUTER_API_KEY │
        │ 3. GEMINI_API_KEY     │
        │ 4. OPENAI_API_KEY     │
        │ 5. LLM_URL            │
        └───────────┬───────────┘
                    │
    ┌───────────────┼───────────────┐
    ▼               ▼               ▼
  Cursor Auto   OpenRouter     Gemini/OpenAI
  (cursor-sdk)  (OpenAI-compat) (OpenAI-compat)
```

Implementation: [`src/applypilot/llm.py`](../src/applypilot/llm.py)

- `_detect_provider()` returns `("cursor", "auto", api_key)` when `CURSOR_API_KEY` is set.
- `_chat_cursor()` flattens OpenAI-style `messages` into one prompt, prepends `_OUTPUT_WRAPPER`, and calls `Agent.prompt()`.
- `chat()` routes to `_chat_cursor()` when `base_url == "cursor"`.
- `threading.Semaphore` limits parallel Cursor agents (`CURSOR_MAX_CONCURRENCY`, default `2`).

## Configuration

Add to `~/.applypilot/.env`:

```env
# Preferred (highest priority):
CURSOR_API_KEY=cursor_...

# Fallback when Cursor credits exhausted:
OPENROUTER_API_KEY=sk-or-...

# Other providers:
GEMINI_API_KEY=...
OPENAI_API_KEY=...

LLM_MODEL=auto
```

Get a Cursor key: [cursor.com/dashboard/integrations](https://cursor.com/dashboard/integrations)
Get an OpenRouter key (free tier available): [openrouter.ai/keys](https://openrouter.ai/keys)

| Variable | Default | Purpose |
|----------|---------|---------|
| `CURSOR_API_KEY` | — | Cursor Auto provider (highest priority) |
| `OPENROUTER_API_KEY` | — | OpenRouter free-tier models (fallback) |
| `LLM_MODEL` | `auto` | Model override for any provider |
| `CURSOR_MAX_CONCURRENCY` | `2` | Max parallel Cursor agent calls |

`CURSOR_API_KEY` takes priority over `GEMINI_API_KEY` if both are set.

### Wizard

`applypilot init` offers **cursor** as the default provider choice and writes the env vars above.

### Doctor

`applypilot doctor` reports `Cursor Auto (auto)` when configured.

## Provider fallback chain

Priority order (first set key wins):

1. `CURSOR_API_KEY` → Cursor Auto (cursor-sdk local agent)
2. `OPENROUTER_API_KEY` → OpenRouter free-tier models (OpenAI-compat API)
3. `GEMINI_API_KEY` → Gemini (OpenAI-compat + native fallback)
4. `OPENAI_API_KEY` → OpenAI
5. `LLM_URL` → local Ollama / llama.cpp compatible server

## Output format constraints

ApplyPilot parsers expect strict formats:

- **Scoring:** `SCORE: N`, `KEYWORDS: ...`, `REASONING: ...`
- **Tailoring:** JSON resume object (`company`/`title`/`dates`/`bullets` per experience entry — see [resume-tailoring.md](resume-tailoring.md))
- **Cover letter:** letter text (preamble stripped in `cover_letter.py`)
- **Enrichment:** JSON with `full_description` and `application_url`

Auto mode may add preamble. `_OUTPUT_WRAPPER` in `llm.py` instructs the agent to output only requested content. If parsers break, tighten the wrapper or add stripping in the relevant scorer/tailor module.

## Error handling and retries

| Error | Behavior |
|-------|----------|
| `CursorAgentError` + `is_retryable` | Exponential backoff, honor `retry_after` if set |
| `result.status == "error"` | `RuntimeError` after agent run completes |
| Gemini HTTP 429/503 | Existing httpx retry loop in `chat()` |
| OpenRouter 429 | Standard httpx retry loop (respect `Retry-After` header) |

## Dependencies

- `cursor-sdk>=0.1.9` in `pyproject.toml`
- Public beta — pin version if API surface changes

## Latency and cost

- Expect **~30–40 seconds per LLM call** (agent loop overhead vs raw API).
- Scoring 124 jobs sequentially ≈ 70+ minutes.
- Raising `CURSOR_MAX_CONCURRENCY` speeds batches but may hit Cursor fair-use limits.

## Smoke tests

```bash
# No network — provider detection only
.venv/bin/python scripts/test_cursor_provider.py

# Live LLM call
.venv/bin/python scripts/live_cursor_score_test.py

# One real job from SQLite
.venv/bin/python scripts/score_one_job.py
```

## Future work (out of scope unless requested)

- Stage 6 auto-apply uses Cursor agent + browser MCP (see [auto-apply.md](auto-apply.md); default when `CURSOR_API_KEY` is set)
- HTTP shim server (superseded by native `llm.py` integration)
- Cursor Automations for batch orchestration (wrong abstraction for sync LLM calls)
