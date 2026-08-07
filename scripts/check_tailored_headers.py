"""Print experience headers from tailored resume files."""
from pathlib import Path

tailored = Path.home() / ".applypilot" / "tailored_resumes"
files = sorted(tailored.glob("*.txt"))
print(f"tailored count: {len(files)}")
for path in files:
    text = path.read_text(encoding="utf-8", errors="replace")
    print(f"\n--- {path.name} ---")
    for line in text.splitlines():
        low = line.lower()
        if " at " in low or "equifax" in low or "kount" in low:
            print(line.strip())
