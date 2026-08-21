"""LinkedIn session cookie (li_at) capture and refresh.

Public LinkedIn pages hide company-website apply URLs behind a sign-in wall.
ApplyPilot stores ``LINKEDIN_LI_AT`` in ``~/.applypilot/.env`` and keeps a
persistent Chrome profile at ``~/.applypilot/linkedin-chrome`` so the cookie
can be refreshed without pasting it by hand every time.

Never log or commit the cookie value.
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from applypilot import config

log = logging.getLogger(__name__)

LINKEDIN_ENV_KEY = "LINKEDIN_LI_AT"
LINKEDIN_PROFILE_DIR = config.APP_DIR / "linkedin-chrome"
LINKEDIN_CDP_PORT = 9333
_LOGIN_URL = "https://www.linkedin.com/login"
_FEED_URL = "https://www.linkedin.com/feed/"


def get_li_at() -> str | None:
    """Return the current li_at cookie from env / .env (no logging of value)."""
    config.load_env()
    raw = (
        os.environ.get(LINKEDIN_ENV_KEY)
        or os.environ.get("APPLYPILOT_LINKEDIN_LI_AT")
        or ""
    ).strip()
    return raw or None


def save_li_at(value: str, *, seed_profile: bool = True) -> Path:
    """Persist li_at to ``~/.applypilot/.env`` and process env."""
    cleaned = (value or "").strip()
    if cleaned.lower().startswith("li_at="):
        cleaned = cleaned.split("=", 1)[1].strip()
    if not cleaned:
        raise ValueError("Empty LinkedIn li_at cookie")

    path = config.set_env_var(LINKEDIN_ENV_KEY, cleaned)
    os.environ[LINKEDIN_ENV_KEY] = cleaned
    if seed_profile:
        try:
            seed_profile_with_li_at(cleaned)
        except Exception as exc:
            log.debug("Could not seed LinkedIn Chrome profile: %s", exc)
    return path


def seed_profile_with_li_at(li_at: str, *, port: int = LINKEDIN_CDP_PORT) -> None:
    """Write li_at into the persistent Chrome profile so --refresh can rotate it."""
    token = (li_at or "").strip()
    if not token:
        return
    proc = None
    try:
        proc = _launch_linkedin_chrome(headless=True, port=port)
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            context.add_cookies(
                [
                    {
                        "name": "li_at",
                        "value": token,
                        "domain": ".linkedin.com",
                        "path": "/",
                        "httpOnly": True,
                        "secure": True,
                        "sameSite": "None",
                    }
                ]
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(_FEED_URL, timeout=45000, wait_until="domcontentloaded")
            time.sleep(1.5)
    finally:
        _stop_chrome(proc, port=port)


def cookie_looks_valid(li_at: str | None = None, timeout: float = 15.0) -> tuple[bool, str]:
    """Best-effort check that li_at still authenticates to LinkedIn."""
    token = (li_at or get_li_at() or "").strip()
    if not token:
        return False, "missing"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Cookie": f"li_at={token}",
        "Accept": "text/html",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        req = Request(_FEED_URL, headers=headers, method="GET")
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310
            final = resp.geturl() or ""
            body = resp.read(8000).decode("utf-8", errors="ignore")
    except Exception as exc:
        return False, f"request_failed:{type(exc).__name__}"

    host = (urlparse(final).hostname or "").lower()
    path = (urlparse(final).path or "").lower()
    if "login" in path or "authwall" in path or "signup" in path:
        return False, "expired_or_logged_out"
    if "linkedin.com" in host and ("feed" in path or path in {"", "/"} or "jobs" in path):
        return True, "ok"
    # Soft pass: not bounced to login and response looks authenticated.
    if "login" not in body.lower()[:500] and "linkedin.com" in host:
        return True, "ok_soft"
    return False, "unexpected_response"


def _kill_port(port: int) -> None:
    try:
        if platform.system() == "Windows":
            result = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"],
                capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    pid = line.strip().split()[-1]
                    if pid.isdigit():
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", pid],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=10,
                        )
        else:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True, text=True, timeout=10,
            )
            for pid_str in result.stdout.strip().splitlines():
                if pid_str.strip().isdigit():
                    subprocess.run(
                        ["kill", "-9", pid_str.strip()],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5,
                    )
    except Exception:
        log.debug("Could not clear CDP port %d", port, exc_info=True)


def _launch_linkedin_chrome(headless: bool, port: int = LINKEDIN_CDP_PORT) -> subprocess.Popen:
    """Launch a dedicated Chrome profile for LinkedIn auth."""
    LINKEDIN_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    (LINKEDIN_PROFILE_DIR / "Default").mkdir(parents=True, exist_ok=True)
    _kill_port(port)

    chrome_exe = config.get_chrome_path()
    cmd = [
        chrome_exe,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={LINKEDIN_PROFILE_DIR}",
        "--profile-directory=Default",
        "--no-first-run",
        "--no-default-browser-check",
        "--window-size=1100,900",
        "--disable-session-crashed-bubble",
        "--hide-crash-restore-bubble",
        "--password-store=basic",
    ]
    if headless:
        cmd.append("--headless=new")

    kwargs: dict = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if platform.system() != "Windows":
        kwargs["preexec_fn"] = os.setsid

    proc = subprocess.Popen(cmd, **kwargs)
    time.sleep(2.5)
    return proc


def _stop_chrome(proc: subprocess.Popen | None, port: int = LINKEDIN_CDP_PORT) -> None:
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    _kill_port(port)


def _li_at_from_cookies(cookies: list[dict]) -> str | None:
    for cookie in cookies:
        if cookie.get("name") == "li_at" and cookie.get("value"):
            return str(cookie["value"]).strip()
    return None


def _read_li_at_via_cdp(port: int = LINKEDIN_CDP_PORT) -> str | None:
    """Read li_at from a Chrome instance over CDP using Playwright."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        try:
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            token = _li_at_from_cookies(context.cookies(["https://www.linkedin.com"]))
            if token:
                return token
            return _li_at_from_cookies(context.cookies())
        finally:
            # Do not browser.close() — that can tear down the Chrome CDP target.
            pass
    return None


def refresh_li_at_from_profile(*, headless: bool = True, port: int = LINKEDIN_CDP_PORT) -> str | None:
    """Pull a fresh li_at from the persistent LinkedIn Chrome profile.

    Returns the cookie when found and saves it to ``.env``. If the profile is
    logged out but ``LINKEDIN_LI_AT`` still validates, re-seed the profile and
    return that cookie so enrich can keep resolving apply URLs.
    """
    proc = None
    token = None
    try:
        proc = _launch_linkedin_chrome(headless=headless, port=port)
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(_FEED_URL, timeout=45000, wait_until="domcontentloaded")
            time.sleep(2)
            token = _li_at_from_cookies(context.cookies(["https://www.linkedin.com"]))
            if not token:
                token = _li_at_from_cookies(context.cookies())

        if token:
            save_li_at(token)
            return token
    finally:
        _stop_chrome(proc, port=port)

    # Profile logged out — keep using a still-valid .env cookie and try to re-seed
    # the Chrome profile so later --refresh calls can rotate it.
    existing = get_li_at()
    if existing:
        ok, _reason = cookie_looks_valid(existing)
        if ok:
            try:
                seed_profile_with_li_at(existing, port=port)
                log.info("LinkedIn profile had no session; re-seeded from LINKEDIN_LI_AT")
            except Exception as exc:
                log.debug("Could not re-seed LinkedIn Chrome profile: %s", exc)
            return existing
    return None


def interactive_login(
    *,
    timeout_sec: int = 300,
    port: int = LINKEDIN_CDP_PORT,
    headed: bool = True,
) -> str:
    """Open LinkedIn login in Chrome and wait until ``li_at`` appears.

    Uses the persistent ``linkedin-chrome`` profile so later refreshes can
    often pull a rotated cookie without another full login.
    """
    proc = None
    try:
        proc = _launch_linkedin_chrome(headless=not headed, port=port)
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.pages[0] if context.pages else context.new_page()

            page.goto(_FEED_URL, timeout=45000, wait_until="domcontentloaded")
            time.sleep(1.5)
            token = _li_at_from_cookies(context.cookies(["https://www.linkedin.com"]))
            if not token:
                token = _li_at_from_cookies(context.cookies())
            if token:
                save_li_at(token)
                return token

            page.goto(_LOGIN_URL, timeout=45000, wait_until="domcontentloaded")
            deadline = time.time() + max(30, timeout_sec)
            while time.time() < deadline:
                token = _li_at_from_cookies(context.cookies(["https://www.linkedin.com"]))
                if not token:
                    token = _li_at_from_cookies(context.cookies())
                if token:
                    try:
                        page.goto(_FEED_URL, timeout=30000, wait_until="domcontentloaded")
                    except Exception:
                        pass
                    save_li_at(token)
                    return token
                time.sleep(2)

            raise TimeoutError(
                f"Timed out after {timeout_sec}s waiting for LinkedIn login "
                "(li_at cookie never appeared)"
            )
    finally:
        _stop_chrome(proc, port=port)


def ensure_li_at(*, allow_interactive: bool = False, timeout_sec: int = 300) -> tuple[str | None, str]:
    """Ensure a working li_at is available.

    Order: validate env cookie → refresh from Chrome profile → optional interactive login.
    Returns ``(cookie_or_none, status)``.
    """
    current = get_li_at()
    ok, reason = cookie_looks_valid(current)
    if ok and current:
        return current, f"env_valid:{reason}"

    refreshed = refresh_li_at_from_profile(headless=True)
    if refreshed:
        ok2, reason2 = cookie_looks_valid(refreshed)
        if ok2:
            return refreshed, f"profile_refreshed:{reason2}"

    if allow_interactive:
        token = interactive_login(timeout_sec=timeout_sec, headed=True)
        return token, "interactive_login"

    return None, f"needs_reauth:{reason}"
