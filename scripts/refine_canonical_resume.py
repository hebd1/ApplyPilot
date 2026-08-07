"""Re-tailor one job as the canonical resume template and regenerate its PDF."""
import json
import sqlite3
from pathlib import Path

from applypilot.config import TAILORED_DIR, load_env, load_profile
from applypilot.database import get_connection
from applypilot.scoring.employment import validate_experience_company_lines
from applypilot.scoring.pdf import build_html, convert_to_pdf, parse_resume, render_resume_pdf_one_page
from applypilot.scoring.tailor import tailor_resume

CANONICAL_TITLE = "Senior Cloud Engineer"
CANONICAL_SITE = "BMO"

load_env()
profile = load_profile()
resume_text = Path.home() / ".applypilot" / "resume.txt"
base = resume_text.read_text(encoding="utf-8")

conn = get_connection()
row = conn.execute(
    "SELECT * FROM jobs WHERE title LIKE ? AND site LIKE ? AND fit_score >= 7 "
    "ORDER BY fit_score DESC LIMIT 1",
    (f"%{CANONICAL_TITLE}%", f"%{CANONICAL_SITE}%"),
).fetchone()
if not row:
    row = conn.execute(
        "SELECT * FROM jobs WHERE fit_score >= 7 ORDER BY fit_score DESC LIMIT 1"
    ).fetchone()
if not row:
    raise SystemExit("No eligible job found")

job = dict(row)
print(f"==> Canonical job: {job['title']} @ {job['site']}")

tailored, report = tailor_resume(base, job, profile, validation_mode="normal")
errors = validate_experience_company_lines(tailored, profile)
if errors:
    print("Company line validation:", errors)

safe_title = job["title"].replace(" ", "_")[:50]
prefix = f"CANONICAL_{safe_title}"
txt_path = TAILORED_DIR / f"{prefix}.txt"
txt_path.write_text(tailored, encoding="utf-8")

report_path = TAILORED_DIR / f"{prefix}_REPORT.json"
report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

html = build_html(parse_resume(tailored))
html_lower = html.lower()
assert "equifax" in html_lower and "kount" in html_lower, "Employers missing from rendered HTML"

pdf_path = convert_to_pdf(txt_path, job=job, profile=profile, kind="resume")
pdf_path = convert_to_pdf(txt_path, job=job, profile=profile, kind="resume")
conn.execute(
    "UPDATE jobs SET tailored_resume_path = ? WHERE url = ?",
    (str(pdf_path), job["url"]),
)
conn.commit()
print(f"==> Status: {report['status']}")
print(f"==> Text: {txt_path}")
print(f"==> PDF:  {pdf_path}")
print("==> Experience header preview:")
in_exp = False
for line in tailored.splitlines():
    u = line.strip().upper()
    if u == "PROFESSIONAL EXPERIENCE":
        in_exp = True
        continue
    if in_exp and u == "EDUCATION":
        break
    if in_exp and line.strip():
        print(f"    {line}")
