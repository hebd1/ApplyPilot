"""Fix ~/.applypilot/.env: LLM_MODEL=auto, CHROME_PATH to Playwright Chromium."""
from pathlib import Path

env_path = Path.home() / ".applypilot" / ".env"
chrome = Path.home() / ".cache/ms-playwright/chromium-1228/chrome-linux64/chrome"
if not chrome.is_file():
    matches = sorted(Path.home().glob(".cache/ms-playwright/chromium-*/chrome-linux*/chrome"))
    chrome = matches[-1] if matches else None

text = env_path.read_text(encoding="utf-8") if env_path.exists() else "# ApplyPilot configuration\n\n"
lines: list[str] = []
seen_chrome = False
seen_model = False
for line in text.splitlines():
    if line.startswith("CHROME_PATH=") or line.startswith("nCHROME_PATH="):
        if chrome:
            lines.append(f"CHROME_PATH={chrome}")
            seen_chrome = True
        continue
    if line.startswith("LLM_MODEL="):
        lines.append("LLM_MODEL=auto")
        seen_model = True
        continue
    lines.append(line)

if chrome and not seen_chrome:
    lines.append(f"CHROME_PATH={chrome}")
if not seen_model:
    lines.append("LLM_MODEL=auto")

env_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
print(f"fixed {env_path}")
print(f"CHROME_PATH={'set' if chrome else 'MISSING'}")
