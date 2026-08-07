"""Check overlap between apply-ready jobs and tailored materials."""
from pathlib import Path

from applypilot.config import load_env
from applypilot.database import get_connection, init_db
from applypilot.view import _local_file_href

load_env()
init_db()
conn = get_connection()

rows = conn.execute("""
    SELECT title, site, fit_score, application_url,
           tailored_resume_path, cover_letter_path
    FROM jobs
    WHERE fit_score >= 7
    ORDER BY fit_score DESC, title
""").fetchall()

print(f"Score 7+ jobs: {len(rows)}\n")
for r in rows:
    apply = "yes" if r["application_url"] else "no"
    resume_path = r["tailored_resume_path"]
    cover_path = r["cover_letter_path"]
    resume_href = _local_file_href(resume_path)
    cover_href = _local_file_href(cover_path)
    print(f"[{r['fit_score']}] {r['title'][:50]}")
    print(f"  site: {r['site']}")
    print(f"  apply_url: {apply}")
    print(f"  resume_db: {resume_path or 'NULL'}")
    print(f"  resume_link: {resume_href or 'MISSING'}")
    if resume_path:
        p = Path(resume_path)
        pdf = p.with_suffix(".pdf")
        print(f"  resume_txt_exists: {p.is_file()}, pdf_exists: {pdf.is_file()}")
    print(f"  cover_db: {cover_path or 'NULL'}")
    print(f"  cover_link: {cover_href or 'MISSING'}")
    print()
