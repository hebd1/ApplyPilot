"""Regenerate PDFs from source .txt files using Playwright (force overwrite)."""
import re
from pathlib import Path

from applypilot.config import COVER_LETTER_DIR, TAILORED_DIR, load_env, load_profile
from applypilot.database import get_connection, init_db
from applypilot.scoring.pdf import build_material_filename, convert_to_pdf

load_env()
init_db()
profile = load_profile()
conn = get_connection()


def _prefix(job: dict) -> str:
    safe_title = re.sub(r"[^\w\s-]", "", job["title"])[:50].strip().replace(" ", "_")
    safe_site = re.sub(r"[^\w\s-]", "", job["site"])[:20].strip().replace(" ", "_")
    return f"{safe_site}_{safe_title}"


rows = conn.execute("""
    SELECT url, title, site, tailored_resume_path, cover_letter_path
    FROM jobs
    WHERE tailored_resume_path IS NOT NULL OR cover_letter_path IS NOT NULL
    ORDER BY fit_score DESC
""").fetchall()

stats = {"resumes": 0, "cover_letters": 0, "errors": 0}

for row in rows:
    job = dict(row)
    prefix = _prefix(job)

    for kind, col, directory, suffix in [
        ("resume", "tailored_resume_path", TAILORED_DIR, ".txt"),
        ("cover", "cover_letter_path", COVER_LETTER_DIR, "_CL.txt"),
    ]:
        txt_path = directory / f"{prefix}{suffix}"
        if not txt_path.is_file():
            continue
        out_path = directory / build_material_filename(profile, job, kind)
        try:
            pdf_path = convert_to_pdf(
                txt_path, output_path=out_path, job=job, profile=profile, kind=kind,
            )
            conn.execute(f"UPDATE jobs SET {col} = ? WHERE url = ?", (str(pdf_path), job["url"]))
            stats["resumes" if kind == "resume" else "cover_letters"] += 1
            print(f"OK {kind}: {pdf_path.name} ({pdf_path.stat().st_size} bytes)")
        except Exception as exc:
            stats["errors"] += 1
            print(f"FAIL {kind} {job.get('title')}: {exc}")

conn.commit()
print(stats)
