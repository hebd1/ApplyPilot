"""Regenerate canonical reference PDF only."""
from pathlib import Path

from applypilot.config import load_env, load_profile
from applypilot.scoring.pdf import convert_to_pdf

load_env()
profile = load_profile()
txt = Path.home() / ".applypilot/tailored_resumes/CANONICAL_Senior_Cloud_Engineer.txt"
pdf = convert_to_pdf(txt, job={"title": "Senior Cloud Engineer", "site": "BMO"}, profile=profile, kind="resume")
print(pdf)
