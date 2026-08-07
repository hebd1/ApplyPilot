"""ApplyPilot HTML Dashboard Generator.

Generates a self-contained HTML dashboard with:
  - Top modules: Overview, Jobs, Applied, Failed
  - Summary stats and score / source charts
  - Filterable scored job cards
  - Applied listings with status, timestamps, materials, and full details
  - Failed apply attempts for triage
"""

from __future__ import annotations

import os
import platform
import webbrowser
from html import escape
from pathlib import Path

from rich.console import Console

from applypilot.config import APP_DIR, DB_PATH
from applypilot.database import get_connection
from applypilot.job_meta import display_company

console = Console()

_SITE_COLORS = {
    "RemoteOK": "#10b981", "WelcomeToTheJungle": "#f59e0b",
    "Job Bank Canada": "#3b82f6", "CareerJet Canada": "#8b5cf6",
    "Hacker News Jobs": "#ff6600", "BuiltIn Remote": "#ec4899",
    "TD Bank": "#00a651", "CIBC": "#c41f3e", "RBC": "#003168",
    "indeed": "#2164f3", "linkedin": "#0a66c2",
    "Dice": "#eb1c26", "Glassdoor": "#0caa41",
}


def _resolve_material_path(path_str: str) -> Path | None:
    """Return the best on-disk path for a material (PDF preferred)."""
    if not path_str:
        return None
    path = Path(path_str)
    if path.is_file():
        return path.resolve()
    if path.suffix.lower() != ".pdf":
        pdf = path.with_suffix(".pdf")
        if pdf.is_file():
            return pdf.resolve()
    return None


def _wsl_distro_name() -> str | None:
    """Return the WSL distro name when running inside WSL."""
    if platform.system() != "Linux":
        return None
    try:
        with open("/proc/version", encoding="utf-8") as fh:
            if "microsoft" not in fh.read().lower():
                return None
    except OSError:
        return None
    return os.environ.get("WSL_DISTRO_NAME") or "Ubuntu"


def _local_file_href(path_str: str | None) -> str | None:
    """Return a browser-openable URI for an on-disk material file."""
    target = _resolve_material_path(path_str) if path_str else None
    if target is None:
        return None

    distro = _wsl_distro_name()
    if distro:
        rel = target.as_posix().lstrip("/")
        return f"file://wsl.localhost/{distro}/{rel}"

    return target.as_uri()


def _material_link_html(path_str: str | None, label: str, css_class: str) -> str:
    """Build a footer link to a tailored resume or cover letter file."""
    href = _local_file_href(path_str)
    if not href:
        return ""
    kind = "PDF" if href.lower().endswith(".pdf") else "TXT"
    return (
        f'<a href="{href}" class="material-link {css_class}" target="_blank">'
        f"{label} ({kind})</a>"
    )


def _score_color(score: int | None) -> str:
    if score is None:
        return "#64748b"
    if score >= 7:
        return "#10b981"
    if score >= 5:
        return "#f59e0b"
    return "#ef4444"


def _parse_reasoning(reasoning_raw: str | None) -> tuple[str, str]:
    reasoning_raw = reasoning_raw or ""
    lines = reasoning_raw.split("\n")
    keywords = lines[0][:160] if lines else ""
    reasoning = lines[1][:280] if len(lines) > 1 else ""
    return keywords, reasoning


def _job_card_html(j: dict, *, variant: str = "review") -> str:
    """Build one job card. variant: review | applied | failed."""
    score = j.get("fit_score")
    score_val = score if score is not None else 0
    title = escape(j.get("title") or "Untitled")
    url = escape(j.get("url") or "")
    salary = escape(j.get("salary") or "")
    location = escape(j.get("location") or "")
    site = escape(j.get("site") or "")
    company = escape(display_company(j))
    site_color = _SITE_COLORS.get(j.get("site") or "", "#6b7280")
    apply_url = escape(j.get("application_url") or "")
    keywords, reasoning = _parse_reasoning(j.get("score_reasoning"))
    desc_preview = escape(j.get("full_description") or "")[:300]
    full_desc_html = escape(j.get("full_description") or "").replace("\n", "<br>")
    desc_len = len(j.get("full_description") or "")

    meta_parts = [
        f'<span class="meta-tag site-tag" style="background:{site_color}33;color:{site_color}">{company}</span>'
    ]
    if company != site and site:
        meta_parts.append(f'<span class="meta-tag" style="opacity:0.75">via {site}</span>')
    if salary:
        meta_parts.append(f'<span class="meta-tag salary">{salary}</span>')
    if location:
        meta_parts.append(f'<span class="meta-tag location">{location[:50]}</span>')

    apply_status = (j.get("apply_status") or "").strip()
    applied_at = (j.get("applied_at") or "").strip()
    apply_error = (j.get("apply_error") or "").strip()
    attempts = j.get("apply_attempts")

    if variant == "applied":
        meta_parts.append('<span class="meta-tag status-applied">Applied</span>')
        if applied_at:
            meta_parts.append(f'<span class="meta-tag">{escape(applied_at[:19].replace("T", " "))} UTC</span>')
        outcome = (j.get("outcome") or "").strip()
        if outcome:
            outcome_class = {
                "interview": "status-interview",
                "offer": "status-offer",
                "rejected": "status-rejected",
                "confirmed": "status-confirmed",
            }.get(outcome, "status-confirmed")
            meta_parts.append(
                f'<span class="meta-tag {outcome_class}">{escape(outcome.title())}</span>'
            )
    elif variant == "failed":
        status_label = escape(apply_status or "failed")
        meta_parts.append(f'<span class="meta-tag status-failed">{status_label}</span>')
        if apply_error:
            meta_parts.append(f'<span class="meta-tag status-error">{escape(apply_error[:80])}</span>')
        if attempts:
            meta_parts.append(f'<span class="meta-tag">{int(attempts)} attempt(s)</span>')

    meta_html = " ".join(meta_parts)

    apply_html = ""
    if apply_url:
        label = "Open Application" if variant == "applied" else "Apply"
        apply_html = f'<a href="{apply_url}" class="apply-link" target="_blank">{label}</a>'
    elif url:
        apply_html = f'<a href="{url}" class="apply-link" target="_blank">Job Posting</a>'

    resume_html = _material_link_html(
        j.get("tailored_resume_path"), "Resume", "material-link-resume",
    )
    cover_html = _material_link_html(
        j.get("cover_letter_path"), "Cover Letter", "material-link-cover",
    )
    action_links = "".join(link for link in (resume_html, cover_html, apply_html) if link)
    footer_html = (
        f'<div class="card-footer"><div class="action-links">{action_links}</div></div>'
        if action_links
        else ""
    )

    score_pill = ""
    if score is not None:
        score_pill = (
            f'<span class="score-pill" style="background:{_score_color(score)}">{score}</span>'
        )
    else:
        score_pill = '<span class="score-pill" style="background:#64748b">—</span>'

    detail_bits = []
    if variant in ("applied", "failed"):
        detail_bits.append("<div class='detail-grid'>")
        detail_bits.append(
            f"<div><span class='detail-label'>Status</span>"
            f"<span class='detail-value'>{escape(apply_status or ('applied' if applied_at else '—'))}</span></div>"
        )
        if applied_at:
            detail_bits.append(
                f"<div><span class='detail-label'>Applied at</span>"
                f"<span class='detail-value'>{escape(applied_at)}</span></div>"
            )
        outcome = (j.get("outcome") or "").strip()
        if outcome:
            detail_bits.append(
                f"<div><span class='detail-label'>Email outcome</span>"
                f"<span class='detail-value'>{escape(outcome)}</span></div>"
            )
        snippet = (j.get("outcome_snippet") or "").strip()
        if snippet:
            detail_bits.append(
                f"<div class='detail-span'><span class='detail-label'>Email</span>"
                f"<span class='detail-value'>{escape(snippet)}</span></div>"
            )
        if apply_error:
            detail_bits.append(
                f"<div class='detail-span'><span class='detail-label'>Apply note</span>"
                f"<span class='detail-value'>{escape(apply_error)}</span></div>"
            )
        if apply_url:
            detail_bits.append(
                f"<div class='detail-span'><span class='detail-label'>Application URL</span>"
                f"<span class='detail-value'><a href='{apply_url}' target='_blank'>{apply_url}</a></span></div>"
            )
        detail_bits.append("</div>")
    details_html = "".join(detail_bits)

    search_blob = " ".join(
        filter(
            None,
            [
                j.get("title"),
                j.get("company"),
                j.get("site"),
                j.get("location"),
                apply_status,
                apply_error,
            ],
        )
    ).lower()

    return f"""
        <div class="job-card" data-score="{score_val}" data-site="{escape(j.get('site') or '')}"
             data-location="{location.lower()}" data-search="{escape(search_blob)}"
             data-variant="{variant}">
          <div class="card-header">
            {score_pill}
            <a href="{url or apply_url}" class="job-title" target="_blank">{title}</a>
          </div>
          <div class="meta-row">{meta_html}</div>
          {details_html}
          {f'<div class="keywords-row">{escape(keywords)}</div>' if keywords else ''}
          {f'<div class="reasoning-row">{escape(reasoning)}</div>' if reasoning else ''}
          {f'<p class="desc-preview">{desc_preview}...</p>' if desc_preview else ''}
          {"<details class='full-desc-details'><summary class='expand-btn'>Full Description (" + f'{desc_len:,}' + " chars)</summary><div class='full-desc'>" + full_desc_html + "</div></details>" if j.get("full_description") else ""}
          {footer_html}
        </div>"""


def _grouped_job_sections(jobs: list, score_dist: dict[int, int]) -> str:
    """Group review jobs by fit score."""
    sections = ""
    current_score = None
    for j in jobs:
        score = j["fit_score"] or 0
        if score != current_score:
            if current_score is not None:
                sections += "</div>"
            score_color = _score_color(score)
            score_label = {
                10: "Perfect Match", 9: "Excellent Fit", 8: "Strong Fit",
                7: "Good Fit", 6: "Moderate+", 5: "Moderate",
            }.get(score, f"Score {score}")
            count_at_score = score_dist.get(score, 0)
            sections += f"""
            <h2 class="score-header" style="border-color:{score_color}">
              <span class="score-badge" style="background:{score_color}">{score}</span>
              {score_label} ({count_at_score} jobs)
            </h2>
            <div class="job-grid">"""
            current_score = score
        sections += _job_card_html(dict(j), variant="review")
    if current_score is not None:
        sections += "</div>"
    return sections


def generate_dashboard(output_path: str | None = None) -> str:
    """Generate an HTML dashboard of all jobs with fit scores.

    Args:
        output_path: Where to write the HTML file. Defaults to ~/.applypilot/dashboard.html.

    Returns:
        Absolute path to the generated HTML file.
    """
    out = Path(output_path) if output_path else APP_DIR / "dashboard.html"

    conn = get_connection()

    total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    ready = conn.execute(
        "SELECT COUNT(*) FROM jobs "
        "WHERE full_description IS NOT NULL AND application_url IS NOT NULL"
    ).fetchone()[0]
    scored = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE fit_score IS NOT NULL"
    ).fetchone()[0]
    high_fit = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE fit_score >= 7"
    ).fetchone()[0]
    applied_count = conn.execute(
        "SELECT COUNT(*) FROM jobs "
        "WHERE apply_status = 'applied' OR applied_at IS NOT NULL"
    ).fetchone()[0]
    failed_count = conn.execute(
        "SELECT COUNT(*) FROM jobs "
        "WHERE apply_status IS NOT NULL AND apply_status != 'applied' "
        "AND apply_status != 'in_progress' AND apply_status != ''"
    ).fetchone()[0]
    ready_apply = conn.execute(
        "SELECT COUNT(*) FROM jobs "
        "WHERE tailored_resume_path IS NOT NULL AND fit_score >= 7 "
        "AND (apply_status IS NULL OR apply_status = '' OR apply_status = 'failed') "
        "AND (apply_attempts IS NULL OR apply_attempts < 3)"
    ).fetchone()[0]

    score_dist: dict[int, int] = {}
    if scored:
        rows = conn.execute(
            "SELECT fit_score, COUNT(*) FROM jobs "
            "WHERE fit_score IS NOT NULL "
            "GROUP BY fit_score ORDER BY fit_score DESC"
        ).fetchall()
        for r in rows:
            score_dist[r[0]] = r[1]

    site_stats = conn.execute("""
        SELECT site,
               COUNT(*) as total,
               SUM(CASE WHEN fit_score >= 7 THEN 1 ELSE 0 END) as high_fit,
               SUM(CASE WHEN fit_score BETWEEN 5 AND 6 THEN 1 ELSE 0 END) as mid_fit,
               SUM(CASE WHEN fit_score < 5 AND fit_score IS NOT NULL THEN 1 ELSE 0 END) as low_fit,
               SUM(CASE WHEN fit_score IS NULL THEN 1 ELSE 0 END) as unscored,
               ROUND(AVG(fit_score), 1) as avg_score
        FROM jobs GROUP BY site ORDER BY high_fit DESC, total DESC
    """).fetchall()

    jobs = conn.execute("""
        SELECT url, title, salary, description, location, site, company, strategy,
               full_description, application_url, detail_error,
               fit_score, score_reasoning,
               tailored_resume_path, cover_letter_path,
               apply_status, applied_at, apply_error, apply_attempts
        FROM jobs
        WHERE fit_score >= 5
        ORDER BY fit_score DESC, site, title
    """).fetchall()

    applied_jobs = conn.execute("""
        SELECT url, title, salary, description, location, site, company, strategy,
               full_description, application_url, detail_error,
               fit_score, score_reasoning,
               tailored_resume_path, cover_letter_path,
               apply_status, applied_at, apply_error, apply_attempts,
               outcome, outcome_at, outcome_snippet
        FROM jobs
        WHERE apply_status = 'applied' OR applied_at IS NOT NULL
        ORDER BY (applied_at IS NULL), datetime(applied_at) DESC, title
    """).fetchall()

    failed_jobs = conn.execute("""
        SELECT url, title, salary, description, location, site, company, strategy,
               full_description, application_url, detail_error,
               fit_score, score_reasoning,
               tailored_resume_path, cover_letter_path,
               apply_status, applied_at, apply_error, apply_attempts
        FROM jobs
        WHERE apply_status IS NOT NULL
          AND apply_status != ''
          AND apply_status != 'applied'
          AND apply_status != 'in_progress'
        ORDER BY (last_attempted_at IS NULL), datetime(last_attempted_at) DESC, title
    """).fetchall()

    score_bars = ""
    max_count = max(score_dist.values()) if score_dist else 1
    for s in range(10, 0, -1):
        count = score_dist.get(s, 0)
        pct = (count / max_count * 100) if max_count else 0
        score_bars += f"""
        <div class="score-row">
          <span class="score-label">{s}</span>
          <div class="score-bar-track">
            <div class="score-bar-fill" style="width:{pct}%;background:{_score_color(s)}"></div>
          </div>
          <span class="score-count">{count}</span>
        </div>"""

    site_rows = ""
    for s in site_stats:
        site = s["site"] or "?"
        color = _SITE_COLORS.get(site, "#6b7280")
        avg = s["avg_score"] or 0
        site_rows += f"""
        <div class="site-row">
          <div class="site-name" style="color:{color}">{escape(site)}</div>
          <div class="site-nums">{s['total']} jobs &middot; {s['high_fit']} strong fit &middot; avg score {avg}</div>
          <div class="bar-track">
            <div class="bar-fill" style="width:{s['high_fit']/max(s['total'],1)*100}%;background:{color}"></div>
            <div class="bar-fill" style="width:{s['mid_fit']/max(s['total'],1)*100}%;background:{color}66"></div>
          </div>
        </div>"""

    job_sections = _grouped_job_sections(jobs, score_dist)

    applied_cards = "".join(
        _job_card_html(dict(j), variant="applied") for j in applied_jobs
    ) or '<p class="empty-state">No applications submitted yet.</p>'

    failed_cards = "".join(
        _job_card_html(dict(j), variant="failed") for j in failed_jobs
    ) or '<p class="empty-state">No failed apply attempts.</p>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ApplyPilot Dashboard</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; background: #0f172a; color: #e2e8f0; padding: 1.5rem 2rem 3rem; }}

  .topbar {{ display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 1rem; margin-bottom: 1.25rem; }}
  h1 {{ font-size: 1.8rem; font-weight: 700; }}
  .subtitle {{ color: #94a3b8; margin-top: 0.25rem; }}

  .modules {{ display: flex; flex-wrap: wrap; gap: 0.5rem; background: #1e293b; border-radius: 12px; padding: 0.5rem; margin-bottom: 1.5rem; }}
  .module-btn {{ background: transparent; border: none; color: #94a3b8; padding: 0.65rem 1rem; border-radius: 8px; cursor: pointer; font-size: 0.9rem; font-weight: 600; transition: all 0.15s; }}
  .module-btn:hover {{ color: #e2e8f0; background: #334155; }}
  .module-btn.active {{ background: #60a5fa; color: #0f172a; }}
  .module-btn .count {{ display: inline-block; margin-left: 0.35rem; font-size: 0.75rem; opacity: 0.85; }}

  .module-panel {{ display: none; }}
  .module-panel.active {{ display: block; }}

  .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 1rem; margin-bottom: 2rem; }}
  .stat-card {{ background: #1e293b; border-radius: 12px; padding: 1.25rem; cursor: pointer; border: 1px solid transparent; transition: border-color 0.15s; }}
  .stat-card:hover {{ border-color: #475569; }}
  .stat-num {{ font-size: 2rem; font-weight: 700; }}
  .stat-label {{ color: #94a3b8; font-size: 0.85rem; margin-top: 0.25rem; }}
  .stat-ok .stat-num {{ color: #10b981; }}
  .stat-scored .stat-num {{ color: #60a5fa; }}
  .stat-high .stat-num {{ color: #f59e0b; }}
  .stat-total .stat-num {{ color: #e2e8f0; }}
  .stat-applied .stat-num {{ color: #34d399; }}
  .stat-failed .stat-num {{ color: #f87171; }}
  .stat-ready .stat-num {{ color: #a78bfa; }}

  .filters {{ background: #1e293b; border-radius: 12px; padding: 1.25rem; margin-bottom: 1.5rem; display: flex; gap: 1rem; flex-wrap: wrap; align-items: center; }}
  .filter-label {{ color: #94a3b8; font-size: 0.85rem; font-weight: 600; }}
  .filter-btn {{ background: #334155; border: none; color: #94a3b8; padding: 0.4rem 0.8rem; border-radius: 6px; cursor: pointer; font-size: 0.8rem; transition: all 0.15s; }}
  .filter-btn:hover {{ background: #475569; color: #e2e8f0; }}
  .filter-btn.active {{ background: #60a5fa; color: #0f172a; font-weight: 600; }}
  .search-input {{ background: #334155; border: 1px solid #475569; color: #e2e8f0; padding: 0.4rem 0.8rem; border-radius: 6px; font-size: 0.8rem; width: 220px; }}
  .search-input::placeholder {{ color: #64748b; }}

  .score-section {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-bottom: 1rem; }}
  .score-dist, .sites-section {{ background: #1e293b; border-radius: 12px; padding: 1.5rem; }}
  .score-dist h3, .sites-section h3, .panel-title {{ font-size: 1rem; margin-bottom: 1rem; color: #94a3b8; }}
  .score-row {{ display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.4rem; }}
  .score-label {{ width: 1.5rem; text-align: right; font-size: 0.85rem; font-weight: 600; }}
  .score-bar-track {{ flex: 1; height: 14px; background: #334155; border-radius: 4px; overflow: hidden; }}
  .score-bar-fill {{ height: 100%; border-radius: 4px; transition: width 0.3s; }}
  .score-count {{ width: 2.5rem; font-size: 0.8rem; color: #94a3b8; }}
  .site-row {{ margin-bottom: 0.8rem; }}
  .site-name {{ font-weight: 600; font-size: 0.9rem; }}
  .site-nums {{ color: #94a3b8; font-size: 0.75rem; margin: 0.15rem 0; }}
  .bar-track {{ height: 8px; background: #334155; border-radius: 4px; display: flex; overflow: hidden; }}
  .bar-fill {{ height: 100%; transition: width 0.3s; }}

  .score-header {{ font-size: 1.2rem; font-weight: 600; margin: 2rem 0 1rem; padding-bottom: 0.5rem; border-bottom: 3px solid; display: flex; align-items: center; gap: 0.75rem; }}
  .score-badge {{ display: inline-flex; align-items: center; justify-content: center; width: 2rem; height: 2rem; border-radius: 8px; color: #0f172a; font-weight: 700; font-size: 1rem; }}

  .job-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(380px, 1fr)); gap: 1rem; }}
  .job-card {{ background: #1e293b; border-radius: 10px; padding: 1rem; border-left: 3px solid #334155; transition: all 0.15s; }}
  .job-card:hover {{ transform: translateY(-2px); box-shadow: 0 4px 12px #00000044; }}
  .job-card[data-score="9"], .job-card[data-score="10"] {{ border-left-color: #10b981; }}
  .job-card[data-score="8"] {{ border-left-color: #34d399; }}
  .job-card[data-score="7"] {{ border-left-color: #60a5fa; }}
  .job-card[data-score="6"], .job-card[data-score="5"] {{ border-left-color: #f59e0b; }}
  .job-card[data-variant="applied"] {{ border-left-color: #34d399; }}
  .job-card[data-variant="failed"] {{ border-left-color: #f87171; }}

  .card-header {{ display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.5rem; }}
  .score-pill {{ display: inline-flex; align-items: center; justify-content: center; min-width: 1.6rem; height: 1.6rem; border-radius: 6px; color: #0f172a; font-weight: 700; font-size: 0.8rem; flex-shrink: 0; }}
  .job-title {{ color: #e2e8f0; text-decoration: none; font-weight: 600; font-size: 0.95rem; }}
  .job-title:hover {{ color: #60a5fa; }}

  .meta-row {{ display: flex; flex-wrap: wrap; gap: 0.4rem; margin-bottom: 0.5rem; }}
  .meta-tag {{ font-size: 0.72rem; padding: 0.15rem 0.5rem; border-radius: 4px; background: #334155; color: #94a3b8; }}
  .meta-tag.salary {{ background: #064e3b; color: #6ee7b7; }}
  .meta-tag.location {{ background: #1e3a5f; color: #93c5fd; }}
  .meta-tag.status-applied {{ background: #064e3b; color: #6ee7b7; }}
  .meta-tag.status-failed {{ background: #7f1d1d; color: #fca5a5; }}
  .meta-tag.status-error {{ background: #451a03; color: #fdba74; }}
  .meta-tag.status-interview {{ background: #1e3a5f; color: #93c5fd; }}
  .meta-tag.status-offer {{ background: #365314; color: #bef264; }}
  .meta-tag.status-rejected {{ background: #44403c; color: #d6d3d1; }}
  .meta-tag.status-confirmed {{ background: #164e63; color: #a5f3fc; }}

  .detail-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem 1rem; background: #0f172a; border-radius: 8px; padding: 0.75rem; margin-bottom: 0.6rem; }}
  .detail-span {{ grid-column: 1 / -1; }}
  .detail-label {{ display: block; font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.04em; color: #64748b; margin-bottom: 0.15rem; }}
  .detail-value {{ font-size: 0.8rem; color: #cbd5e1; word-break: break-word; }}
  .detail-value a {{ color: #60a5fa; text-decoration: none; }}
  .detail-value a:hover {{ text-decoration: underline; }}

  .keywords-row {{ font-size: 0.75rem; color: #10b981; margin-bottom: 0.3rem; line-height: 1.4; }}
  .reasoning-row {{ font-size: 0.75rem; color: #94a3b8; margin-bottom: 0.5rem; font-style: italic; line-height: 1.4; }}
  .desc-preview {{ font-size: 0.8rem; color: #64748b; line-height: 1.5; margin-bottom: 0.75rem; max-height: 3.6em; overflow: hidden; }}
  .card-footer {{ display: flex; justify-content: flex-end; margin-top: 0.25rem; }}
  .action-links {{ display: flex; flex-wrap: wrap; gap: 0.4rem; justify-content: flex-end; }}
  .apply-link {{ font-size: 0.8rem; color: #60a5fa; text-decoration: none; padding: 0.3rem 0.8rem; border: 1px solid #60a5fa33; border-radius: 6px; font-weight: 500; }}
  .apply-link:hover {{ background: #60a5fa22; }}
  .material-link {{ font-size: 0.8rem; text-decoration: none; padding: 0.3rem 0.8rem; border: 1px solid; border-radius: 6px; font-weight: 500; }}
  .material-link-resume {{ color: #34d399; border-color: #34d39944; }}
  .material-link-resume:hover {{ background: #34d39922; }}
  .material-link-cover {{ color: #a78bfa; border-color: #a78bfa44; }}
  .material-link-cover:hover {{ background: #a78bfa22; }}

  .full-desc-details {{ margin-bottom: 0.75rem; }}
  .expand-btn {{ font-size: 0.8rem; color: #60a5fa; cursor: pointer; list-style: none; padding: 0.3rem 0; }}
  .expand-btn::-webkit-details-marker {{ display: none; }}
  .expand-btn:hover {{ color: #93c5fd; }}
  .full-desc {{ font-size: 0.8rem; color: #cbd5e1; line-height: 1.6; margin-top: 0.5rem; padding: 0.75rem; background: #0f172a; border-radius: 8px; max-height: 400px; overflow-y: auto; white-space: pre-wrap; word-break: break-word; }}

  .hidden {{ display: none !important; }}
  .job-count {{ color: #94a3b8; font-size: 0.85rem; margin-bottom: 1rem; }}
  .empty-state {{ color: #64748b; padding: 2rem 0; }}
  .hint {{ color: #64748b; font-size: 0.85rem; margin-bottom: 1rem; }}

  @media (max-width: 768px) {{
    .score-section {{ grid-template-columns: 1fr; }}
    .job-grid {{ grid-template-columns: 1fr; }}
    .detail-grid {{ grid-template-columns: 1fr; }}
    body {{ padding: 1rem; }}
  }}
</style>
</head>
<body>

<div class="topbar">
  <div>
    <h1>ApplyPilot</h1>
    <p class="subtitle">{total} jobs &middot; {scored} scored &middot; {applied_count} applied &middot; {high_fit} strong matches</p>
  </div>
</div>

<nav class="modules" aria-label="Dashboard modules">
  <button class="module-btn active" data-module="overview" onclick="showModule('overview')">Overview</button>
  <button class="module-btn" data-module="jobs" onclick="showModule('jobs')">Jobs<span class="count">{len(jobs)}</span></button>
  <button class="module-btn" data-module="applied" onclick="showModule('applied')">Applied<span class="count">{applied_count}</span></button>
  <button class="module-btn" data-module="failed" onclick="showModule('failed')">Failed<span class="count">{failed_count}</span></button>
</nav>

<section id="module-overview" class="module-panel active">
  <div class="summary">
    <div class="stat-card stat-total" onclick="showModule('jobs')"><div class="stat-num">{total}</div><div class="stat-label">Total Jobs</div></div>
    <div class="stat-card stat-ok" onclick="showModule('jobs')"><div class="stat-num">{ready}</div><div class="stat-label">Ready (desc + URL)</div></div>
    <div class="stat-card stat-scored" onclick="showModule('jobs')"><div class="stat-num">{scored}</div><div class="stat-label">Scored by LLM</div></div>
    <div class="stat-card stat-high" onclick="showModule('jobs'); filterScore(7)"><div class="stat-num">{high_fit}</div><div class="stat-label">Strong Fit (7+)</div></div>
    <div class="stat-card stat-applied" onclick="showModule('applied')"><div class="stat-num">{applied_count}</div><div class="stat-label">Applied</div></div>
    <div class="stat-card stat-failed" onclick="showModule('failed')"><div class="stat-num">{failed_count}</div><div class="stat-label">Failed / skipped</div></div>
    <div class="stat-card stat-ready" onclick="showModule('jobs'); filterScore(7)"><div class="stat-num">{ready_apply}</div><div class="stat-label">Materials ready</div></div>
  </div>
  <div class="score-section">
    <div class="score-dist">
      <h3>Score Distribution</h3>
      {score_bars}
    </div>
    <div class="sites-section">
      <h3>By Source</h3>
      {site_rows}
    </div>
  </div>
</section>

<section id="module-jobs" class="module-panel">
  <p class="hint">Scored jobs (5+). Filter by score or search title / company / site.</p>
  <div class="filters" data-filter-scope="jobs">
    <span class="filter-label">Score:</span>
    <button class="filter-btn active" onclick="filterScore(0)">All 5+</button>
    <button class="filter-btn" onclick="filterScore(7)">7+ Strong</button>
    <button class="filter-btn" onclick="filterScore(8)">8+ Excellent</button>
    <button class="filter-btn" onclick="filterScore(9)">9+ Perfect</button>
    <span class="filter-label" style="margin-left:1rem">Search:</span>
    <input type="text" class="search-input" id="search-jobs" placeholder="Filter jobs..." oninput="filterText(this.value, 'jobs')">
  </div>
  <div id="job-count-jobs" class="job-count"></div>
  <div id="jobs-root">
{job_sections}
  </div>
</section>

<section id="module-applied" class="module-panel">
  <h2 class="panel-title">Applications submitted ({applied_count})</h2>
  <p class="hint">Click a title for the posting. Expand full description for JD details. Resume / cover / application links are in each card.</p>
  <div class="filters" data-filter-scope="applied">
    <span class="filter-label">Search:</span>
    <input type="text" class="search-input" id="search-applied" placeholder="Filter applied..." oninput="filterText(this.value, 'applied')">
  </div>
  <div id="job-count-applied" class="job-count"></div>
  <div class="job-grid" id="applied-root">
{applied_cards}
  </div>
</section>

<section id="module-failed" class="module-panel">
  <h2 class="panel-title">Failed / skipped attempts ({failed_count})</h2>
  <p class="hint">Includes CAPTCHA, location mismatches, marketplace skips, Lever skips, and other apply errors.</p>
  <div class="filters" data-filter-scope="failed">
    <span class="filter-label">Search:</span>
    <input type="text" class="search-input" id="search-failed" placeholder="Filter failed..." oninput="filterText(this.value, 'failed')">
  </div>
  <div id="job-count-failed" class="job-count"></div>
  <div class="job-grid" id="failed-root">
{failed_cards}
  </div>
</section>

<script>
let minScore = 0;
let searchText = {{ jobs: '', applied: '', failed: '' }};

function showModule(name) {{
  document.querySelectorAll('.module-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.module-btn').forEach(b => b.classList.remove('active'));
  const panel = document.getElementById('module-' + name);
  if (panel) panel.classList.add('active');
  document.querySelectorAll('.module-btn[data-module="' + name + '"]').forEach(b => b.classList.add('active'));
  if (history.replaceState) {{
    history.replaceState(null, '', '#' + name);
  }} else {{
    location.hash = name;
  }}
  applyFilters(name === 'jobs' ? 'jobs' : name);
}}

function filterScore(min) {{
  minScore = min;
  document.querySelectorAll('#module-jobs .filter-btn').forEach(b => b.classList.remove('active'));
  if (event && event.target && event.target.classList.contains('filter-btn')) {{
    event.target.classList.add('active');
  }} else {{
    const map = {{0:0, 7:1, 8:2, 9:3}};
    const btns = document.querySelectorAll('#module-jobs .filter-btn');
    const idx = map[min] ?? 0;
    if (btns[idx]) btns[idx].classList.add('active');
  }}
  showModule('jobs');
  applyFilters('jobs');
}}

function filterText(text, scope) {{
  searchText[scope] = (text || '').toLowerCase();
  applyFilters(scope);
}}

function applyFilters(scope) {{
  scope = scope || 'jobs';
  let shown = 0;
  let total = 0;
  const rootId = scope === 'jobs' ? 'jobs-root' : (scope + '-root');
  const root = document.getElementById(rootId) || document.getElementById('module-' + scope);
  if (!root) return;
  root.querySelectorAll('.job-card').forEach(card => {{
    total++;
    const score = parseInt(card.dataset.score) || 0;
    const text = (card.dataset.search || card.textContent || '').toLowerCase();
    const q = searchText[scope] || '';
    const scoreMatch = scope !== 'jobs' || score >= (minScore || 5);
    const textMatch = !q || text.includes(q);
    if (scoreMatch && textMatch) {{
      card.classList.remove('hidden');
      shown++;
    }} else {{
      card.classList.add('hidden');
    }}
  }});
  const countEl = document.getElementById('job-count-' + scope);
  if (countEl) countEl.textContent = `Showing ${{shown}} of ${{total}}`;

  if (scope === 'jobs') {{
    document.querySelectorAll('#jobs-root .score-header').forEach(header => {{
      const grid = header.nextElementSibling;
      if (grid && grid.classList.contains('job-grid')) {{
        const visible = grid.querySelectorAll('.job-card:not(.hidden)').length;
        header.style.display = visible ? '' : 'none';
        grid.style.display = visible ? '' : 'none';
      }}
    }});
  }}
}}

const initial = (location.hash || '#overview').replace('#','') || 'overview';
showModule(['overview','jobs','applied','failed'].includes(initial) ? initial : 'overview');
</script>

</body>
</html>"""

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    abs_path = str(out.resolve())
    console.print(f"[green]Dashboard written to {abs_path}[/green]")
    return abs_path


def open_dashboard(output_path: str | None = None) -> None:
    """Generate the dashboard and open it in the default browser.

    Args:
        output_path: Where to write the HTML file. Defaults to ~/.applypilot/dashboard.html.
    """
    path = generate_dashboard(output_path)
    console.print("[dim]Opening in browser...[/dim]")
    webbrowser.open(f"file:///{path}")
