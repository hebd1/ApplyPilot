"""
Unified LLM client for ApplyPilot.

Auto-detects provider from environment:
  LLM_PROVIDER=claude -> Claude Code CLI (`claude -p`, subscription auth;
                         CLAUDE_LLM_MODEL, default: sonnet). Takes priority.
  CURSOR_API_KEY     -> Cursor Auto mode (default: auto)
  OPENROUTER_API_KEY -> OpenRouter free-tier models (default: openrouter/free)
  GEMINI_API_KEY     -> Google Gemini (default: gemini-2.0-flash)
  OPENAI_API_KEY     -> OpenAI (default: gpt-4o-mini)
  LLM_URL            -> Local llama.cpp / Ollama compatible endpoint

LLM_MODEL env var overrides the model name for any provider.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime

import httpx

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------

_CURSOR_PROVIDER = "cursor"
_CLAUDE_CLI_PROVIDER = "claude-cli"

_OUTPUT_WRAPPER = (
    "You are a text-generation assistant. Output ONLY the requested content. "
    "No commentary, preamble, tool use, or markdown fences unless explicitly asked.\n\n"
)


def _detect_provider() -> tuple[str, str, str]:
    """Return (base_url, model, api_key) based on environment variables.

    Reads env at call time (not module import time) so that load_env() called
    in _bootstrap() is always visible here.
    """
    cursor_key = os.environ.get("CURSOR_API_KEY", "")
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    local_url = os.environ.get("LLM_URL", "")
    model_override = os.environ.get("LLM_MODEL", "")

    # Explicit opt-in: Claude Code CLI on the user's subscription. Uses its own
    # model variable so a leftover LLM_MODEL (e.g. "auto") does not leak in.
    if os.environ.get("LLM_PROVIDER", "").strip().lower() in ("claude", "claude-cli"):
        return (
            _CLAUDE_CLI_PROVIDER,
            os.environ.get("CLAUDE_LLM_MODEL", "").strip() or "sonnet",
            "",
        )

    # If the model looks like an OpenRouter model (contains "/" like "openrouter/free"
    # or "qwen/qwen3.7-flash"), prefer OpenRouter even if CURSOR_API_KEY is set.
    # The CURSOR_API_KEY is still used by the apply agent (Stage 6) independently.
    if openrouter_key and model_override and "/" in model_override:
        or_model = model_override if model_override != "auto" else ""
        return (
            "https://openrouter.ai/api/v1",
            or_model or "openrouter/free",
            openrouter_key,
        )

    if cursor_key:
        return (_CURSOR_PROVIDER, model_override or "auto", cursor_key)

    if openrouter_key:
        or_model = model_override
        if not or_model or or_model == "auto":
            or_model = ""
        return (
            "https://openrouter.ai/api/v1",
            or_model or "openrouter/free",
            openrouter_key,
        )

    if gemini_key and not local_url:
        return (
            "https://generativelanguage.googleapis.com/v1beta/openai",
            model_override or "gemini-2.0-flash",
            gemini_key,
        )

    if openai_key and not local_url:
        return (
            "https://api.openai.com/v1",
            model_override or "gpt-4o-mini",
            openai_key,
        )

    if local_url:
        return (
            local_url.rstrip("/"),
            model_override or "local-model",
            os.environ.get("LLM_API_KEY", ""),
        )

    raise RuntimeError(
        "No LLM provider configured. "
        "Set CURSOR_API_KEY, OPENROUTER_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY, or LLM_URL in your environment."
    )


def _flatten_messages(messages: list[dict]) -> str:
    """Convert OpenAI-style messages into a single prompt for Cursor agents."""
    parts: list[str] = []
    for msg in messages:
        role = msg["role"]
        text = msg.get("content", "")
        if role == "system":
            parts.append(f"Instructions:\n{text}")
        elif role == "user":
            parts.append(f"User:\n{text}")
        elif role == "assistant":
            parts.append(f"Assistant:\n{text}")
    return "\n\n".join(parts)


def _cursor_retry_wait(exc: Exception, attempt: int) -> float:
    """Compute wait seconds for a retryable Cursor error."""
    retry_after = getattr(exc, "retry_after", None)
    if retry_after is not None:
        if isinstance(retry_after, (int, float)):
            return float(retry_after)
        if isinstance(retry_after, datetime):
            return max(0.0, (retry_after - datetime.now(retry_after.tzinfo)).total_seconds())
        try:
            return float(retry_after)
        except (TypeError, ValueError):
            pass
    return min(_RATE_LIMIT_BASE_WAIT * (2 ** attempt), 60)


_cursor_semaphore: threading.Semaphore | None = None
_claude_semaphore: threading.Semaphore | None = None


class ClaudeCLIError(RuntimeError):
    """`claude -p` exited non-zero or timed out."""

    def __init__(self, message: str, *, is_retryable: bool) -> None:
        super().__init__(message)
        self.is_retryable = is_retryable


_CLAUDE_RETRYABLE_MARKERS = ("rate limit", "rate_limit", "overloaded", "529", "429", "timed out", "econnreset")


def _get_claude_semaphore() -> threading.Semaphore:
    global _claude_semaphore
    if _claude_semaphore is None:
        limit = int(os.environ.get("CLAUDE_MAX_CONCURRENCY", "2"))
        _claude_semaphore = threading.Semaphore(max(1, limit))
    return _claude_semaphore


def claude_cli_path() -> str | None:
    """Locate `claude`: CLAUDE_CLI_PATH, PATH, then ~/.local/bin (absent from non-login PATHs)."""
    explicit = os.environ.get("CLAUDE_CLI_PATH")
    if explicit:
        return explicit
    found = shutil.which("claude")
    if found:
        return found
    local = os.path.expanduser("~/.local/bin/claude")
    return local if os.path.isfile(local) else None


def build_claude_cli_command(model: str, system_prompt: str) -> list[str]:
    """argv for a tool-less, settings-less, non-persisted `claude -p` call.

    `--setting-sources ""` skips user/project settings (and with them any
    hooks), `--tools ""` makes it pure text generation, and
    `--strict-mcp-config` keeps MCP servers out. `--bare` is not used: it
    ignores OAuth, and this provider runs on the user's subscription login.
    """
    exe = claude_cli_path() or "claude"
    return [
        exe, "-p",
        "--model", model,
        "--output-format", "text",
        "--tools", "",
        "--setting-sources", "",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--system-prompt", system_prompt,
    ]


def split_system_prompt(messages: list[dict]) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for the Claude CLI.

    System messages become the CLI system prompt (prefixed with the
    output-only wrapper); everything else is flattened into stdin.
    """
    system = [m.get("content", "") for m in messages if m["role"] == "system"]
    rest = [m for m in messages if m["role"] != "system"]
    system_prompt = _OUTPUT_WRAPPER + "\n\n".join(system)
    if len(rest) == 1 and rest[0]["role"] == "user":
        user_prompt = rest[0].get("content", "")
    else:
        user_prompt = _flatten_messages(rest)
    return system_prompt.strip(), user_prompt


def _get_cursor_semaphore() -> threading.Semaphore:
    global _cursor_semaphore
    if _cursor_semaphore is None:
        limit = int(os.environ.get("CURSOR_MAX_CONCURRENCY", "2"))
        _cursor_semaphore = threading.Semaphore(max(1, limit))
    return _cursor_semaphore


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

_MAX_RETRIES = 5
_TIMEOUT = 120  # seconds

# Base wait on first 429/503 (doubles each retry, caps at 60s).
# Gemini free tier is 15 RPM = 4s minimum between requests; 10s gives headroom.
_RATE_LIMIT_BASE_WAIT = 10


_GEMINI_COMPAT_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"
_GEMINI_NATIVE_BASE = "https://generativelanguage.googleapis.com/v1beta"


class LLMClient:
    """Thin LLM client supporting Cursor Auto, OpenAI-compatible, and native Gemini endpoints.

    For Gemini keys, starts on the OpenAI-compat layer. On a 403 (which
    happens with preview/experimental models not exposed via compat), it
    automatically switches to the native generateContent API and stays there
    for the lifetime of the process.
    """

    def __init__(self, base_url: str, model: str, api_key: str) -> None:
        self.base_url = base_url
        self.model = model
        self.api_key = api_key
        self._client = httpx.Client(timeout=_TIMEOUT)
        # True once we've confirmed the native Gemini API works for this model
        self._use_native_gemini: bool = False
        self._is_gemini: bool = base_url.startswith(_GEMINI_COMPAT_BASE)
        self._is_cursor: bool = base_url == _CURSOR_PROVIDER
        self._is_claude_cli: bool = base_url == _CLAUDE_CLI_PROVIDER

    # -- Claude Code CLI ----------------------------------------------------

    def _chat_claude_cli(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Call `claude -p` (Claude Code CLI, subscription auth).

        The CLI has no temperature / max-token flags; length limits are
        stated in the prompt the same way the Cursor path does it.
        """
        system_prompt, user_prompt = split_system_prompt(messages)
        if max_tokens != 4096:
            user_prompt += f"\n\n(Keep the response under about {max_tokens} tokens.)"

        timeout = int(os.environ.get("CLAUDE_CLI_TIMEOUT", "300"))
        env = dict(os.environ)
        env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] = "1"
        with _get_claude_semaphore(), tempfile.TemporaryDirectory(prefix="applypilot-llm-") as cwd:
            try:
                proc = subprocess.run(
                    build_claude_cli_command(self.model, system_prompt),
                    input=user_prompt,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=timeout,
                    cwd=cwd,
                    env=env,
                )
            except subprocess.TimeoutExpired as exc:
                raise ClaudeCLIError(f"claude -p timed out after {timeout}s", is_retryable=True) from exc

        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[-500:]
            retryable = any(m in detail.lower() for m in _CLAUDE_RETRYABLE_MARKERS)
            raise ClaudeCLIError(f"claude -p exited {proc.returncode}: {detail}", is_retryable=retryable)
        return proc.stdout.strip()

    # -- Cursor Auto API ----------------------------------------------------

    def _chat_cursor(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Call Cursor Auto mode via cursor-sdk."""
        from cursor_sdk import Agent, AgentOptions, CursorAgentError, LocalAgentOptions

        prompt = _OUTPUT_WRAPPER + _flatten_messages(messages)
        if temperature != 0.0 or max_tokens != 4096:
            prompt += (
                f"\n\nGeneration settings: temperature={temperature}, "
                f"max_output_tokens={max_tokens}."
            )

        with _get_cursor_semaphore():
            try:
                result = Agent.prompt(
                    prompt,
                    AgentOptions(
                        api_key=self.api_key,
                        model=self.model,
                        local=LocalAgentOptions(cwd=os.getcwd()),
                    ),
                )
            except CursorAgentError:
                raise

        if result.status == "finished":
            return result.result or ""

        raise RuntimeError(
            f"Cursor agent run failed (status={result.status}, id={getattr(result, 'id', '?')})"
        )

    # -- Native Gemini API --------------------------------------------------

    def _chat_native_gemini(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Call the native Gemini generateContent API.

        Used automatically when the OpenAI-compat endpoint returns 403,
        which happens for preview/experimental models not exposed via compat.

        Converts OpenAI-style messages to Gemini's contents/systemInstruction
        format transparently.
        """
        contents: list[dict] = []
        system_parts: list[dict] = []

        for msg in messages:
            role = msg["role"]
            text = msg.get("content", "")
            if role == "system":
                system_parts.append({"text": text})
            elif role == "user":
                contents.append({"role": "user", "parts": [{"text": text}]})
            elif role == "assistant":
                # Gemini uses "model" instead of "assistant"
                contents.append({"role": "model", "parts": [{"text": text}]})

        payload: dict = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}

        url = f"{_GEMINI_NATIVE_BASE}/models/{self.model}:generateContent"
        resp = self._client.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            params={"key": self.api_key},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]

    # -- OpenAI-compat API --------------------------------------------------

    def _chat_compat(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Call the OpenAI-compatible endpoint."""
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        resp = self._client.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers=headers,
        )

        # 403 on Gemini compat = model not available on compat layer.
        # Raise a specific sentinel so chat() can switch to native API.
        if resp.status_code == 403 and self._is_gemini:
            raise _GeminiCompatForbidden(resp)

        return self._handle_compat_response(resp)

    @staticmethod
    def _handle_compat_response(resp: httpx.Response) -> str:
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    # -- public API ---------------------------------------------------------

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> str:
        """Send a chat completion request and return the assistant message text."""
        # Qwen3 optimization: prepend /no_think to skip chain-of-thought
        # reasoning, saving tokens on structured extraction tasks.
        if "qwen" in self.model.lower() and messages:
            first = messages[0]
            if first.get("role") == "user" and not first["content"].startswith("/no_think"):
                messages = [{"role": first["role"], "content": f"/no_think\n{first['content']}"}] + messages[1:]

        for attempt in range(_MAX_RETRIES):
            try:
                if self._is_claude_cli:
                    return self._chat_claude_cli(messages, temperature, max_tokens)

                if self._is_cursor:
                    return self._chat_cursor(messages, temperature, max_tokens)

                # Route to native Gemini if we've already confirmed it's needed
                if self._use_native_gemini:
                    return self._chat_native_gemini(messages, temperature, max_tokens)

                return self._chat_compat(messages, temperature, max_tokens)

            except _GeminiCompatForbidden:
                # Model not available on OpenAI-compat layer — switch to native.
                log.warning(
                    "Gemini compat endpoint returned 403 for model '%s'. "
                    "Switching to native generateContent API. "
                    "(Preview/experimental models are often compat-only on native.)",
                    self.model,
                )
                self._use_native_gemini = True
                # Retry immediately with native — don't count as a rate-limit wait
                try:
                    return self._chat_native_gemini(messages, temperature, max_tokens)
                except httpx.HTTPStatusError as native_exc:
                    raise RuntimeError(
                        f"Both Gemini endpoints failed. Compat: 403 Forbidden. "
                        f"Native: {native_exc.response.status_code} — "
                        f"{native_exc.response.text[:200]}"
                    ) from native_exc

            except httpx.HTTPStatusError as exc:
                resp = exc.response
                if resp.status_code in (429, 503) and attempt < _MAX_RETRIES - 1:
                    # Respect Retry-After header if provided (Gemini sends this).
                    retry_after = (
                        resp.headers.get("Retry-After")
                        or resp.headers.get("X-RateLimit-Reset-Requests")
                    )
                    if retry_after:
                        try:
                            wait = float(retry_after)
                        except (ValueError, TypeError):
                            wait = _RATE_LIMIT_BASE_WAIT * (2 ** attempt)
                    else:
                        wait = min(_RATE_LIMIT_BASE_WAIT * (2 ** attempt), 60)

                    log.warning(
                        "LLM rate limited (HTTP %s). Waiting %ds before retry %d/%d. "
                        "Tip: Gemini free tier = 15 RPM. Consider a paid account "
                        "or switching to a local model.",
                        resp.status_code, wait, attempt + 1, _MAX_RETRIES,
                    )
                    time.sleep(wait)
                    continue
                raise

            except ClaudeCLIError as exc:
                if exc.is_retryable and attempt < _MAX_RETRIES - 1:
                    wait = min(_RATE_LIMIT_BASE_WAIT * (2 ** attempt), 60)
                    log.warning("Claude CLI call failed (%s). Retrying in %ds (%d/%d).",
                                exc, wait, attempt + 1, _MAX_RETRIES)
                    time.sleep(wait)
                    continue
                raise

            except httpx.TimeoutException:
                if attempt < _MAX_RETRIES - 1:
                    wait = min(_RATE_LIMIT_BASE_WAIT * (2 ** attempt), 60)
                    log.warning(
                        "LLM request timed out, retrying in %ds (attempt %d/%d)",
                        wait, attempt + 1, _MAX_RETRIES,
                    )
                    time.sleep(wait)
                    continue
                raise

            except Exception as exc:
                from cursor_sdk import CursorAgentError

                if isinstance(exc, CursorAgentError):
                    if getattr(exc, "is_retryable", False) and attempt < _MAX_RETRIES - 1:
                        wait = _cursor_retry_wait(exc, attempt)
                        log.warning(
                            "Cursor LLM rate limited. Waiting %ds before retry %d/%d.",
                            wait,
                            attempt + 1,
                            _MAX_RETRIES,
                        )
                        time.sleep(wait)
                        continue
                    raise
                raise

        raise RuntimeError("LLM request failed after all retries")

    def ask(self, prompt: str, **kwargs) -> str:
        """Convenience: single user prompt -> assistant response."""
        return self.chat([{"role": "user", "content": prompt}], **kwargs)

    def close(self) -> None:
        self._client.close()


class _GeminiCompatForbidden(Exception):
    """Sentinel: Gemini OpenAI-compat returned 403. Switch to native API."""
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        super().__init__(f"Gemini compat 403: {response.text[:200]}")


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: LLMClient | None = None


def get_client() -> LLMClient:
    """Return (or create) the module-level LLMClient singleton."""
    global _instance
    if _instance is None:
        base_url, model, api_key = _detect_provider()
        provider_label = {
            _CURSOR_PROVIDER: "Cursor Auto",
            _CLAUDE_CLI_PROVIDER: "Claude Code CLI",
        }.get(base_url, base_url)
        log.info("LLM provider: %s  model: %s", provider_label, model)
        _instance = LLMClient(base_url, model, api_key)
    return _instance
