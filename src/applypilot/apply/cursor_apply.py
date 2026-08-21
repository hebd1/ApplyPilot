"""Auto-apply via Cursor SDK agent + Playwright/Gmail MCP."""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from cursor_sdk import Agent
from cursor_sdk.types import AgentOptions, LocalAgentOptions, SendOptions, StdioMcpServerConfig

from applypilot import config
from applypilot.apply import prompt as prompt_mod
from applypilot.apply.dashboard import add_event, get_state, update_state
from applypilot.apply.launcher import parse_apply_output
from applypilot.apply.materials import resolve_resume_text
from applypilot.job_meta import display_company

logger = logging.getLogger(__name__)

_active_runs: dict[int, object] = {}
_active_lock = threading.Lock()

# Allow search/read (+ send for email-only apps); no mailbox mutation.
_GMAIL_MCP_PACKAGE = "@gongrzhe/server-gmail-autoauth-mcp"


def get_apply_backend() -> str:
    """Return 'cursor' for the auto-apply agent."""
    config.load_env()
    explicit = os.environ.get("APPLY_BACKEND", "").strip().lower()
    if explicit in ("cursor",):
        return explicit
    if os.environ.get("CURSOR_API_KEY"):
        return "cursor"
    return "cursor"


def gmail_mcp_credentials_path() -> Path:
    """Cached OAuth token path used by @gongrzhe/server-gmail-autoauth-mcp."""
    return Path.home() / ".gmail-mcp" / "credentials.json"


def gmail_mcp_authenticated() -> bool:
    return gmail_mcp_credentials_path().is_file()


def gmail_mcp_token_healthy() -> tuple[bool, str]:
    """Refresh the Gmail MCP token and report whether Stage 6 can read mail.

    Returns:
        (ok, detail) — ok is False on missing/revoked tokens (invalid_grant).
    """
    import json
    import urllib.error
    import urllib.parse
    import urllib.request
    from datetime import datetime, timedelta, timezone

    creds_path = gmail_mcp_credentials_path()
    keys_path = Path.home() / ".gmail-mcp" / "gcp-oauth.keys.json"
    if not creds_path.is_file():
        return False, f"missing {creds_path}"
    if not keys_path.is_file():
        return False, f"missing {keys_path}"

    try:
        token = json.loads(creds_path.read_text(encoding="utf-8"))
        keys = json.loads(keys_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"unreadable Gmail OAuth files: {exc}"

    installed = keys.get("installed") or keys.get("web") or {}
    client_id = installed.get("client_id")
    client_secret = installed.get("client_secret")
    token_uri = installed.get("token_uri") or "https://oauth2.googleapis.com/token"
    refresh = token.get("refresh_token")
    if not client_id or not client_secret:
        return False, "invalid gcp-oauth.keys.json"
    if not refresh:
        return False, "no refresh_token — re-run bash scripts/gmail_oauth_readonly.sh"

    body = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh,
            "grant_type": "refresh_token",
        }
    ).encode()
    req = urllib.request.Request(
        token_uri,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        if exc.code == 400 and "invalid_grant" in detail:
            return False, "refresh failed HTTP 400: invalid_grant (token expired or revoked)"
        return False, f"refresh failed HTTP {exc.code}: {detail}"
    except Exception as exc:
        return False, f"refresh failed: {exc}"

    access = data.get("access_token")
    if not access:
        return False, "refresh returned no access_token"
    token["access_token"] = access
    if "expires_in" in data:
        exp = datetime.now(timezone.utc) + timedelta(seconds=int(data["expires_in"]))
        token["expiry_date"] = int(exp.timestamp() * 1000)
    if data.get("refresh_token"):
        token["refresh_token"] = data["refresh_token"]
    try:
        creds_path.write_text(json.dumps(token, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        return False, f"could not write refreshed token: {exc}"
    return True, "gmail.readonly refresh OK"


def gmail_send_allowed() -> bool:
    """True only when the user explicitly opts in to outbound Gmail send.

    Default is read-only: search/read for OTPs. Delete/modify/label/filter/
    settings changes are never allowed. Send requires APPLY_ALLOW_GMAIL_SEND=1
    in ~/.applypilot/.env (or the process environment).
    """
    config.load_env()
    return os.environ.get("APPLY_ALLOW_GMAIL_SEND", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def cancel_active_run(worker_id: int) -> None:
    """Cancel an in-flight Cursor agent run (Ctrl+C skip)."""
    with _active_lock:
        run = _active_runs.pop(worker_id, None)
    if run is not None:
        try:
            run.cancel()
        except Exception:
            logger.debug("Failed to cancel Cursor run for worker %d", worker_id, exc_info=True)


def cancel_all_active_runs() -> None:
    with _active_lock:
        runs = list(_active_runs.items())
        _active_runs.clear()
    for _wid, run in runs:
        try:
            run.cancel()
        except Exception:
            pass


def _make_mcp_servers(cdp_port: int) -> dict[str, StdioMcpServerConfig]:
    viewport = config.DEFAULTS["viewport"]
    return {
        "playwright": StdioMcpServerConfig(
            command="npx",
            args=[
                "-y",
                "@playwright/mcp@latest",
                f"--cdp-endpoint=http://localhost:{cdp_port}",
                f"--viewport-size={viewport}",
            ],
        ),
        "gmail": StdioMcpServerConfig(
            command="npx",
            args=["-y", _GMAIL_MCP_PACKAGE],
        ),
    }


def _read_resume_text(job: dict) -> str:
    return resolve_resume_text(job)

def run_job_cursor(
    job: dict,
    port: int,
    worker_id: int = 0,
    model: str = "composer-2.5",
    dry_run: bool = False,
) -> tuple[str, int]:
    """Run one job application using a Cursor agent with Playwright MCP."""
    config.load_env()
    api_key = os.environ.get("CURSOR_API_KEY", "")
    if not api_key:
        raise RuntimeError("CURSOR_API_KEY required for Cursor auto-apply")

    resume_text = _read_resume_text(job)
    agent_prompt = prompt_mod.build_prompt(
        job=job, tailored_resume=resume_text, dry_run=dry_run,
    )

    worker_dir = config.APPLY_WORKER_DIR / f"worker-{worker_id}"
    worker_dir.mkdir(parents=True, exist_ok=True)

    update_state(
        worker_id, status="applying", job_title=job["title"],
        company=display_company(job), score=job.get("fit_score", 0),
        start_time=time.time(), actions=0, last_action="cursor agent starting",
    )
    add_event(f"[W{worker_id}] Cursor apply: {job['title'][:40]} @ {display_company(job)}")

    worker_log = config.LOG_DIR / f"worker-{worker_id}.log"
    ts_header = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_header = (
        f"\n{'=' * 60}\n"
        f"[CURSOR] [{ts_header}] {job['title']} @ {job.get('site', '')}\n"
        f"URL: {job.get('application_url') or job['url']}\n"
        f"{'=' * 60}\n"
    )
    worker_log.write_text(
        (worker_log.read_text(encoding="utf-8") if worker_log.exists() else "") + log_header,
        encoding="utf-8",
    )

    start = time.time()
    output_parts: list[str] = []
    mcp_servers = _make_mcp_servers(port)

    try:
        with Agent.create(
            AgentOptions(
                api_key=api_key,
                model=model,
                local=LocalAgentOptions(cwd=str(worker_dir), setting_sources=[]),
                mcp_servers=mcp_servers,
            ),
        ) as agent:
            run = agent.send(
                agent_prompt,
                SendOptions(mcp_servers=mcp_servers),
            )
            with _active_lock:
                _active_runs[worker_id] = run

            for message in run.messages():
                msg_type = getattr(message, "type", "")
                if msg_type != "assistant":
                    continue
                content = getattr(getattr(message, "message", None), "content", ())
                for block in content:
                    block_type = getattr(block, "type", "")
                    if block_type == "text":
                        text = getattr(block, "text", "")
                        if text:
                            output_parts.append(text)
                            with open(worker_log, "a", encoding="utf-8") as lf:
                                lf.write(text + "\n")
                    elif block_type == "tool_use":
                        name = getattr(block, "name", "")
                        desc = (
                            re.sub(r"^mcp__playwright__", "", name)
                            .replace("mcp__gmail__", "gmail:")
                        )
                        ws = get_state(worker_id)
                        cur_actions = ws.actions if ws else 0
                        update_state(
                            worker_id, actions=cur_actions + 1,
                            last_action=desc[:35] or "tool",
                        )
                        with open(worker_log, "a", encoding="utf-8") as lf:
                            lf.write(f"  >> {desc}\n")

            result = run.wait()
            if result.result:
                output_parts.append(result.result)

            output = "\n".join(output_parts)
            duration_ms = int((time.time() - start) * 1000)

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            job_log = config.LOG_DIR / (
                f"cursor_{ts}_w{worker_id}_{job.get('site', 'unknown')[:20]}.txt"
            )
            job_log.write_text(output, encoding="utf-8")

            if result.status == "error":
                add_event(f"[W{worker_id}] CURSOR ERROR: {job['title'][:30]}")
                update_state(worker_id, status="failed", last_action="cursor error")
                return f"failed:cursor agent error", duration_ms

            return parse_apply_output(output, worker_id, job, duration_ms)

    except Exception as exc:
        duration_ms = int((time.time() - start) * 1000)
        logger.exception("Cursor apply failed for %s", job.get("title"))
        add_event(f"[W{worker_id}] FAILED: {exc}")
        update_state(worker_id, status="failed", last_action=str(exc)[:35])
        return f"failed:{exc}", duration_ms
    finally:
        with _active_lock:
            _active_runs.pop(worker_id, None)
