"""Clear applied status for a job wrongly marked by dry-run."""
import sqlite3
from pathlib import Path

url = "https://www.indeed.com/viewjob?jk=1a451f73e80ca7f8"
conn = sqlite3.connect(Path.home() / ".applypilot" / "applypilot.db")
conn.execute(
    """
    UPDATE jobs SET apply_status=NULL, applied_at=NULL, apply_error=NULL,
           apply_attempts=0, agent_id=NULL
    WHERE url=? OR application_url LIKE ?
    """,
    (url, "%xh1kk7dg5us%"),
)
conn.commit()
row = conn.execute(
    "SELECT title, apply_status, applied_at FROM jobs WHERE application_url LIKE ?",
    ("%xh1kk7dg5us%",),
).fetchone()
print("reset:", row)
