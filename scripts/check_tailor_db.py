import sqlite3
from pathlib import Path

db = Path.home() / ".applypilot" / "applypilot.db"
c = sqlite3.connect(db)
eligible = c.execute("select count(*) from jobs where fit_score>=7").fetchone()[0]
attempts = c.execute("select count(*) from jobs where tailor_attempts>0").fetchone()[0]
tailored = c.execute("select count(*) from jobs where tailored_resume_path is not null").fetchone()[0]
print(f"eligible={eligible} attempts={attempts} tailored={tailored}")
rows = c.execute(
    "select title, tailor_attempts, tailored_resume_path from jobs where tailor_attempts>0 limit 5"
).fetchall()
for r in rows:
    print(r)
covers = c.execute("select count(*) from jobs where cover_letter_path is not null").fetchone()[0]
print(f"cover_letters={covers}")
