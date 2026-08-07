"""Dump HTML for BMO resume to inspect bullet rendering."""
from pathlib import Path

from applypilot.scoring.pdf import build_html, parse_resume

txt = Path.home() / ".applypilot/tailored_resumes/BMO_Senior_Cloud_Engineer.txt"
text = txt.read_text(encoding="utf-8")
html = build_html(parse_resume(text))
out = Path("/tmp/bmo_resume.html")
out.write_text(html, encoding="utf-8")
# Show bullet-related fragments
for tag in ("ul", "li", "extra-row", "project-title", "resume-bullets"):
    count = html.count(f"<{tag}")
    print(f"{tag}: {count}")
print(f"written {out}")
