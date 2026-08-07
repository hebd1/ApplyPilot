"""Ensure APPLY_BACKEND=cursor in ~/.applypilot/.env."""
from pathlib import Path

env_path = Path.home() / ".applypilot" / ".env"
text = env_path.read_text(encoding="utf-8") if env_path.is_file() else ""
lines = text.splitlines()
out: list[str] = []
found = False
for line in lines:
    if line.startswith("APPLY_BACKEND="):
        out.append("APPLY_BACKEND=cursor")
        found = True
    else:
        out.append(line)
if not found:
    out.append("APPLY_BACKEND=cursor")
env_path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
print(f"set APPLY_BACKEND=cursor in {env_path}")
