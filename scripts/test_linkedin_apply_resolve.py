#!/usr/bin/env python3
"""Unit + live checks for LinkedIn → ATS apply URL resolution."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from applypilot.config import load_env  # noqa: E402
from applypilot.job_meta import (  # noqa: E402
    classify_apply_url,
    linkedin_job_id,
    linkedin_job_view_url,
    parse_linkedin_apply_url_from_html,
    resolve_linkedin_apply_url,
)

load_env()

SAMPLE_HTML = """
<html><body>
<code id="applyUrl" style="display: none"><!--"?url=https%3A%2F%2Fwww.runzero.com%2Fabout%2Fcareers%2Fapply%2F%3Fgh_jid%3D6105125004%26gh_src%3Db7d0b22e4us"--></code>
</body></html>
"""

SEARCH_URL = (
    "https://www.linkedin.com/jobs/search-results/"
    "?currentJobId=4436408417&keywords=Software%20Engineer"
)

RUNZERO_APPLY = (
    "https://www.runzero.com/about/careers/apply/"
    "?gh_jid=6105125004&gh_src=b7d0b22e4us"
)


def test_unit() -> None:
    assert linkedin_job_id(SEARCH_URL) == "4436408417"
    assert linkedin_job_view_url(SEARCH_URL) == (
        "https://www.linkedin.com/jobs/view/4436408417"
    )
    parsed = parse_linkedin_apply_url_from_html(SAMPLE_HTML)
    assert parsed is not None
    assert "runzero.com" in parsed
    assert "gh_jid=6105125004" in parsed
    ok, reason = classify_apply_url(parsed)
    assert ok, reason
    ok_board, reason_board = classify_apply_url(
        "https://www.linkedin.com/jobs/view/4436408417"
    )
    assert not ok_board
    assert reason_board == "job_board_apply_url"

    # Simulated LinkedIn redirect target must be Stage-6 usable.
    ok_ats, reason_ats = classify_apply_url(RUNZERO_APPLY)
    assert ok_ats, reason_ats
    print("unit: ok")


def test_live(job_url: str) -> int:
    print(f"live resolve: {job_url}")
    view = linkedin_job_view_url(job_url) or job_url
    resolved = resolve_linkedin_apply_url(view, follow=True)
    if not resolved:
        print(
            "live: no off-site apply URL "
            "(Easy Apply, public sign-in wall, or missing LINKEDIN_LI_AT)"
        )
        return 2
    ok, reason = classify_apply_url(resolved)
    print(f"resolved: {resolved}")
    print(f"usable: {ok} ({reason or 'ok'})")
    return 0 if ok else 1


def test_ats_page(url: str) -> int:
    """Confirm a resolved ATS URL loads (Playwright)."""
    from playwright.sync_api import sync_playwright

    print(f"ats page: {url}")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        resp = page.goto(url, timeout=45000)
        page.wait_for_load_state("domcontentloaded")
        final = page.url
        title = page.title()
        status = resp.status if resp else None
        browser.close()
    ok, reason = classify_apply_url(final)
    print(f"  status={status} title={title!r}")
    print(f"  final={final}")
    print(f"  usable={ok} ({reason or 'ok'})")
    return 0 if ok and status and status < 400 else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", metavar="URL", help="Resolve a live LinkedIn job URL")
    parser.add_argument(
        "--ats",
        metavar="URL",
        help="Open a resolved ATS apply URL and verify it is usable",
    )
    parser.add_argument("--unit-only", action="store_true")
    args = parser.parse_args()

    test_unit()
    if args.unit_only:
        return 0
    code = 0
    if args.live:
        code = max(code, test_live(args.live))
    if args.ats:
        code = max(code, test_ats_page(args.ats))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
