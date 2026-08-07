"""Try cursor-sdk auth without explicit API key."""
import os

from cursor_sdk import Agent, AgentOptions, LocalAgentOptions

print("CURSOR_API_KEY set:", bool(os.environ.get("CURSOR_API_KEY")))
try:
    result = Agent.prompt(
        "Reply with exactly: SCORE: 8",
        AgentOptions(
            model="auto",
            local=LocalAgentOptions(cwd="/mnt/c/Users/elihe/Projects/applypilot"),
        ),
    )
    print("status:", result.status)
    print("result:", (result.result or "")[:200])
except Exception as e:
    print(type(e).__name__ + ":", str(e)[:300])
