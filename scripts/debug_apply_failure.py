"""Inspect apply backend + last failed job error."""
import sqlite3
from pathlib import Path

from applypilot.apply.cursor_apply import get_apply_backend
from applypilot.config import load_env

load_env()
print("backend:", get_apply_backend())

db = Path.home() / ".applypilot" / "applypilot.db"
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
row = conn.execute(
    """
    SELECT title, site, apply_status, apply_error, apply_attempts, application_url, url
    FROM jobs
    WHERE apply_status IS NOT NULL OR apply_error IS NOT NULL
    ORDER BY COALESCE(applied_at, '') DESC, rowid DESC
    LIMIT 5
    """
).fetchall()
print("recent apply rows:")
for r in row:
    print(dict(r))

logs = Path.home() / ".applypilot" / "logs"
if logs.is_dir():
    files = sorted(logs.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:5]
    print("recent logs:")
    for f in files:
        print(" ", f.name, f.stat().st_size)
