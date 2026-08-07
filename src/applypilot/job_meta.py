"""Employer labeling and apply-URL quality helpers.

`site` on a job is the discovery board (Indeed, Talent.com, …). `company` is
the employer when known. Prefer `display_company(job)` for prompts, PDFs, and
dashboard labels.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# Aggregator / job-board hosts that are weak as application destinations.
_BOARD_HOSTS = frozenset({
    "indeed.com",
    "linkedin.com",
    "talent.com",
    "ziprecruiter.com",
    "glassdoor.com",
    "simplyhired.com",
    "dice.com",
})

_BOARD_SITE_LABELS = frozenset({
    "indeed", "linkedin", "talent.com", "ziprecruiter", "glassdoor",
    "simplyhired", "dice", "google",
})


def _title_case_slug(slug: str) -> str:
    cleaned = re.sub(r"[-_]+", " ", (slug or "").strip())
    if not cleaned:
        return ""
    # Preserve short all-caps tokens like IBM / BMO when already uppercase
    if cleaned.isupper() and len(cleaned) <= 6:
        return cleaned
    return cleaned.title()


def _hostname(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def infer_company_from_url(url: str | None) -> str | None:
    """Best-effort employer name from an ATS / careers URL (not job-board hosts)."""
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return None

    host = _hostname(url)
    if not host or host in _BOARD_HOSTS:
        return None

    path = urlparse(url).path or ""
    parts = [p for p in path.split("/") if p]

    # company.wd5.myworkdayjobs.com
    m = re.match(r"^([a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com$", host)
    if m:
        return _title_case_slug(m.group(1))

    # boards.greenhouse.io/slug or job-boards.greenhouse.io/slug
    if "greenhouse.io" in host:
        if parts and parts[0] not in {"embed", "jobs", "jh"}:
            return _title_case_slug(parts[0])
        return None

    # grnh.se short links — no company slug
    if host == "grnh.se":
        return None

    # jobs.lever.co/company
    if host == "jobs.lever.co" or host.endswith(".lever.co"):
        if parts:
            return _title_case_slug(parts[0])
        return None

    # jobs.ashbyhq.com/company
    if host == "jobs.ashbyhq.com" or host.endswith(".ashbyhq.com"):
        if parts:
            return _title_case_slug(parts[0])
        return None

    if host in {"github.careers", "www.github.careers"} or host.endswith(".github.careers"):
        return "GitHub"

    for prefix in ("careers.", "jobs.", "job.", "apply."):
        if host.startswith(prefix):
            slug = host[len(prefix):].split(".")[0]
            if slug and slug not in _BOARD_HOSTS:
                return _title_case_slug(slug)

    if host.endswith(".careers"):
        slug = host[: -len(".careers")].split(".")[0]
        if slug:
            return _title_case_slug(slug)

    return None


def display_company(job: dict) -> str:
    """Employer label for prompts / filenames: company column, URL inference, else site."""
    company = (job.get("company") or "").strip()
    if company:
        return company

    for key in ("application_url", "url"):
        inferred = infer_company_from_url(job.get(key))
        if inferred:
            return inferred

    site = (job.get("site") or "").strip()
    return site or "Unknown"


def is_board_site_label(site: str | None) -> bool:
    if not site:
        return False
    return site.strip().lower() in _BOARD_SITE_LABELS


def classify_apply_url(url: str | None) -> tuple[bool, str]:
    """Return (ok, reason). Reject relative / aggregator / redirect apply URLs."""
    if not url or not str(url).strip():
        return False, "missing_apply_url"

    url = str(url).strip()
    if url.startswith("/") or not url.lower().startswith(("http://", "https://")):
        return False, "relative_or_non_http_apply_url"

    try:
        parsed = urlparse(url)
    except Exception:
        return False, "invalid_apply_url"

    host = _hostname(url)
    path = (parsed.path or "").lower()
    query = (parsed.query or "").lower()

    if not host:
        return False, "missing_apply_host"

    # Marketplace / contractor intakes are never good apply targets.
    from applypilot.config import is_marketplace_url
    if is_marketplace_url(url):
        return False, "marketplace_host"

    if "/redirect" in path or path == "/redirect" or query.startswith("id=") and "redirect" in url.lower():
        if "talent.com" in host or path.startswith("/redirect"):
            return False, "aggregator_redirect"

    if host in _BOARD_HOSTS:
        # Pure job-board view pages are poor apply targets (prefer careers ATS URL).
        return False, "job_board_apply_url"

    return True, ""


def job_has_usable_apply_url(job: dict | None) -> tuple[bool, str]:
    """True when ``application_url`` is a real ATS/career link Stage 6 can open.

    LinkedIn/Indeed board pages and missing apply links return False — use this
    before tailor/cover so we do not spend LLM tokens on un-applyable jobs.
    Does **not** fall back to ``job['url']`` (board listing).
    """
    if not job:
        return False, "missing_job"
    return classify_apply_url(job.get("application_url"))


def is_preferred_ats_url(url: str | None) -> bool:
    """True when URL looks like Greenhouse / Lever / Ashby / Workday."""
    from applypilot.config import preferred_ats_rank
    return preferred_ats_rank(url) < 50
