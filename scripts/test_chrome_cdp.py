"""Verify Chrome CDP launch for auto-apply (Playwright Chromium)."""
import os
import sys
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"))

from applypilot.config import load_env
from applypilot.apply.chrome import launch_chrome, cleanup_worker, BASE_CDP_PORT

load_env()
port = BASE_CDP_PORT
print(f"CHROME_PATH={os.environ.get('CHROME_PATH', '(auto)')}")
proc = launch_chrome(worker_id=0, port=port, headless=True)
try:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=5) as resp:
        print("CDP OK:", resp.read()[:120])
finally:
    cleanup_worker(0, proc)
print("Chrome auto-apply launch: OK")
