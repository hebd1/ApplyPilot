"""Quick test: resume fits on one page."""
from pathlib import Path

from applypilot.scoring.pdf import _count_pdf_pages, render_resume_pdf_one_page

txt_files = sorted(Path.home().glob(".applypilot/tailored_resumes/*.txt"))
if not txt_files:
    print("no resume txt files")
    raise SystemExit(0)

src = txt_files[0]
out = "/tmp/test_resume_1page.pdf"
render_resume_pdf_one_page(src.read_text(encoding="utf-8"), out)
print(src.name, "->", _count_pdf_pages(out), "page(s)")
