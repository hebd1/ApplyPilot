"""Employer labeling and apply-URL quality helpers.

`site` on a job is the discovery board (Indeed, Talent.com, …). `company` is
the employer when known. Prefer `display_company(job)` for prompts, PDFs, and
dashboard labels.
"""

from __future__ import annotations

import logging
import re
from html import unescape
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)

# LinkedIn embeds the off-site apply target in <code id="applyUrl">?url=...</code>
_LINKEDIN_APPLY_URL_RE = re.compile(r"(?<=\?url=)[^\"<]+")
_LINKEDIN_JOB_ID_RE = re.compile(
    r"(?:linkedin\.com/jobs/view/|currentJobId=)(\d{5,})",
    re.IGNORECASE,
)

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

    if host in _BOARD_HOSTS or host.endswith(".linkedin.com"):
        # Pure job-board view pages are poor apply targets (prefer careers ATS URL).
        return False, "job_board_apply_url"

    return True, ""


def linkedin_job_id(url: str | None) -> str | None:
    """Extract a numeric LinkedIn job id from a view or search-results URL."""
    if not url:
        return None
    m = _LINKEDIN_JOB_ID_RE.search(str(url))
    return m.group(1) if m else None


def linkedin_job_view_url(url: str | None) -> str | None:
    """Normalize LinkedIn search/view URLs to ``/jobs/view/{id}``."""
    job_id = linkedin_job_id(url)
    if not job_id:
        return None
    return f"https://www.linkedin.com/jobs/view/{job_id}"


def parse_linkedin_apply_url_from_html(html: str | None) -> str | None:
    """Parse LinkedIn's embedded off-site apply target from job HTML.

    Public LinkedIn job pages often include::

        <code id="applyUrl" style="display: none"><!--"?url=https%3A%2F%2F... "--></code>

    Easy Apply-only postings omit this and cannot be auto-applied via ATS.
    """
    if not html:
        return None

    # Prefer the dedicated applyUrl blob JobSpy also reads.
    m = re.search(
        r'<code[^>]*\bid=["\']applyUrl["\'][^>]*>(.*?)</code>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    blob = m.group(1) if m else html
    blob = unescape(blob)

    match = _LINKEDIN_APPLY_URL_RE.search(blob)
    if match:
        return _clean_apply_url(unquote(match.group(0)).strip().rstrip('"').rstrip("'"))

    # Fallback: explicit url= query inside applyUrl-ish JSON/text.
    for key in ("applyUrl", "companyApplyUrl", "externalApplyUrl"):
        qm = re.search(rf'"{key}"\s*:\s*"([^"]+)"', html)
        if qm:
            candidate = unquote(unescape(qm.group(1))).strip()
            if candidate.startswith("http"):
                return _clean_apply_url(candidate)
    return None


def _clean_apply_url(url: str) -> str:
    """Normalize leaked JSON escapes and trailing junk in apply targets."""
    cleaned = (
        url.replace("\\u0026", "&")
        .replace("\\u002f", "/")
        .replace("\\/", "/")
        .replace("\\u003d", "=")
        .replace("\\u003f", "?")
        .rstrip("\\")
        .strip()
        .rstrip('"')
        .rstrip("'")
    )
    return cleaned


def _linkedin_li_at_cookie() -> str | None:
    """Optional LinkedIn session cookie for off-site apply resolution."""
    try:
        from applypilot.discovery.linkedin_auth import get_li_at
        return get_li_at()
    except Exception:
        from applypilot.config import load_env
        import os
        load_env()
        raw = (os.environ.get("LINKEDIN_LI_AT") or os.environ.get("APPLYPILOT_LINKEDIN_LI_AT") or "").strip()
        return raw or None


def _http_get(url: str, timeout: float = 15.0, cookie: str | None = None) -> tuple[str, str]:
    """GET url; return (final_url, body_text). Raises on HTTP errors."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if cookie:
        headers["Cookie"] = cookie if "=" in cookie else f"li_at={cookie}"
    req = Request(url, headers=headers, method="GET")
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 — apply URL resolver
        final = resp.geturl() or url
        body = resp.read().decode("utf-8", errors="ignore")
        return final, body


def follow_apply_redirects(url: str, timeout: float = 15.0) -> str:
    """Follow HTTP redirects and return the final URL (best-effort)."""
    if not url or not str(url).strip().lower().startswith(("http://", "https://")):
        return url
    try:
        final, _body = _http_get(url, timeout=timeout)
        return final
    except Exception as exc:
        log.debug("follow_apply_redirects failed for %s: %s", url[:120], exc)
        return url


def resolve_linkedin_apply_url(
    job_url: str | None,
    html: str | None = None,
    *,
    follow: bool = True,
    timeout: float = 15.0,
) -> str | None:
    """Resolve a LinkedIn job listing to an off-site ATS/career apply URL.

    Public LinkedIn pages often omit the company apply target (sign-in wall).
    Set ``LINKEDIN_LI_AT`` in ``~/.applypilot/.env`` (or run
    ``applypilot linkedin-auth``) so company-website applies can be resolved.
    Easy Apply-only posts still return None.
    """
    apply_url = parse_linkedin_apply_url_from_html(html) if html else None
    li_at = _linkedin_li_at_cookie()
    cookie_header = f"li_at={li_at}" if li_at else None

    view = linkedin_job_view_url(job_url)
    job_id = linkedin_job_id(job_url)

    def _try_fetch(url: str, cookie: str | None) -> str | None:
        try:
            _final, page_html = _http_get(url, timeout=timeout, cookie=cookie)
        except Exception as exc:
            log.debug("LinkedIn apply fetch failed for %s: %s", url, exc)
            return None
        return parse_linkedin_apply_url_from_html(page_html)

    if not apply_url and view:
        apply_url = _try_fetch(view, cookie_header)

    # Guest jobPosting endpoint sometimes still embeds apply targets.
    if not apply_url and job_id:
        apply_url = _try_fetch(
            f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}",
            cookie_header,
        )

    if not apply_url:
        if not li_at:
            log.debug(
                "LinkedIn apply URL unavailable without session cookie "
                "(run: applypilot linkedin-auth --login) for %s",
                view or job_url,
            )
        else:
            # Cookie may have expired — try one profile refresh, then retry once.
            try:
                from applypilot.discovery.linkedin_auth import (
                    cookie_looks_valid,
                    refresh_li_at_from_profile,
                )
                ok_cookie, _ = cookie_looks_valid(li_at)
                if not ok_cookie:
                    refreshed = refresh_li_at_from_profile(headless=True)
                    if refreshed:
                        cookie_header = f"li_at={refreshed}"
                        if view:
                            apply_url = _try_fetch(view, cookie_header)
                        if not apply_url and job_id:
                            apply_url = _try_fetch(
                                f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}",
                                cookie_header,
                            )
            except Exception as exc:
                log.debug("LinkedIn cookie refresh skipped: %s", exc)
        if not apply_url:
            return None

    final = follow_apply_redirects(apply_url, timeout=timeout) if follow else apply_url
    ok, _reason = classify_apply_url(final)
    return final if ok else None


def normalize_board_apply_url(url: str | None, *, follow: bool = True) -> str | None:
    """Return a usable ATS apply URL, following redirects from board wrappers."""
    if not url:
        return None
    url = str(url).strip()
    ok, _ = classify_apply_url(url)
    if ok:
        return url

    host = _hostname(url)
    if host.endswith("linkedin.com") or host == "linkedin.com":
        return resolve_linkedin_apply_url(url, follow=follow)

    if follow and url.lower().startswith(("http://", "https://")):
        final = follow_apply_redirects(url)
        ok, _ = classify_apply_url(final)
        return final if ok else None
    return None


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
