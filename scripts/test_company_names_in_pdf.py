"""Verify PDF HTML includes employer names on company header rows."""
import sys
from pathlib import Path

from applypilot.config import load_profile
from applypilot.scoring.pdf import build_html, parse_resume, render_resume_pdf_one_page

profile = load_profile()
tailored = Path.home() / ".applypilot" / "tailored_resumes"
sample = next(p for p in tailored.glob("*.txt") if not p.name.endswith("_JOB.txt"))

text = sample.read_text(encoding="utf-8")
parsed = parse_resume(text)
html = build_html(parsed)

for employer in ("Equifax", "Kount", "CHPC"):
  if employer.lower() not in html.lower():
    print(f"FAIL: {employer} missing from HTML for {sample.name}")
    sys.exit(1)

out = Path("/tmp/canonical_resume_test.pdf")
render_resume_pdf_one_page(text, str(out))
print(f"OK: {sample.name} — employers present in HTML, PDF -> {out}")
