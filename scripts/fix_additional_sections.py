"""Fix additional-information section in all tailored resume text files."""
from pathlib import Path

from applypilot.config import load_profile
from applypilot.scoring.resume_format import normalize_section_name

profile = load_profile()
facts = profile.get("resume_facts", {})
extra = facts.get("additional_information", "")
if isinstance(extra, list):
    extra = ", ".join(str(x) for x in extra if str(x).strip())

tailored = Path.home() / ".applypilot" / "tailored_resumes"
fixed = 0
for path in sorted(tailored.glob("*.txt")):
    if path.name.endswith("_JOB.txt"):
        continue
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        if normalize_section_name(lines[i].strip()) != "ADDITIONAL":
            out.append(lines[i])
            i += 1
            continue
        out.append(lines[i])
        out.append("")
        if extra:
            out.append(f"* {extra}")
        break
    new_text = "\n".join(out).strip() + "\n"
    if new_text != path.read_text(encoding="utf-8"):
        path.write_text(new_text, encoding="utf-8")
        fixed += 1

print(f"fixed {fixed} files")
