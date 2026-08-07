import sqlite3
from pathlib import Path

c = sqlite3.connect(Path.home() / ".applypilot/applypilot.db")
print("eligible", c.execute("select count(*) from jobs where fit_score>=7").fetchone()[0])
print("attempts", c.execute("select count(*) from jobs where tailor_attempts>0").fetchone()[0])
print("tailored", c.execute("select count(*) from jobs where tailored_resume_path is not null").fetchone()[0])
print("covers", c.execute("select count(*) from jobs where cover_letter_path is not null").fetchone()[0])
rows = c.execute(
    "select title, tailor_attempts, length(coalesce(tailored_resume_path,'')) from jobs where tailor_attempts>0 order by tailor_attempts desc limit 3"
).fetchall()
for r in rows:
    print(r)
