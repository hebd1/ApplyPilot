"""Test Cursor SDK Agent.prompt works."""
import os, sys, time
from cursor_sdk import Agent, AgentOptions, LocalAgentOptions, CursorAgentError

from dotenv import load_dotenv
load_dotenv(os.path.expanduser("~/.applypilot/.env"))

api_key = os.environ.get("CURSOR_API_KEY", "")
if not api_key:
    print("CURSOR_API_KEY not set")
    sys.exit(1)

for model in ["auto", "composer-2.5"]:
    print(f"\nTesting Agent.prompt with model={model}")
    start = time.time()
    try:
        result = Agent.prompt(
            "Say hello in one word",
            AgentOptions(
                api_key=api_key,
                model=model,
                local=LocalAgentOptions(cwd="/tmp", setting_sources=[]),
            ),
        )
        elapsed = int(time.time() - start)
        print(f"  Status: {result.status} ({elapsed}s)")
        print(f"  Result: {(result.result[:200] if result.result else '(empty)')}")
        if result.status == "error":
            print(f"  Model used: {result.model}")
        else:
            print(f"  Model used: {result.model}")
            print("SUCCESS")
            sys.exit(0)
    except CursorAgentError as e:
        print(f"  CursorAgentError: {e.message} (retryable={e.is_retryable})")
    except Exception as e:
        print(f"  Error: {e}")

print("ALL MODELS FAILED")
sys.exit(1)