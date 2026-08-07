"""Re-tailor and regenerate the BMO Senior Cloud Engineer reference resume."""
import json
import sqlite3
from pathlib import Path

from applypilot.config import TAILORED_DIR, load_env, load_profile
from applypilot.scoring.employment import validate_experience_company_lines
from applypilot.scoring.pdf import build_material_filename, convert_to_pdf
from applypilot.scoring.tailor import tailor_resume

load_env()
profile = load_profile()
base = (Path.home() / ".applypilot/resume.txt").read_text(encoding="utf-8")
conn = sqlite3.connect(Path.home() / ".applypilot/applypilot.db")
conn.row_factory = sqlite3.Row

row = conn.execute(
    "SELECT * FROM jobs WHERE title LIKE '%Senior Cloud Engineer%' AND site LIKE '%BMO%' "
    "ORDER BY fit_score DESC LIMIT 1"
).fetchone()
if not row:
    raise SystemExit("BMO Senior Cloud Engineer job not found in DB")

job = dict(row)
print(f"Job: {job['title']} @ {job['site']}")

tailored, report = tailor_resume(base, job, profile, validation_mode="normal")
company_errors = validate_experience_company_lines(tailored, profile)

txt_path = TAILORED_DIR / "BMO_Senior_Cloud_Engineer.txt"
txt_path.write_text(tailored, encoding="utf-8")

report_path = TAILORED_DIR / "BMO_Senior_Cloud_Engineer_REPORT.json"
report_path.write_text(json.dumps({**report, "company_line_errors": company_errors}, indent=2), encoding="utf-8")

# Canonical upload filename the user expects
pdf_name = build_material_filename(profile, job, "resume")
pdf_path = TAILORED_DIR / pdf_name
convert_to_pdf(txt_path, output_path=pdf_path, job=job, profile=profile, kind="resume")

conn.execute(
    "UPDATE jobs SET tailored_resume_path = ?, tailored_at = datetime('now') WHERE url = ?",
    (str(pdf_path), job["url"]),
)
conn.commit()

print(f"Status: {report['status']}")
print(f"PDF: {pdf_path}")
print(f"Company line errors: {company_errors or 'none'}")
print("\nExperience preview:")
in_exp = False
for line in tailored.splitlines():
    u = line.strip().upper()
    if u == "PROFESSIONAL EXPERIENCE":
        in_exp = True
        continue
    if in_exp and u == "EDUCATION":
        break
    if in_exp and line.strip().startswith("*"):
        print(f"  {line.strip()[:90]}...")
