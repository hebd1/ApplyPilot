"""Employment history helpers for resume tailoring validation."""

from __future__ import annotations

import re

# Patterns that indicate two employers were merged into one header.
_MERGED_COMPANY_RE = re.compile(
    r"kount.{0,40}equifax|equifax.{0,40}kount|an equifax company|\(equifax\)",
    re.IGNORECASE,
)


def get_employment_history(profile: dict) -> list[dict]:
    """Return canonical employment rows from profile resume_facts."""
    facts = profile.get("resume_facts", {})
    history = facts.get("employment_history")
    if isinstance(history, list) and history:
        return history
    return _employment_from_preserved_companies(facts)


def _employment_from_preserved_companies(facts: dict) -> list[dict]:
    """Fallback when employment_history is not set."""
    companies = facts.get("preserved_companies", [])
    return [{"company": c, "title": "", "subtitle": ""} for c in companies]


def format_employment_for_prompt(profile: dict) -> str:
    """Build prompt block listing each employer as a separate experience entry."""
    lines: list[str] = []
    for row in get_employment_history(profile):
        company = row.get("company", "").strip()
        title = row.get("title", "").strip()
        subtitle = row.get("subtitle", "").strip()
        if title and subtitle:
            lines.append(f"- {title} at {company} | {subtitle}")
        elif title:
            lines.append(f"- {title} at {company}")
        else:
            lines.append(f"- {company}")
    return "\n".join(lines)


def is_merged_company_header(header: str) -> bool:
    """True when header combines Kount and Equifax (or similar) into one employer."""
    return bool(_MERGED_COMPANY_RE.search(header or ""))


def _company_aliases(company: str) -> set[str]:
    """Return lowercase aliases for a company name (full + parenthetical abbr)."""
    aliases = {company.lower().strip()}
    match = re.search(r"\(([^)]+)\)", company)
    if match:
        aliases.add(match.group(1).lower().strip())
    # Strip parenthetical for base name matching
    base = re.sub(r"\s*\([^)]*\)\s*", " ", company).strip().lower()
    if base:
        aliases.add(base)
    return {a for a in aliases if a}


def canonical_company_name(company: str, profile: dict) -> str:
    """Map aliases (e.g. CHPC) to the full employment_history company string."""
    company_l = (company or "").lower().strip()
    if not company_l:
        return company
    for row in get_employment_history(profile):
        canonical = (row.get("company") or "").strip()
        if not canonical:
            continue
        if company_l in _company_aliases(canonical):
            return canonical
    return company


def company_in_header(company: str, header: str) -> bool:
    """Check if a canonical company name appears in an experience header."""
    if not company or not header:
        return False
    if is_merged_company_header(header):
        return False
    header_l = header.lower()
    return any(alias in header_l for alias in _company_aliases(company))


def company_in_entry(company: str, entry: dict) -> bool:
    """Check if a canonical company name appears in an experience entry."""
    if not company or not isinstance(entry, dict):
        return False
    explicit = str(entry.get("company", "")).strip()
    header = str(entry.get("header", "")).strip()
    if explicit:
        explicit_l = explicit.lower()
        aliases = _company_aliases(company)
        if any(a in explicit_l or explicit_l in a for a in aliases):
            return True
    return company_in_header(company, header)


def validate_employment_structure(data: dict, profile: dict) -> list[str]:
    """Validate experience entries use separate employers (no Kount+Equifax merge)."""
    errors: list[str] = []
    experience = data.get("experience")
    if not isinstance(experience, list):
        return ["experience must be a list"]

    for entry in experience:
        if not isinstance(entry, dict):
            continue
        header = str(entry.get("header", ""))
        company = str(entry.get("company", ""))
        label = company or header
        if is_merged_company_header(label) or is_merged_company_header(header):
            errors.append(
                "Merged employer in experience entry "
                f"('{label}'). List Kount Inc and Equifax as separate entries."
            )

    for row in get_employment_history(profile):
        company = row.get("company", "").strip()
        if not company:
            continue
        matching = [e for e in experience if isinstance(e, dict) and company_in_entry(company, e)]
        if not matching:
            errors.append(f"Missing separate experience entry for employer: {company}")

    return errors


def validate_experience_company_lines(text: str, profile: dict) -> list[str]:
    """Ensure each employer appears on its own company header line in experience."""
    errors: list[str] = []
    in_experience = False
    company_lines: list[str] = []

    for line in text.split("\n"):
        stripped = line.strip()
        upper = stripped.upper()
        if upper in ("EXPERIENCE", "PROFESSIONAL EXPERIENCE"):
            in_experience = True
            continue
        if in_experience and upper in (
            "EDUCATION", "TECHNICAL SKILLS", "SUMMARY", "PROFESSIONAL SUMMARY",
            "ADDITIONAL INFORMATION", "PROJECTS", "SELECTED PROJECT EXPERIENCE",
        ):
            break
        if not in_experience or not stripped or stripped.startswith(("* ", "- ", "\u2022 ")):
            continue
        left, _ = stripped, ""
        if re.search(r"\s{2,}", stripped):
            left = re.split(r"\s{2,}", stripped, maxsplit=1)[0].strip()
        company_lines.append(left.lower())

    for row in get_employment_history(profile):
        company = row.get("company", "").strip()
        if not company:
            continue
        aliases = _company_aliases(company)
        found = any(
            any(a in line or line in a for a in aliases)
            for line in company_lines
        )
        if not found:
            errors.append(
                f"Employer '{company}' must appear on its own company header line in experience"
            )
    return errors


def normalize_experience_entries(data: dict, profile: dict) -> dict:
    """Normalize experience[] to company/location/title/dates fields."""
    experience = data.get("experience")
    if not isinstance(experience, list):
        return data

    history = get_employment_history(profile)
    company_by_title: dict[str, str] = {}
    for row in history:
        title = (row.get("title") or "").strip().lower()
        company = (row.get("company") or "").strip()
        if title and company:
            company_by_title[title] = company

    for entry in experience:
        if not isinstance(entry, dict):
            continue
        header = str(entry.get("header", "")).strip()
        if header and not entry.get("company"):
            title, company = _parse_title_at_company(header)
            entry.setdefault("title", title)
            entry.setdefault("company", company)
        company = str(entry.get("company", "")).strip()
        if is_merged_company_header(company) or is_merged_company_header(header):
            title = str(entry.get("title", "")).strip()
            if not title and header:
                title, _ = _parse_title_at_company(header)
            canonical = company_by_title.get(title.lower())
            if canonical:
                entry["company"] = canonical
                entry.pop("header", None)
        company = str(entry.get("company", "")).strip()
        if company:
            entry["company"] = canonical_company_name(company, profile)
        subtitle = str(entry.get("subtitle", "")).strip()
        if subtitle:
            if "|" in subtitle:
                left, right = [p.strip() for p in subtitle.split("|", 1)]
                if re.search(r"\d{4}|present", right, re.I):
                    if re.search(r",\s*[A-Z]{2}", left):
                        entry.setdefault("location", left)
                    entry.setdefault("dates", right)
                elif not entry.get("dates"):
                    entry.setdefault("dates", right)
            elif re.search(r"\d{4}|present", subtitle, re.I):
                entry.setdefault("dates", subtitle)
        hints = _lookup_row(profile, str(entry.get("company", "")))
        entry.setdefault("location", hints.get("location", ""))
        entry.setdefault("dates", entry.get("dates") or hints.get("dates", ""))
    return data


def _parse_title_at_company(header: str) -> tuple[str, str]:
    match = re.match(r"^(.+?)\s+at\s+(.+)$", header.strip(), re.I)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return header.strip(), ""


def _lookup_row(profile: dict, company: str) -> dict[str, str]:
    company_l = company.lower()
    for row in get_employment_history(profile):
        row_company = row.get("company", "")
        if row_company.lower() in company_l or company_l in row_company.lower():
            subtitle = row.get("subtitle", "")
            location, dates = "", subtitle
            if "|" in subtitle:
                location, dates = [p.strip() for p in subtitle.split("|", 1)]
            return {"location": location, "dates": dates}
    return {"location": "", "dates": ""}


def normalize_experience_headers(data: dict, profile: dict) -> dict:
    """Back-compat wrapper — normalize all experience entry shapes."""
    return normalize_experience_entries(data, profile)
