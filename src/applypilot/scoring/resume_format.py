"""Shared resume text layout matching the user's canonical resume format."""

from __future__ import annotations

import re
from typing import Any

from applypilot.scoring.employment import canonical_company_name, get_employment_history

# Section header aliases (canonical uppercase keys used internally by pdf.py)
SECTION_ALIASES: dict[str, str] = {
    "PROFESSIONAL SUMMARY": "SUMMARY",
    "PROFILE": "SUMMARY",
    "PROFESSIONAL EXPERIENCE": "EXPERIENCE",
    "WORK EXPERIENCE": "EXPERIENCE",
    "SELECTED PROJECT EXPERIENCE": "PROJECTS",
    "ADDITIONAL INFORMATION": "ADDITIONAL",
}

_COMPANY_LOCATION_RE = re.compile(r"^(.+?)\s{2,}(.+)$")
_ROLE_DATES_RE = re.compile(r"^(.+?)\s{2,}(.+)$")
_LOCATION_RE = re.compile(r".+,\s*[A-Z]{2}\s*$")
_AT_COMPANY_RE = re.compile(r"^(.+?)\s+at\s+(.+)$", re.IGNORECASE)


def normalize_section_name(name: str) -> str:
    upper = (name or "").strip().upper()
    return SECTION_ALIASES.get(upper, upper)


def format_contact_line(profile: dict) -> str:
    """Location • email • phone on one line (matches ELI_HEBDON_RESUME_2026).

    ``resume_facts.contact_line`` (the playbook's fixed line) wins when set.
    """
    fixed = (profile.get("resume_facts", {}) or {}).get("contact_line", "")
    if fixed:
        return str(fixed).strip()
    personal = profile.get("personal", {})
    city = personal.get("city", "").strip()
    state = personal.get("province_state", "").strip()
    postal = personal.get("postal_code", "").strip()
    location = ", ".join(p for p in (city, f"{state} {postal}".strip()) if p)
    location = re.sub(r"\s+", " ", location).strip()

    parts: list[str] = []
    if location:
        parts.append(location)
    if personal.get("email"):
        parts.append(personal["email"])
    phone = personal.get("phone", "")
    if phone:
        digits = re.sub(r"\D", "", phone)
        if len(digits) == 10:
            phone = f"+ 1 ({digits[:3]}) {digits[3:6]}-{digits[6:]}"
        parts.append(phone)
    return " • ".join(parts)


def _lookup_employment(profile: dict, company: str) -> dict[str, str]:
    """Return {location, dates} hints from profile employment_history."""
    company_l = company.lower()
    for row in get_employment_history(profile):
        if row.get("company", "").lower() in company_l or company_l in row.get("company", "").lower():
            subtitle = row.get("subtitle", "")
            location, dates = "", subtitle
            if "|" in subtitle:
                location, dates = [p.strip() for p in subtitle.split("|", 1)]
            return {"location": location, "dates": dates}
    return {"location": "", "dates": ""}


def parse_title_at_company(header: str) -> tuple[str, str]:
    match = _AT_COMPANY_RE.match(header.strip())
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return header.strip(), ""


def parse_subtitle(subtitle: str) -> tuple[str, str]:
    """Split 'Tech | Dates' or 'Location | Dates' into (secondary, dates)."""
    if not subtitle:
        return "", ""
    if "|" in subtitle:
        left, right = [p.strip() for p in subtitle.split("|", 1)]
        if re.search(r"\d{4}", right) or re.search(r"present", right, re.I):
            return left, right
        return left, right
    if re.search(r"\d{4}|present", subtitle, re.I):
        return "", subtitle
    return subtitle, ""


def format_spread_line(left: str, right: str, width: int = 78) -> str:
    """Two-column plain-text row: left label, right detail."""
    left = left.strip()
    right = right.strip()
    if not right:
        return left
    pad = max(2, width - len(left) - len(right))
    return f"{left}{' ' * pad}{right}"


def parsed_experience_entry_to_lines(entry: dict[str, Any]) -> list[str]:
    """Rebuild spread lines from a parsed experience entry (for PDF compaction)."""
    company = str(entry.get("company", "")).strip()
    location = str(entry.get("location", "")).strip()
    role = str(entry.get("role", "")).strip()
    dates = str(entry.get("dates", "")).strip() or str(entry.get("subtitle", "")).strip()

    if not role:
        role = str(entry.get("title", "")).strip()
    if role == company:
        role = ""

    lines: list[str] = []
    if company:
        display_company = company.upper() if company.isupper() or len(company) <= 40 else company
        lines.append(format_spread_line(display_company, location))
    if role:
        lines.append(format_spread_line(role, dates))
    elif entry.get("title") and entry.get("subtitle") and not company:
        lines.append(format_spread_line(str(entry["title"]), str(entry["subtitle"])))
    for bullet in entry.get("bullets", []):
        text = str(bullet).strip()
        if text:
            lines.append(f"* {text}")
    return lines


def experience_entry_to_lines(entry: dict[str, Any], profile: dict) -> list[str]:
    """Render one experience JSON entry in canonical resume layout."""
    company = str(entry.get("company", "")).strip()
    location = str(entry.get("location", "")).strip()
    title = str(entry.get("title", "")).strip()
    dates = str(entry.get("dates", "")).strip()
    header = str(entry.get("header", "")).strip()
    subtitle = str(entry.get("subtitle", "")).strip()

    if not company and header:
        title, company = parse_title_at_company(header)
    if subtitle:
        secondary, parsed_dates = parse_subtitle(subtitle)
        if parsed_dates and not dates:
            dates = parsed_dates
        if secondary and not location and _LOCATION_RE.match(secondary):
            location = secondary

    if company:
        company = canonical_company_name(company, profile)
        hints = _lookup_employment(profile, company)
        location = location or hints.get("location", "")
        dates = dates or hints.get("dates", "")
    elif title:
        for row in get_employment_history(profile):
            if row.get("title", "").lower() == title.lower():
                company = row.get("company", "")
                hints = _lookup_employment(profile, company)
                location = location or hints.get("location", "")
                dates = dates or hints.get("dates", "")
                break

    lines: list[str] = []
    if company:
        lines.append(format_spread_line(company.upper(), location))
    if title:
        lines.append(format_spread_line(title, dates))
    for bullet in entry.get("bullets", []):
        text = str(bullet).strip()
        if text:
            lines.append(f"* {text}")
    return lines


def education_to_lines(education: Any, profile: dict) -> list[str]:
    """Render education block from dict or legacy string."""
    facts = profile.get("resume_facts", {})
    details = facts.get("education_details") or {}

    if isinstance(education, dict):
        school = education.get("school") or details.get("school") or facts.get("preserved_school", "")
        location = education.get("location") or details.get("location", "")
        degree = education.get("degree") or details.get("degree", "")
        year = str(education.get("year") or details.get("year", "")).strip()
        highlights = education.get("highlights") or details.get("highlights") or []
    else:
        school = facts.get("preserved_school", "")
        location = details.get("location", "")
        degree = str(education or profile.get("experience", {}).get("education_level", ""))
        year = str(details.get("year", ""))
        highlights = details.get("highlights") or []

    lines: list[str] = []
    if school:
        lines.append(format_spread_line(school.upper(), location))
    degree_line = degree
    if year and year not in degree_line:
        degree_line = format_spread_line(degree, year) if degree else year
    if degree_line:
        lines.append(degree_line)
    for item in highlights:
        text = str(item).strip()
        if text:
            lines.append(f"* {text}")
    return lines


def assemble_resume_text(data: dict[str, Any], profile: dict) -> str:
    """Convert tailored JSON to plain text matching ELI_HEBDON_RESUME_2026 layout."""
    from applypilot.scoring.validator import sanitize_text

    personal = profile.get("personal", {})
    lines: list[str] = []

    lines.append(personal.get("full_name", ""))
    lines.append(sanitize_text(data.get("title", "Software Engineer")))
    lines.append(format_contact_line(profile))
    lines.append("")

    lines.append("PROFESSIONAL SUMMARY")
    lines.append("")
    lines.append(sanitize_text(data.get("summary", "")))
    lines.append("")

    lines.append("TECHNICAL SKILLS")
    skills = data.get("skills", {})
    if isinstance(skills, dict):
        for cat, val in skills.items():
            lines.append(f"* {cat}: {sanitize_text(str(val))}")
    lines.append("")

    lines.append("PROFESSIONAL EXPERIENCE")
    lines.append("")
    for entry in data.get("experience", []):
        if isinstance(entry, dict):
            lines.extend(experience_entry_to_lines(entry, profile))
            lines.append("")

    projects = data.get("projects")
    if not projects:
        projects = profile.get("resume_facts", {}).get("personal_projects") or []
    if isinstance(projects, list) and projects:
        lines.append("PROJECTS")
        lines.append("")
        for entry in projects:
            if isinstance(entry, dict):
                name = sanitize_text(str(entry.get("name") or entry.get("header") or "")).strip()
                desc = sanitize_text(
                    str(entry.get("description") or entry.get("summary") or "")
                ).strip()
                bullets = entry.get("bullets") or []
                if name and desc:
                    lines.append(f"* {name}: {desc}")
                elif name:
                    lines.append(f"* {name}")
                elif desc:
                    lines.append(f"* {desc}")
                for bullet in bullets:
                    text = sanitize_text(str(bullet)).strip()
                    if text:
                        lines.append(f"* {text}")
            elif str(entry).strip():
                lines.append(f"* {sanitize_text(str(entry).strip())}")
        lines.append("")

    lines.append("EDUCATION")
    lines.append("")
    lines.extend(education_to_lines(data.get("education"), profile))
    lines.append("")

    extra = data.get("additional_information")
    if extra is None:
        extra = profile.get("resume_facts", {}).get("additional_information", [])
    if isinstance(extra, list) and extra:
        lines.append("ADDITIONAL INFORMATION")
        lines.append("")
        combined = ", ".join(sanitize_text(str(item)) for item in extra if str(item).strip())
        if combined:
            lines.append(f"* {combined}")
    elif isinstance(extra, str) and extra.strip():
        lines.append("ADDITIONAL INFORMATION")
        lines.append("")
        lines.append(f"* {sanitize_text(extra)}")

    return "\n".join(lines).strip() + "\n"


def _is_bullet_line(line: str) -> bool:
    return line.startswith("- ") or line.startswith("* ") or line.startswith("\u2022 ")


def _strip_bullet(line: str) -> str:
    return line[2:].strip() if len(line) > 2 else line.strip()


def repair_experience_layout(text: str, profile: dict) -> str:
    """Fix company rows where tech stack was mistaken for location."""
    history = get_employment_history(profile)
    company_names = [row.get("company", "").strip() for row in history if row.get("company")]
    lines = text.splitlines()
    out: list[str] = []
    for line in lines:
        if re.search(r"\s{2,}", line.strip()):
            spread_left, spread_right = re.split(r"\s{2,}", line.strip(), maxsplit=1)
            spread_right = spread_right.strip() if spread_right else ""
            spread_upper = spread_left.upper()
            matched = any(
                spread_upper == name.upper() or name.upper() in spread_upper
                for name in company_names
            )
            if matched and spread_right and not _LOCATION_RE.match(spread_right):
                hints = _lookup_employment(profile, spread_left)
                if hints.get("location"):
                    line = format_spread_line(spread_left, hints["location"])
        out.append(line)
    return "\n".join(out)


def convert_legacy_experience_text(text: str, profile: dict) -> str:
    """Rewrite 'Title at Company' experience blocks into tabular employer layout."""
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    in_experience = False

    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        upper = stripped.upper()

        if upper in ("EXPERIENCE", "PROFESSIONAL EXPERIENCE"):
            in_experience = True
            out.append("PROFESSIONAL EXPERIENCE")
            out.append("")
            i += 1
            continue

        if in_experience and upper in (
            "PROJECTS", "EDUCATION", "TECHNICAL SKILLS", "SUMMARY",
            "PROFESSIONAL SUMMARY", "ADDITIONAL INFORMATION", "SELECTED PROJECT EXPERIENCE",
        ):
            in_experience = False

        if in_experience and stripped and " at " in stripped and not _is_bullet_line(stripped):
            title, company = parse_title_at_company(stripped)
            subtitle = lines[i + 1].strip() if i + 1 < len(lines) else ""
            bullets: list[str] = []
            j = i + 2
            if subtitle and not _is_bullet_line(subtitle):
                j = i + 2
            else:
                subtitle = ""
                j = i + 1
            while j < len(lines):
                b = lines[j].strip()
                if not b:
                    j += 1
                    break
                if _is_bullet_line(b):
                    bullets.append(_strip_bullet(b))
                    j += 1
                    continue
                if " at " in b and not _is_bullet_line(b):
                    break
                if b.upper() in (
                    "PROJECTS", "EDUCATION", "TECHNICAL SKILLS", "SUMMARY",
                    "PROFESSIONAL SUMMARY", "ADDITIONAL INFORMATION",
                ):
                    break
                j += 1
                break

            entry = {"company": company, "title": title, "subtitle": subtitle, "bullets": bullets}
            out.extend(experience_entry_to_lines(entry, profile))
            out.append("")
            i = j
            continue

        if upper == "SUMMARY":
            out.append("PROFESSIONAL SUMMARY")
        elif upper == "EXPERIENCE":
            out.append("PROFESSIONAL EXPERIENCE")
            out.append("")
        else:
            out.append(raw)
        i += 1

    return repair_experience_layout("\n".join(out), profile)
