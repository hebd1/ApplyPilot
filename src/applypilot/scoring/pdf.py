"""Text-to-PDF conversion for tailored resumes and cover letters.

Parses the structured text resume format, renders via an HTML/CSS template,
and exports to PDF using headless Chromium via Playwright.
"""

import logging
import re
from html import escape
from pathlib import Path

from applypilot.config import load_profile
from applypilot.scoring.resume_format import (
    convert_legacy_experience_text,
    normalize_section_name,
    parsed_experience_entry_to_lines,
)

log = logging.getLogger(__name__)


# ── Resume Parser ────────────────────────────────────────────────────────

def parse_resume(text: str) -> dict:
    """Parse a structured text resume into sections.

    Expects a format with header lines (name, title, location, contact)
    followed by ALL-CAPS section headers (SUMMARY, TECHNICAL SKILLS, etc.).

    Args:
        text: Full resume text.

    Returns:
        {"name": str, "title": str, "location": str, "contact": str, "sections": dict}
    """
    lines = [line.rstrip() for line in text.strip().split("\n")]

    # Header: first lines before first section header
    header_lines: list[str] = []
    body_start = 0
    section_headers = {
        "SUMMARY", "PROFESSIONAL SUMMARY", "PROFILE",
        "TECHNICAL SKILLS", "SKILLS",
        "EXPERIENCE", "PROFESSIONAL EXPERIENCE", "WORK EXPERIENCE",
        "PROJECTS", "SELECTED PROJECT EXPERIENCE",
        "EDUCATION", "ADDITIONAL INFORMATION",
    }
    for i, line in enumerate(lines):
        if line.strip().upper() in section_headers:
            body_start = i
            break
        if line.strip():
            header_lines.append(line.strip())

    name = header_lines[0] if len(header_lines) > 0 else ""
    title = header_lines[1] if len(header_lines) > 1 else ""
    location = ""
    contact = ""
    if len(header_lines) > 2:
        third = header_lines[2]
        if "•" in third or "@" in third or "|" in third:
            contact = third.replace("|", "•")
        else:
            location = third
    if len(header_lines) > 3:
        contact = header_lines[3].replace("|", "•")

    # Split body into sections by ALL-CAPS headers
    sections: dict[str, str] = {}
    current_section: str | None = None
    current_lines: list[str] = []

    for line in lines[body_start:]:
        stripped = line.strip()
        # Detect section headers (all caps, no leading dash/bullet, longer than 3 chars)
        if (
            stripped
            and stripped == stripped.upper()
            and not stripped.startswith("-")
            and not stripped.startswith("*")
            and len(stripped) > 3
            and not stripped.startswith("\u2022")
        ):
            if current_section:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = normalize_section_name(stripped)
            current_lines = []
        else:
            current_lines.append(line)

    if current_section:
        sections[current_section] = "\n".join(current_lines).strip()

    return {
        "name": name,
        "title": title,
        "location": location,
        "contact": contact,
        "sections": sections,
    }


def parse_skills(text: str) -> list[tuple[str, str]]:
    """Parse skills section into (category, value) pairs."""
    skills: list[tuple[str, str]] = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith(("* ", "- ", "\u2022 ")):
            line = line[2:].strip()
        if ":" in line:
            cat, val = line.split(":", 1)
            skills.append((cat.strip(), val.strip()))
    return skills


def _is_bullet(line: str) -> bool:
    return line.startswith("- ") or line.startswith("* ") or line.startswith("\u2022 ")


def _bullet_text(line: str) -> str:
    return line[2:].strip()


def _split_spread_line(line: str) -> tuple[str, str]:
    """Split 'LEFT          RIGHT' on 2+ spaces."""
    parts = re.split(r"\s{2,}", line.strip(), maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return line.strip(), ""


def parse_entries(text: str, *, default_phase: str = "") -> list[dict]:
    """Parse experience/project/education entries from section text.

    ``default_phase="projects"`` when parsing a PROJECTS section body that has
    no inline header (bullets only, ``* Name: desc``).
    """
    entries: list[dict] = []
    lines = text.strip().split("\n")
    current: dict | None = None
    phase = default_phase

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.lower() in ("selected project experience", "projects", "personal projects", "key projects"):
            if current:
                entries.append(current)
                current = None
            phase = "projects"
            continue

        if _is_bullet(stripped):
            bullet = _bullet_text(stripped)
            if phase == "projects":
                # Support "* Name: description" personal-project lines from assemble_resume_text
                if ":" in bullet:
                    if current and (current.get("title") or current.get("bullets")):
                        entries.append(current)
                    name, _, desc = bullet.partition(":")
                    current = {
                        "title": name.strip() or bullet,
                        "subtitle": "",
                        "bullets": [desc.strip()] if desc.strip() else [],
                        "kind": "project",
                    }
                elif current is None:
                    current = {"title": bullet, "subtitle": "", "bullets": [], "kind": "project"}
                else:
                    current.setdefault("bullets", []).append(bullet)
            elif current is not None:
                current["bullets"].append(bullet)
            continue

        left, right = _split_spread_line(stripped)
        if current is None:
            current = {
                "title": left,
                "subtitle": right,
                "bullets": [],
                "company": left,
                "location": right,
                "role": "",
                "dates": "",
            }
            phase = "company"
            continue

        if phase == "company" and not current.get("role"):
            current["role"] = left
            current["dates"] = right
            phase = "role"
            continue

        if phase == "projects":
            if current and current.get("bullets"):
                entries.append(current)
            current = {"title": stripped, "subtitle": "", "bullets": [], "kind": "project"}
            continue

        if current and current.get("bullets"):
            entries.append(current)
        current = {
            "title": left,
            "subtitle": right,
            "bullets": [],
            "company": left,
            "location": right,
            "role": "",
            "dates": "",
        }
        phase = "company"

    if current:
        entries.append(current)
    return entries


# ── One-page compaction ──────────────────────────────────────────────────

_COMPACT_LIMITS: list[dict] = [
    # Never drop employers (max_exp stays high). Trim bullets / summary / projects only.
    {"max_exp": 99, "max_proj": 99, "max_bullets": 5, "max_summary": 999, "include_projects": True},
    {"max_exp": 99, "max_proj": 3, "max_bullets": 4, "max_summary": 500, "include_projects": True},
    {"max_exp": 99, "max_proj": 2, "max_bullets": 3, "max_summary": 350, "include_projects": True},
    {"max_exp": 99, "max_proj": 1, "max_bullets": 2, "max_summary": 250, "include_projects": True},
    {"max_exp": 99, "max_proj": 0, "max_bullets": 2, "max_summary": 200, "include_projects": False},
]


def _compact_resume(resume: dict, level: int) -> dict:
    """Return a copy of parsed resume trimmed for single-page PDF."""
    limits = _COMPACT_LIMITS[min(level, len(_COMPACT_LIMITS) - 1)]
    out = {
        "name": resume["name"],
        "title": resume["title"],
        "location": resume["location"],
        "contact": resume["contact"],
        "sections": dict(resume["sections"]),
        "_compact_level": level,
    }
    sections = out["sections"]
    if "SUMMARY" in sections:
        summary = sections["SUMMARY"].strip()
        if len(summary) > limits["max_summary"]:
            summary = summary[: limits["max_summary"]].rsplit(" ", 1)[0] + "."
        sections["SUMMARY"] = summary
    for section_key, max_key in (("EXPERIENCE", "max_exp"), ("PROJECTS", "max_proj")):
        if section_key not in sections:
            continue
        if section_key == "PROJECTS" and not limits["include_projects"]:
            del sections[section_key]
            continue
        entries = parse_entries(
            sections[section_key],
            default_phase="projects" if section_key == "PROJECTS" else "",
        )[: limits[max_key]]
        for entry in entries:
            entry["bullets"] = entry["bullets"][: limits["max_bullets"]]
        rebuilt: list[str] = []
        for entry in entries:
            rebuilt.extend(parsed_experience_entry_to_lines(entry))
            rebuilt.append("")
        sections[section_key] = "\n".join(rebuilt).strip()
    return out


def _count_pdf_pages(path: str) -> int:
    try:
        from pypdf import PdfReader
        return len(PdfReader(path).pages)
    except Exception:
        return 1


def _resume_css(compact_level: int, scale: float = 1.0) -> str:
    """CSS tuned for single-page letter resume matching ELI_HEBDON layout."""
    base_size = max(8.5, 10.0 - compact_level * 0.25) * scale
    name_size = max(16, 18 - compact_level) * scale
    margin_v = max(0.38, 0.48 - compact_level * 0.03)
    margin_h = max(0.55, 0.62 - compact_level * 0.02)
    return f"""
@page {{
    size: letter;
    margin: {margin_v}in {margin_h}in;
}}
* {{
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}}
body {{
    font-family: Calibri, 'Segoe UI', Arial, sans-serif;
    font-size: {base_size}pt;
    line-height: 1.32;
    color: #111;
}}
.header {{
    text-align: center;
    margin-bottom: 4px;
}}
.name {{
    font-size: {name_size}pt;
    font-weight: 700;
    letter-spacing: 0.3px;
}}
.title {{
    font-size: {base_size + 0.5}pt;
    font-weight: 600;
    margin-top: 1px;
}}
.contact {{
    font-size: {base_size - 0.3}pt;
    color: #333;
    margin-top: 1px;
}}
.section {{
    margin-top: {max(5, 8 - compact_level)}px;
}}
.section-title {{
    font-size: {base_size}pt;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    border-bottom: 1px solid #222;
    padding-bottom: 1px;
    margin-bottom: 3px;
}}
.summary {{
    font-size: {base_size}pt;
    color: #222;
    line-height: 1.3;
}}
.skill-row {{
    font-size: {base_size - 0.1}pt;
    margin: 0;
    line-height: 1.25;
}}
.skill-cat {{
    font-weight: 600;
}}
.entry {{
    margin-bottom: {max(3, 6 - compact_level)}px;
    break-inside: avoid;
}}
.spread-row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 12px;
    line-height: 1.2;
}}
.org {{
    font-weight: 700;
    text-transform: uppercase;
    font-size: {base_size}pt;
}}
.role {{
    font-weight: 600;
    font-size: {base_size}pt;
}}
.meta {{
    font-size: {base_size - 0.2}pt;
    color: #333;
    white-space: nowrap;
}}
.project-title {{
    font-weight: 600;
    font-size: {base_size - 0.1}pt;
    margin-top: 2px;
}}
ul.resume-bullets {{
    margin: 2px 0 0 16px;
    padding: 0;
    list-style-type: disc;
}}
ul.resume-bullets li {{
    font-size: {base_size - 0.05}pt;
    margin-bottom: 2px;
    line-height: 1.3;
    padding-left: 2px;
}}
ul {{
    margin: 2px 0 0 16px;
    padding: 0;
    list-style-type: disc;
}}
li {{
    font-size: {base_size - 0.05}pt;
    margin-bottom: 2px;
    line-height: 1.3;
}}
.edu-block {{
    font-size: {base_size}pt;
}}
"""


# ── HTML Template ────────────────────────────────────────────────────────

def _bullet_list_html(bullets: list[str]) -> str:
    """Uniform bullet list used across experience, education, and additional sections."""
    if not bullets:
        return ""
    items = "".join(f"<li>{escape(b)}</li>" for b in bullets if str(b).strip())
    return f'<ul class="resume-bullets">{items}</ul>'


def _render_experience_entries(entries: list[dict]) -> str:
    items = ""
    for e in entries:
        if e.get("kind") == "project":
            bullets = e.get("bullets", [])
            title = escape(e.get("title", ""))
            if bullets:
                items += f'<div class="project-title">{title}</div>{_bullet_list_html(bullets)}'
            elif title:
                items += f'<div class="project-title">{title}</div>'
            continue
        company = escape(e.get("company") or e.get("title", ""))
        location = escape(e.get("location", ""))
        role = escape(e.get("role") or e.get("title", ""))
        dates = escape(e.get("dates") or e.get("subtitle", ""))
        loc_html = f'<span class="meta">{location}</span>' if location else ""
        date_html = f'<span class="meta">{dates}</span>' if dates else ""
        items += (
            f'<div class="entry">'
            f'<div class="spread-row"><span class="org">{company}</span>{loc_html}</div>'
            f'<div class="spread-row"><span class="role">{role}</span>{date_html}</div>'
            f'{_bullet_list_html(e.get("bullets", []))}</div>'
        )
    return items


def _render_education_html(text: str) -> str:
    lines = [ln.strip() for ln in text.strip().split("\n") if ln.strip()]
    html_parts: list[str] = []
    bullet_buf: list[str] = []
    header_rows = 0

    def flush_bullets() -> None:
        nonlocal bullet_buf
        if bullet_buf:
            html_parts.append(_bullet_list_html(bullet_buf))
            bullet_buf = []

    for line in lines:
        if line.startswith(("* ", "- ", "\u2022 ")):
            bullet_buf.append(line[2:].strip())
            continue
        flush_bullets()
        left, right = _split_spread_line(line)
        # First spread row = school (uppercase org); second = degree (role style)
        if header_rows == 0:
            html_parts.append(
                f'<div class="spread-row"><span class="org">{escape(left)}</span>'
                f'<span class="meta">{escape(right)}</span></div>'
                if right
                else f'<div class="org">{escape(left)}</div>'
            )
        else:
            html_parts.append(
                f'<div class="spread-row"><span class="role">{escape(left)}</span>'
                f'<span class="meta">{escape(right)}</span></div>'
                if right
                else f'<div class="role">{escape(left)}</div>'
            )
        header_rows += 1
    flush_bullets()
    return f'<div class="edu-block">{"".join(html_parts)}</div>'


def _render_additional_html(text: str) -> str:
    bullets: list[str] = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith(("* ", "- ", "\u2022 ")):
            line = line[2:].strip()
        bullets.append(line)
    if len(bullets) > 1:
        bullets = [", ".join(bullets)]
    return _bullet_list_html(bullets)


def build_html(resume: dict, compact_level: int = 0, scale: float = 1.0) -> str:
    """Build professional resume HTML from parsed data.

    Args:
        resume: Parsed resume dict from parse_resume().
        compact_level: 0-3; higher values use tighter layout for one-page fit.

    Returns:
        Complete HTML string ready for PDF rendering.
    """
    compact_level = resume.get("_compact_level", compact_level)
    sections = resume["sections"]

    # Skills
    skills_html = ""
    if "TECHNICAL SKILLS" in sections:
        skills = parse_skills(sections["TECHNICAL SKILLS"])
        rows = ""
        for cat, val in skills:
            rows += f'<div class="skill-row"><span class="skill-cat">{escape(cat)}:</span> {escape(val)}</div>\n'
        skills_html = f'<div class="section"><div class="section-title">Technical Skills</div>{rows}</div>'

    # Experience (+ inline selected projects)
    exp_html = ""
    exp_key = "EXPERIENCE" if "EXPERIENCE" in sections else None
    if exp_key:
        entries = parse_entries(sections[exp_key])
        items = _render_experience_entries(entries)
        exp_html = (
            f'<div class="section"><div class="section-title">Professional Experience</div>{items}</div>'
        )

    # Standalone projects section (legacy tailored resumes)
    proj_html = ""
    if "PROJECTS" in sections and "Selected Project Experience" not in sections.get("EXPERIENCE", ""):
        entries = parse_entries(sections["PROJECTS"], default_phase="projects")
        items = _render_experience_entries(
            [{**e, "kind": "project"} for e in entries]
        )
        if items:
            proj_html = (
                f'<div class="section"><div class="section-title">Selected Project Experience</div>{items}</div>'
            )

    # Education
    edu_html = ""
    if "EDUCATION" in sections:
        edu_html = (
            f'<div class="section"><div class="section-title">Education</div>'
            f'{_render_education_html(sections["EDUCATION"])}</div>'
        )

    # Additional information
    extra_html = ""
    if "ADDITIONAL" in sections:
        extra_html = (
            f'<div class="section"><div class="section-title">Additional Information</div>'
            f'{_render_additional_html(sections["ADDITIONAL"])}</div>'
        )

    # Summary
    summary_html = ""
    summary_key = "SUMMARY" if "SUMMARY" in sections else None
    if summary_key:
        summary_html = (
            f'<div class="section"><div class="section-title">Professional Summary</div>'
            f'<div class="summary">{escape(sections[summary_key].strip())}</div></div>'
        )

    # Contact line parsing
    contact = resume["contact"]
    contact_html = escape(contact.replace("•", " | "))

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
{_resume_css(compact_level, scale)}
</style>
</head>
<body>
<div class="header">
    <div class="name">{escape(resume['name'])}</div>
    <div class="title">{escape(resume['title'])}</div>
    <div class="contact">{contact_html}</div>
</div>
{summary_html}
{skills_html}
{exp_html}
{proj_html}
{edu_html}
{extra_html}
</body>
</html>"""


_FILL_SCALES = (1.1, 1.16)


def render_resume_pdf_one_page(text: str, output_path: str) -> None:
    """Render resume PDF, compacting content until it fits on one page."""
    profile = load_profile()
    text = convert_legacy_experience_text(text, profile)
    parsed = parse_resume(text)
    for level in range(len(_COMPACT_LIMITS)):
        compact = _compact_resume(parsed, level)
        best_html = build_html(compact, compact_level=level, scale=1.0)
        render_pdf(best_html, output_path)
        pages = _count_pdf_pages(output_path)
        if pages > 1:
            log.debug("Resume PDF is %d pages at compact level %d; tightening", pages, level)
            continue
        for scale in _FILL_SCALES:
            trial_html = build_html(compact, compact_level=level, scale=scale)
            render_pdf(trial_html, output_path)
            if _count_pdf_pages(output_path) > 1:
                render_pdf(best_html, output_path)
                break
            best_html = trial_html
        else:
            render_pdf(best_html, output_path)
        if level > 0:
            log.info("Resume compacted to 1 page (level %d): %s", level, output_path)
        return
    log.warning("Resume may exceed 1 page after max compaction: %s", output_path)


# ── Naming & cover letter HTML ───────────────────────────────────────────

def _slugify(value: str, max_len: int = 40) -> str:
    """Turn arbitrary text into a safe filename component."""
    cleaned = re.sub(r"[^\w\s-]", "", value or "")
    cleaned = re.sub(r"\s+", "_", cleaned.strip())
    return cleaned[:max_len].strip("_") or "Document"


def build_material_filename(profile: dict, job: dict, kind: str) -> str:
    """Build an upload-ready PDF filename.

    Example: Hebdon_Full_Stack_Developer_Upstart_Resume.pdf
    """
    from applypilot.job_meta import display_company

    personal = profile.get("personal", {})
    full_name = personal.get("full_name", "Candidate")
    name_parts = full_name.split()
    name_part = _slugify(name_parts[-1] if name_parts else "Candidate", 30)
    title_part = _slugify(job.get("title", "Role"))
    company_part = _slugify(display_company(job), 25)
    suffix = "Resume" if kind == "resume" else "CoverLetter"
    return f"{name_part}_{title_part}_{company_part}_{suffix}.pdf"


def build_cover_letter_html(text: str, profile: dict, job: dict | None = None) -> str:
    """Build professional cover letter HTML with header, subject, and closing."""
    personal = profile.get("personal", {})
    full_name = personal.get("full_name", "")
    email = personal.get("email", "")
    phone = personal.get("phone", "")
    city = personal.get("city", "")
    state = personal.get("province_state", "")
    country = personal.get("country", "United States")

    location_line = ", ".join(p for p in (city, state) if p)
    contact_bits = [escape(x) for x in (email, phone) if x]
    contact_html = " | ".join(contact_bits)
    remote_line = f"Remote / {country}" if country else "Remote"

    # Parse letter body from LLM text
    body_text = text.strip()
    subject = ""
    if job:
        subject = f"Subject: {job.get('title', 'Application')}"
    closing_html = ""
    body_paras: list[str] = []

    lines = body_text.split("\n")
    idx = 0
    while idx < len(lines):
        line = lines[idx].strip()
        if line.lower().startswith("subject:"):
            subject = line
            idx += 1
            continue
        if line.lower().startswith("dear"):
            # Collect salutation + following paragraphs
            block_lines = [line]
            idx += 1
            while idx < len(lines):
                nxt = lines[idx].strip()
                if not nxt:
                    idx += 1
                    if block_lines and block_lines[-1]:
                        break
                    continue
                lower = nxt.lower()
                if lower.startswith(("warm regards", "sincerely", "best regards", "thank you")):
                    break
                block_lines.append(nxt)
                idx += 1
            para = " ".join(block_lines)
            if para:
                body_paras.append(para)
            continue
        lower = line.lower()
        if lower.startswith(("warm regards", "sincerely", "best regards")) or (
            full_name and line == full_name.strip()
        ):
            closing_lines = []
            while idx < len(lines):
                nxt = lines[idx].strip()
                if nxt:
                    closing_lines.append(nxt)
                idx += 1
            closing_html = "<br>".join(escape(x) for x in closing_lines)
            break
        if lower.startswith("thank you"):
            closing_lines = [line]
            idx += 1
            while idx < len(lines):
                nxt = lines[idx].strip()
                if not nxt:
                    idx += 1
                    continue
                lower_nxt = nxt.lower()
                if lower_nxt.startswith(("warm regards", "sincerely", "best regards")):
                    closing_lines.append(nxt)
                    idx += 1
                    while idx < len(lines):
                        tail = lines[idx].strip()
                        if tail:
                            closing_lines.append(tail)
                        idx += 1
                    break
                if full_name and nxt == full_name.strip():
                    closing_lines.append(nxt)
                    idx += 1
                    break
                closing_lines.append(nxt)
                idx += 1
            closing_html = "<br>".join(escape(x) for x in closing_lines)
            break
        if line:
            body_paras.append(line)
        idx += 1

    if not body_paras:
        blocks = [b.strip() for b in body_text.split("\n\n") if b.strip()]
        for block in blocks:
            if block.lower().startswith("subject:"):
                subject = block.split("\n", 1)[0]
                rest = block.split("\n", 1)[1] if "\n" in block else ""
                if rest.strip():
                    body_paras.append(rest.strip())
            elif not block.lower().startswith(("warm regards", "sincerely")):
                body_paras.append(block.replace("\n", " "))

    if not closing_html:
        closing_html = f"Warm regards,<br>{escape(full_name)}"

    subject_html = f'<div class="subject">{escape(subject)}</div>' if subject else ""
    body_html = ""
    for para in body_paras:
        body_html += f'<p class="letter-para">{escape(para)}</p>\n'

    header_location = f'<div class="header-line">{escape(location_line)} | {contact_html}</div>'
    header_remote = f'<div class="header-line">{escape(remote_line)}</div>'

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
@page {{
    size: letter;
    margin: 0.65in 0.75in;
}}
body {{
    font-family: Calibri, 'Segoe UI', Arial, sans-serif;
    font-size: 11pt;
    line-height: 1.45;
    color: #1a1a1a;
}}
.letter-header {{
    margin-bottom: 18px;
}}
.name {{
    font-size: 14pt;
    font-weight: 700;
    color: #1a3a5c;
    margin-bottom: 2px;
}}
.header-line {{
    font-size: 10pt;
    color: #444;
}}
.subject {{
    font-weight: 600;
    margin: 16px 0 14px 0;
    color: #1a3a5c;
}}
.letter-para {{
    margin: 0 0 12px 0;
    text-align: left;
}}
.closing {{
    margin-top: 20px;
    line-height: 1.5;
    color: #1a3a5c;
}}
</style>
</head>
<body>
<div class="letter-header">
    <div class="name">{escape(full_name)}</div>
    {header_location}
    {header_remote}
</div>
{subject_html}
{body_html}
<div class="closing">{closing_html}</div>
</body>
</html>"""


def _detect_material_kind(text_path: Path) -> str:
    if text_path.name.endswith("_CL.txt"):
        return "cover"
    return "resume"


def _build_material_html(
    text: str, profile: dict, kind: str, job: dict | None = None,
) -> str:
    if kind == "cover":
        return build_cover_letter_html(text, profile, job=job)
    return build_html(parse_resume(text))


# ── PDF Renderer ─────────────────────────────────────────────────────────

def _render_pdf_xhtml2pdf(html: str, output_path: str) -> None:
    """Render HTML to PDF using xhtml2pdf (no browser dependencies)."""
    from xhtml2pdf import pisa

    with open(output_path, "wb") as pdf_file:
        status = pisa.CreatePDF(html, dest=pdf_file, encoding="utf-8")
    if status.err:
        raise RuntimeError(f"xhtml2pdf failed with {status.err} error(s)")


def _render_pdf_playwright(html: str, output_path: str) -> None:
    """Render HTML to PDF using Playwright's headless Chromium."""
    from playwright.sync_api import sync_playwright

    from applypilot.config import get_chrome_path

    launch_kwargs: dict = {"headless": True}
    try:
        launch_kwargs["executable_path"] = get_chrome_path()
    except FileNotFoundError:
        pass

    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_kwargs)
        page = browser.new_page()
        page.set_content(html, wait_until="networkidle")
        page.pdf(
            path=output_path,
            format="Letter",
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            print_background=True,
        )
        browser.close()


def render_pdf(html: str, output_path: str) -> None:
    """Render HTML to PDF, preferring Playwright with xhtml2pdf fallback."""
    try:
        _render_pdf_playwright(html, output_path)
        return
    except Exception as exc:
        log.warning("Playwright PDF render failed (%s); falling back to xhtml2pdf", exc)

    _render_pdf_xhtml2pdf(html, output_path)


# ── Public API ───────────────────────────────────────────────────────────

def convert_to_pdf(
    text_path: Path,
    output_path: Path | None = None,
    html_only: bool = False,
    job: dict | None = None,
    profile: dict | None = None,
    kind: str | None = None,
) -> Path:
    """Convert a text resume or cover letter to a styled PDF.

    Args:
        text_path: Path to the .txt source file.
        output_path: Optional explicit output path. When omitted and job/profile
            are provided, uses build_material_filename().
        html_only: If True, write HTML instead of PDF.
        job: Job dict (title, site) for naming.
        profile: User profile dict for naming and cover letter header.
        kind: "resume" or "cover". Auto-detected from filename when omitted.

    Returns:
        Path to the generated PDF (or HTML) file.
    """
    text_path = Path(text_path)
    profile = profile or load_profile()
    material_kind = kind or _detect_material_kind(text_path)
    text = text_path.read_text(encoding="utf-8")

    if output_path is None and job is not None:
        output_path = text_path.parent / build_material_filename(profile, job, material_kind)
    elif output_path is None:
        output_path = text_path.with_suffix(".pdf")

    out = Path(output_path)

    if html_only:
        html = _build_material_html(text, profile, material_kind, job=job)
        html_out = out if out.suffix.lower() == ".html" else out.with_suffix(".html")
        html_out.write_text(html, encoding="utf-8")
        log.info("HTML generated: %s", html_out)
        return html_out

    if out.suffix.lower() != ".pdf":
        out = out.with_suffix(".pdf")

    if material_kind == "resume":
        render_resume_pdf_one_page(text, str(out))
    else:
        html = _build_material_html(text, profile, material_kind, job=job)
        render_pdf(html, str(out))
    log.info("PDF generated: %s", out)
    return out


def batch_convert_materials(limit: int = 0) -> dict[str, int]:
    """Convert tailored resumes and cover letters to named PDFs for all DB jobs.

    Updates DB paths to point at the generated PDF files.

    Returns:
        {"resumes": int, "cover_letters": int, "errors": int}
    """
    from applypilot.database import get_connection

    profile = load_profile()
    conn = get_connection()
    rows = conn.execute("""
        SELECT url, title, site, tailored_resume_path, cover_letter_path
        FROM jobs
        WHERE tailored_resume_path IS NOT NULL OR cover_letter_path IS NOT NULL
        ORDER BY fit_score DESC
    """).fetchall()

    stats = {"resumes": 0, "cover_letters": 0, "errors": 0}
    processed = 0

    for row in rows:
        if limit and processed >= limit:
            break
        job = dict(row)

        txt_path = job.get("tailored_resume_path")
        if txt_path and str(txt_path).endswith(".txt") and Path(txt_path).is_file():
            try:
                pdf_path = convert_to_pdf(
                    Path(txt_path), job=job, profile=profile, kind="resume",
                )
                conn.execute(
                    "UPDATE jobs SET tailored_resume_path = ? WHERE url = ?",
                    (str(pdf_path), job["url"]),
                )
                stats["resumes"] += 1
                processed += 1
            except Exception as exc:
                stats["errors"] += 1
                log.error("Resume PDF failed for %s: %s", job.get("title", "?"), exc)

        cl_path = job.get("cover_letter_path")
        if cl_path and str(cl_path).endswith(".txt") and Path(cl_path).is_file():
            try:
                pdf_path = convert_to_pdf(
                    Path(cl_path), job=job, profile=profile, kind="cover",
                )
                conn.execute(
                    "UPDATE jobs SET cover_letter_path = ? WHERE url = ?",
                    (str(pdf_path), job["url"]),
                )
                stats["cover_letters"] += 1
                processed += 1
            except Exception as exc:
                stats["errors"] += 1
                log.error("Cover letter PDF failed for %s: %s", job.get("title", "?"), exc)

    conn.commit()
    log.info(
        "PDF batch done: %d resumes, %d cover letters, %d errors",
        stats["resumes"], stats["cover_letters"], stats["errors"],
    )
    return stats


def batch_convert(limit: int = 50) -> int:
    """Legacy batch convert for tailored resumes without DB context.

    Prefer batch_convert_materials() for upload-ready named PDFs.
    """
    result = batch_convert_materials(limit=limit if limit else 0)
    return result["resumes"] + result["cover_letters"]
