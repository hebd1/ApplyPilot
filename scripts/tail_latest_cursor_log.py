from pathlib import Path

logs = Path.home() / ".applypilot" / "logs"
files = sorted(logs.glob("cursor_*"), key=lambda p: p.stat().st_mtime, reverse=True)
print("latest:", files[0] if files else None)
if files:
    text = files[0].read_text(encoding="utf-8", errors="replace")
    print(text[-1500:])
