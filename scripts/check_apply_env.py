import os
import shutil
from pathlib import Path

from applypilot.apply.cursor_apply import get_apply_backend
from applypilot.config import load_env

load_env()
print("APPLY_BACKEND=", repr(os.environ.get("APPLY_BACKEND")))
print("CURSOR_API_KEY set=", bool(os.environ.get("CURSOR_API_KEY")))
print("get_apply_backend=", get_apply_backend())
print("which applypilot=", shutil.which("applypilot"))
print("venv applypilot=", Path(__file__).resolve().parents[1] / ".venv/bin/applypilot")
env_path = Path.home() / ".applypilot" / ".env"
if env_path.is_file():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.strip().startswith("#"):
            key = line.split("=", 1)[0]
            if key in ("APPLY_BACKEND", "CURSOR_API_KEY", "LLM_MODEL", "CHROME_PATH"):
                val = line.split("=", 1)[1] if "=" in line else ""
                print(f".env {key}=", "(set)" if key.endswith("KEY") else val)
