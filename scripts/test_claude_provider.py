#!/usr/bin/env python3
"""Claude Code CLI provider checks (no network). `--live` also makes one real call."""
from __future__ import annotations

import os
import sys

from applypilot import llm


def _reset() -> None:
    llm._instance = None


def main() -> None:
    saved = {k: os.environ.get(k) for k in ("LLM_PROVIDER", "CLAUDE_LLM_MODEL", "LLM_MODEL", "CURSOR_API_KEY")}
    try:
        # LLM_PROVIDER=claude wins over a Cursor key and ignores LLM_MODEL.
        os.environ["LLM_PROVIDER"] = "claude"
        os.environ["CURSOR_API_KEY"] = "dummy"
        os.environ["LLM_MODEL"] = "auto"
        os.environ.pop("CLAUDE_LLM_MODEL", None)
        base, model, key = llm._detect_provider()
        assert base == llm._CLAUDE_CLI_PROVIDER, base
        assert model == "sonnet", model
        assert key == ""

        os.environ["CLAUDE_LLM_MODEL"] = "opus"
        assert llm._detect_provider()[1] == "opus"

        # Without the opt-in, Cursor detection is unchanged.
        os.environ.pop("LLM_PROVIDER")
        assert llm._detect_provider()[0] == llm._CURSOR_PROVIDER

        # argv: no tools, no settings (hooks), no MCP, no persisted session.
        argv = llm.build_claude_cli_command("sonnet", "SYS")
        for flag in ("-p", "--no-session-persistence", "--strict-mcp-config"):
            assert flag in argv, flag
        assert argv[argv.index("--tools") + 1] == ""
        assert argv[argv.index("--setting-sources") + 1] == ""
        assert argv[argv.index("--system-prompt") + 1] == "SYS"
        assert "--bare" not in argv, "--bare ignores OAuth (subscription login)"

        # System messages go to --system-prompt; one user message passes through verbatim.
        sys_prompt, user = llm.split_system_prompt([
            {"role": "system", "content": "Score jobs."},
            {"role": "user", "content": "JOB TEXT"},
        ])
        assert sys_prompt.startswith(llm._OUTPUT_WRAPPER.strip()[:20])
        assert sys_prompt.endswith("Score jobs.")
        assert user == "JOB TEXT"

        # Multi-turn input is flattened.
        _, user = llm.split_system_prompt([
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"},
        ])
        assert "Assistant:\nb" in user and user.endswith("User:\nc"), user

        # Retryable classification of CLI failures.
        err = llm.ClaudeCLIError("x", is_retryable=True)
        assert err.is_retryable

        if "--live" in sys.argv:
            os.environ["LLM_PROVIDER"] = "claude"
            os.environ.pop("CLAUDE_LLM_MODEL", None)
            _reset()
            out = llm.get_client().chat(
                [
                    {"role": "system", "content": "Reply in the exact format requested."},
                    {"role": "user", "content": "Output exactly: SCORE: 7"},
                ],
                max_tokens=64,
            )
            assert "SCORE: 7" in out, out
            print("live call ok:", out)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        _reset()

    print("test_claude_provider: ok")


if __name__ == "__main__":
    main()
