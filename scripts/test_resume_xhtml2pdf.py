from pathlib import Path

from applypilot.scoring.pdf import build_html, parse_resume

text = Path.home().joinpath(
    ".applypilot/tailored_resumes/indeed_Full_Stack_Developer.txt"
).read_text(encoding="utf-8")
html = build_html(parse_resume(text))

from xhtml2pdf import pisa

out = Path("/tmp/resume_test.pdf")
with out.open("wb") as f:
    status = pisa.CreatePDF(html, dest=f)
print("err", status.err, "size", out.stat().st_size if out.exists() else 0)
