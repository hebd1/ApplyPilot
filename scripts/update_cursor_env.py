"""Update ~/.applypilot/.env with Cursor API key from environment."""
from __future__ import annotations

import os
import sys
from pathlib import Path

key = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("CURSOR_API_KEY", "")).strip()
if not key:
    print("ERROR: CURSOR_API_KEY env var required")
    sys.exit(1)

env_path = Path.home() / ".applypilot" / ".env"
text = env_path.read_text(encoding="utf-8") if env_path.exists() else "# ApplyPilot configuration\n\n"

lines: list[str] = []
seen_cursor = False
seen_model = False
for line in text.splitlines():
    if line.startswith("CURSOR_API_KEY="):
        lines.append(f"CURSOR_API_KEY={key}")
        seen_cursor = True
    elif line.startswith("LLM_MODEL="):
        lines.append("LLM_MODEL=auto")
        seen_model = True
    else:
        lines.append(line)

if not seen_cursor:
    lines.append(f"CURSOR_API_KEY={key}")
if not seen_model:
    lines.append("LLM_MODEL=auto")

env_path.parent.mkdir(parents=True, exist_ok=True)
env_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
print(f"updated {env_path}")
