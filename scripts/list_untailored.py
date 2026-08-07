"""List jobs still needing tailor after regeneration."""
import sqlite3
from pathlib import Path

c = sqlite3.connect(Path.home() / ".applypilot/applypilot.db")
c.row_factory = sqlite3.Row
rows = c.execute(
    """
    SELECT title, site, fit_score, tailor_attempts, tailored_resume_path
    FROM jobs
    WHERE fit_score >= 7 AND tailored_resume_path IS NULL
    ORDER BY fit_score DESC, title
    """
).fetchall()
print(f"untailored: {len(rows)}")
for r in rows[:20]:
    print(f"  [{r['fit_score']}] attempts={r['tailor_attempts']} {r['site']}: {r['title']}")
if len(rows) > 20:
    print(f"  ... and {len(rows)-20} more")
