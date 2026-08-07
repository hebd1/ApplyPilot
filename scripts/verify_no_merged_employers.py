"""Fail if any tailored resume merges Kount and Equifax."""
import re
import sys
from pathlib import Path

from applypilot.scoring.employment import is_merged_company_header

tailored = Path.home() / ".applypilot" / "tailored_resumes"
merged_re = re.compile(r"kount.{0,40}equifax|equifax.{0,40}kount", re.I)
bad = []
for path in sorted(tailored.glob("*.txt")):
    if path.name.endswith("_JOB.txt"):
        continue
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if " at " in line.lower() and (is_merged_company_header(line) or merged_re.search(line)):
            bad.append((path.name, line.strip()))

if bad:
    print("MERGED HEADERS FOUND:")
    for name, line in bad:
        print(f"  {name}: {line}")
    sys.exit(1)

print(f"OK: {len(list(tailored.glob('*.txt')))} files, no merged employer headers")
