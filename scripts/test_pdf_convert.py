from pathlib import Path

from applypilot.scoring.pdf import convert_to_pdf

for label, p in [
    ("resume", Path.home() / ".applypilot/tailored_resumes/indeed_Full_Stack_Developer.txt"),
    ("cover", Path.home() / ".applypilot/cover_letters/indeed_Full_Stack_Developer_CL.txt"),
]:
    print(f"=== {label} ===")
    try:
        out = convert_to_pdf(p)
        print("OK", out, out.stat().st_size)
    except Exception as e:
        print("FAIL", type(e).__name__, e)
