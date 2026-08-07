import sqlite3
from pathlib import Path

c = sqlite3.connect(Path.home() / ".applypilot" / "applypilot.db")
rows = c.execute(
    """
    SELECT title, site, fit_score, application_url
    FROM jobs
    WHERE fit_score >= 7
      AND tailored_resume_path IS NOT NULL
      AND cover_letter_path IS NOT NULL
      AND applied_at IS NULL
      AND (apply_status IS NULL OR apply_status = 'failed')
      AND application_url IS NOT NULL
      AND application_url != ''
    ORDER BY fit_score DESC
    LIMIT 8
    """
).fetchall()
print(f"{len(rows)} sample ready jobs with application_url:")
for r in rows:
    print(f"  [{r[2]}] {r[1]}: {r[0]}")
    print(f"      {r[3][:100]}")
