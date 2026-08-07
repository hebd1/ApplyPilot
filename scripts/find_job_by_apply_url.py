import sqlite3
import sys
from pathlib import Path

needle = sys.argv[1] if len(sys.argv) > 1 else "xh1kk7dg5us"
c = sqlite3.connect(Path.home() / ".applypilot" / "applypilot.db")
c.row_factory = sqlite3.Row
rows = c.execute(
    """
    SELECT title, site, url, application_url, apply_status, apply_attempts,
           tailored_resume_path IS NOT NULL AS has_resume
    FROM jobs
    WHERE application_url LIKE ? OR url LIKE ?
    """,
    (f"%{needle}%", f"%{needle}%"),
).fetchall()
print(f"matches for {needle}: {len(rows)}")
for r in rows:
    print(dict(r))
