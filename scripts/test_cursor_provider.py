"""Quick smoke test for LLM provider detection."""
import os

# Test Cursor detection
os.environ["CURSOR_API_KEY"] = "cursor_test_key"
os.environ["OPENROUTER_API_KEY"] = "or_should_not_win"
os.environ["GEMINI_API_KEY"] = "gemini_should_not_win"

from applypilot.llm import _detect_provider, _flatten_messages, LLMClient, _CURSOR_PROVIDER

base, model, key = _detect_provider()
assert base == _CURSOR_PROVIDER
assert model == "auto"
assert key == "cursor_test_key"

flat = _flatten_messages([{"role": "user", "content": "Say hello"}])
assert "Say hello" in flat

client = LLMClient(base, model, key)
assert client._is_cursor is True

print("cursor provider detection: OK")

# Test OpenRouter detection
os.environ.pop("CURSOR_API_KEY")
os.environ["OPENROUTER_API_KEY"] = "or_test_key"

base, model, key = _detect_provider()
assert base == "https://openrouter.ai/api/v1"
assert model == "openrouter/free"
assert key == "or_test_key"

print("openrouter provider detection: OK")
