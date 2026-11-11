"""Direct discovery from company ATS job boards (Greenhouse, Ashby, Lever public APIs).

Each board in ``config/ats_boards.yaml`` is fetched from its public JSON API.
Postings come back with the real apply link and the full description, so they
skip enrichment and go straight to scoring. Filters: software/backend title,
US-remote (or one of Eli's accepted places), and posted within
``ATS_MAX_AGE_DAYS`` (default 3).
"""

from __future__ import annotations

import html
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from applypilot import config

log = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)  # one INFO line per board request is noise

# -- Titles -------------------------------------------------------------------

_ROLE = re.compile(r"\b(engineer|developer)\b", re.I)
_TITLE_IN = re.compile(
    r"\b(software|backend|back[- ]end|platform|full[- ]?stack|golang|go|api|infrastructure|identity|"
    r"distributed|systems|server|product engineer)\b", re.I)
_TITLE_OUT = re.compile(
    r"\b(manager|director|head of|vp|vice president|intern|internship|new grad|ios|android|mobile|"
    r"machine learning|ml|data scientist|data engineer|research|solutions|sales|support|customer|"
    r"recruit\w*|designer|front[- ]?end|qa|test)\b", re.I)


def title_ok(title: str | None) -> bool:
    t = title or ""
    return bool(_ROLE.search(t) and _TITLE_IN.search(t) and not _TITLE_OUT.search(t))


# -- Locations ----------------------------------------------------------------

_REMOTE = re.compile(r"\b(remote|anywhere|distributed|work from home)\b", re.I)
_US = re.compile(r"\b(us|usa|u\.s\.|united states|americas|north america)\b", re.I)
_NON_US = re.compile(
    r"\b(uk|united kingdom|england|london|ireland|dublin|india|bangalore|bengaluru|canada|toronto|"
    r"vancouver|emea|europe|apac|latam|brazil|mexico|germany|berlin|france|paris|spain|netherlands|"
    r"amsterdam|poland|israel|tel aviv|singapore|japan|tokyo|australia|sydney|philippines|argentina|"
    r"colombia|portugal|lisbon|sweden|romania|ukraine)\b", re.I)
_GENERIC_ACCEPT = {"remote", "united states", "usa", "us", "anywhere"}
_STATE_ABBR = {"idaho": "id", "utah": "ut"}


def location_ok(location: str | None, accept: list[str]) -> bool:
    """US remote, or a place Eli accepts (``location_accept``); unknown passes to the scorer."""
    loc = (location or "").strip()
    if not loc:
        return True
    for place in accept or []:
        p = str(place).strip().lower()
        if not p or p in _GENERIC_ACCEPT:
            continue
        if re.search(r"\b" + re.escape(p) + r"\b", loc, re.I):
            return True
        abbr = _STATE_ABBR.get(p)
        if abbr and re.search(r",\s*" + abbr + r"\b", loc, re.I):
            return True
    if _REMOTE.search(loc):
        return bool(_US.search(loc)) or not _NON_US.search(loc)
    return False


# -- Parsing ------------------------------------------------------------------

def _html_to_text(raw: str | None) -> str:
    s = html.unescape(raw or "")
    s = re.sub(r"<(br|/p|/li|/h\d|/div)[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<li[^>]*>", "- ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n\n", s).strip()


def _job(company, site, slug, *, url, apply_url, title, location, posted, description, salary=None):
    return {
        "url": url, "application_url": apply_url or url, "title": (title or "").strip(),
        "location": (location or "").strip(), "posted": posted, "full_description": description,
        "description": description[:500], "salary": salary, "company": company, "site": site, "slug": slug,
    }


def parse_greenhouse(slug: str, company: str, data: dict) -> list[dict]:
    return [
        _job(company, "Greenhouse", slug,
             url=j.get("absolute_url"), apply_url=j.get("absolute_url"), title=j.get("title"),
             location=(j.get("location") or {}).get("name"),
             posted=j.get("first_published") or j.get("updated_at"),
             description=_html_to_text(j.get("content")))
        for j in (data or {}).get("jobs", []) if j.get("absolute_url")
    ]


def parse_ashby(slug: str, company: str, data: dict) -> list[dict]:
    out = []
    for j in (data or {}).get("jobs", []):
        if not j.get("jobUrl"):
            continue
        loc = j.get("location") or ""
        if j.get("isRemote") and "remote" not in loc.lower():
            loc = f"{loc} (Remote)".strip()
        comp = j.get("compensation") or {}
        out.append(_job(company, "Ashby", slug,
                        url=j["jobUrl"], apply_url=j.get("applyUrl"), title=j.get("title"), location=loc,
                        posted=j.get("publishedAt"),
                        description=(j.get("descriptionPlain") or _html_to_text(j.get("descriptionHtml"))).strip(),
                        salary=comp.get("compensationTierSummary") or comp.get("scrapeableCompensationSalarySummary")))
    return out


def parse_lever(slug: str, company: str, data: list) -> list[dict]:
    out = []
    for j in data or []:
        if not j.get("hostedUrl"):
            continue
        loc = (j.get("categories") or {}).get("location") or ""
        if (j.get("workplaceType") or "").lower() == "remote" and "remote" not in loc.lower():
            loc = f"{loc} (Remote)".strip()
        parts = [j.get("descriptionPlain") or ""]
        for block in j.get("lists") or []:
            parts.append(f"{block.get('text', '')}\n{_html_to_text(block.get('content'))}")
        parts.append(j.get("additionalPlain") or "")
        rng = j.get("salaryRange") or {}
        salary = None
        if rng.get("min") and rng.get("max"):
            salary = f"${rng['min']:,} – ${rng['max']:,} {rng.get('currency', 'USD')}"
        created = j.get("createdAt")
        posted = datetime.fromtimestamp(created / 1000, tz=timezone.utc).isoformat() if created else None
        out.append(_job(company, "Lever", slug,
                        url=j["hostedUrl"], apply_url=j.get("applyUrl"), title=j.get("text"), location=loc,
                        posted=posted, description="\n\n".join(p for p in parts if p.strip()).strip(),
                        salary=salary))
    return out


FETCHERS = {
    "greenhouse": ("https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true", parse_greenhouse),
    "ashby": ("https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true", parse_ashby),
    "lever": ("https://api.lever.co/v0/postings/{slug}?mode=json", parse_lever),
}


# -- Selection and storage ----------------------------------------------------

def _parse_time(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def select_jobs(jobs: list[dict], *, max_age_days: int, accept: list[str], now: datetime | None = None) -> list[dict]:
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=max_age_days)
    kept = []
    for j in jobs:
        posted = _parse_time(j.get("posted"))
        if posted and posted < cutoff:
            continue
        if title_ok(j.get("title")) and location_ok(j.get("location"), accept):
            kept.append(j)
    return kept


def store(conn, jobs: list[dict]) -> tuple[int, int]:
    """Insert apply-ready postings (already enriched). Returns (new, duplicates)."""
    from applypilot.config import is_marketplace_url, title_is_excluded

    now = datetime.now(timezone.utc).isoformat()
    new = dup = 0
    for j in jobs:
        if title_is_excluded(j.get("title")) or is_marketplace_url(j.get("application_url")):
            continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO jobs (url, title, salary, description, location, site, strategy, "
            "discovered_at, full_description, application_url, detail_scraped_at, company) "
            "VALUES (?, ?, ?, ?, ?, ?, 'ats_api', ?, ?, ?, ?, ?)",
            (j["url"], j["title"], j.get("salary"), j.get("description"), j.get("location"), j["site"],
             now, j.get("full_description"), j["application_url"], now, j.get("company")),
        )
        if cur.rowcount:
            new += 1
        else:
            dup += 1
    conn.commit()
    return new, dup


def load_boards() -> list[dict]:
    import yaml

    path = config.CONFIG_DIR / "ats_boards.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    return [b for b in (data or {}).get("boards", []) if b.get("ats") in FETCHERS and b.get("slug")]


def _fetch(board: dict) -> list[dict]:
    import httpx

    url_fmt, parser = FETCHERS[board["ats"]]
    resp = httpx.get(url_fmt.format(slug=board["slug"]), timeout=30, follow_redirects=True)
    resp.raise_for_status()
    return parser(board["slug"], board.get("company") or board["slug"], resp.json())


def run_ats_discovery(max_age_days: int | None = None, workers: int = 8) -> dict:
    from applypilot.database import get_connection

    max_age = max_age_days or int(os.environ.get("ATS_MAX_AGE_DAYS", "3"))
    accept = config.load_search_config().get("location_accept") or []
    boards = load_boards()
    stats = {"boards": len(boards), "errors": 0, "matched": 0, "new": 0}

    def fetch(board):
        try:
            return board, _fetch(board)
        except Exception as exc:
            log.warning("ATS board %s/%s failed: %s", board["ats"], board["slug"], exc)
            return board, None

    conn = get_connection()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for board, jobs in pool.map(fetch, boards):
            if jobs is None:
                stats["errors"] += 1
                continue
            kept = select_jobs(jobs, max_age_days=max_age, accept=accept)
            new, _dup = store(conn, kept)
            stats["matched"] += len(kept)
            stats["new"] += new
            if kept:
                log.info("ATS %-18s %3d postings, %2d match, %2d new", board.get("company"), len(jobs), len(kept), new)
    log.info("ATS boards: %d boards, %d matching postings, %d new (max age %d days, %d errors)",
             stats["boards"], stats["matched"], stats["new"], max_age, stats["errors"])
    return stats
