import sqlite3
from pathlib import Path

c = sqlite3.connect(Path.home() / ".applypilot/applypilot.db")
rows = c.execute(
    "SELECT title, site, tailored_resume_path FROM jobs WHERE title LIKE '%Cloud Engineer%' AND site LIKE '%BMO%'"
).fetchall()
for r in rows:
    print(r)
