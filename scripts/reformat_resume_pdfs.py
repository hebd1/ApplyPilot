"""Reformat tailored resume text and regenerate PDFs with canonical layout."""
from pathlib import Path

from applypilot.config import load_env, load_profile
from applypilot.database import get_connection
from applypilot.scoring.pdf import convert_to_pdf
from applypilot.scoring.resume_format import (
    convert_legacy_experience_text,
    education_to_lines,
    format_contact_line,
    repair_experience_layout,
)


def _normalize_additional_block(text: str, profile: dict) -> str:
    """Merge multiple additional-info bullets into one line (matches reference resume)."""
    facts = profile.get("resume_facts", {})
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        if lines[i].strip().upper() != "ADDITIONAL INFORMATION":
            out.append(lines[i])
            i += 1
            continue
        out.append(lines[i])
        out.append("")
        i += 1
        extra = facts.get("additional_information", "")
        if isinstance(extra, list):
            extra = ", ".join(str(x) for x in extra if str(x).strip())
        if str(extra).strip():
            out.append(f"* {str(extra).strip()}")
        break  # Additional Information is always the final section
    result = "\n".join(out).strip()
    return result + "\n" if result else text


load_env()
profile = load_profile()
facts = profile.get("resume_facts", {})
tailored_dir = Path.home() / ".applypilot" / "tailored_resumes"
conn = get_connection()

updated = 0
pdfs = 0
errors = 0

for path in sorted(tailored_dir.glob("*.txt")):
    if path.name.endswith("_JOB.txt"):
        continue
    text = path.read_text(encoding="utf-8")
    new_text = convert_legacy_experience_text(text, profile)
    new_text = repair_experience_layout(new_text, profile)
    new_text = _normalize_additional_block(new_text, profile)

    # Patch sparse education / additional sections from profile defaults
    lower = new_text.lower()
    if "education" in lower and "utah flagship" not in lower:
        lines = new_text.rstrip().split("\n")
        if "EDUCATION" not in new_text.upper():
            lines.extend(["", "EDUCATION", ""])
        else:
            # replace single-line education with full block
            out: list[str] = []
            skip_edu = False
            for line in lines:
                upper = line.strip().upper()
                if upper == "EDUCATION":
                    out.append(line)
                    out.append("")
                    out.extend(education_to_lines({}, profile))
                    skip_edu = True
                    continue
                if skip_edu:
                    if upper in ("ADDITIONAL INFORMATION", "TECHNICAL SKILLS", "PROFESSIONAL EXPERIENCE"):
                        skip_edu = False
                        out.append(line)
                    continue
                out.append(line)
            lines = out
        new_text = "\n".join(lines).strip() + "\n"

    extra = facts.get("additional_information") or []
    if extra and "additional information" not in lower:
        combined = extra if isinstance(extra, str) else ", ".join(str(x) for x in extra)
        new_text = new_text.rstrip() + f"\n\nADDITIONAL INFORMATION\n\n* {combined}\n"

    # Ensure header contact line matches canonical format
    header_lines = new_text.splitlines()
    if len(header_lines) >= 2:
        header_lines[2:3] = [format_contact_line(profile)]
        new_text = "\n".join(header_lines)

    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
        updated += 1

    row = conn.execute(
        "SELECT url, title, site FROM jobs WHERE tailored_resume_path LIKE ?",
        (f"%{path.name}",),
    ).fetchone()
    job = dict(row) if row else {"title": path.stem, "site": "unknown"}
    try:
        pdf_path = convert_to_pdf(path, job=job, profile=profile, kind="resume")
        conn.execute(
            "UPDATE jobs SET tailored_resume_path = ? WHERE tailored_resume_path LIKE ?",
            (str(pdf_path), f"%{path.name}",),
        )
        pdfs += 1
    except Exception as exc:
        errors += 1
        print(f"ERROR {path.name}: {exc}")

conn.commit()
print({"text_updated": updated, "pdfs": pdfs, "errors": errors})
