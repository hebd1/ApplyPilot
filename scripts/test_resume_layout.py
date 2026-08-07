"""Smoke test resume PDF layout against ELI_HEBDON_RESUME_2026."""
from pathlib import Path

from applypilot.scoring.pdf import _count_pdf_pages, parse_resume, render_resume_pdf_one_page

SOURCE = Path("/mnt/c/Users/elihe/Documents/Resumes/ELI_HEBDON_RESUME_2026.txt")
OUT = Path("/tmp/reference_resume_test.pdf")

text = SOURCE.read_text(encoding="utf-8")
parsed = parse_resume(text)
print("sections:", list(parsed["sections"].keys()))
render_resume_pdf_one_page(text, str(OUT))
print("reference pages:", _count_pdf_pages(str(OUT)))
