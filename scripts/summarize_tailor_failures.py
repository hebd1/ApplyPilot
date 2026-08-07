"""Summarize tailor validation failures from REPORT.json files."""
import json
from collections import Counter
from pathlib import Path

reports = sorted(Path.home().joinpath(".applypilot/tailored_resumes").glob("*_REPORT.json"))
if not reports:
    print("No report files found")
    raise SystemExit(0)

status_counts = Counter()
error_counts = Counter()

for path in reports:
    data = json.loads(path.read_text(encoding="utf-8"))
    status = data.get("status", "?")
    status_counts[status] += 1
    if status != "approved" and status != "approved_with_judge_warning":
        for err in data.get("validator", {}).get("errors", []):
            error_counts[err] += 1

print("Status counts:")
for k, v in status_counts.most_common():
    print(f"  {k}: {v}")

print("\nTop validation error patterns:")
for k, v in error_counts.most_common(15):
    print(f"  {v}x  {k}")

print("\nSample failed reports:")
shown = 0
for path in reports:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("status") == "failed_validation":
        print(f"\n--- {path.name} ---")
        print(f"title: {data.get('job_title', '?')}")
        errs = data.get("validator", {}).get("errors", [])
        warns = data.get("validator", {}).get("warnings", [])
        for e in errs[:8]:
            print(f"  ERROR: {e}")
        for w in warns[:3]:
            print(f"  WARN: {w}")
        shown += 1
        if shown >= 3:
            break
