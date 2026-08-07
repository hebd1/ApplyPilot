import sqlite3
from pathlib import Path

c = sqlite3.connect(Path.home() / ".applypilot" / "applypilot.db")
row = c.execute(
    """
    SELECT title, site, url, application_url, apply_status
    FROM jobs
    WHERE title LIKE '%Full Stack%' AND site LIKE '%Thomson%'
    LIMIT 1
    """
).fetchone()
print(row)
