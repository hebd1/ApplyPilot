"""ApplyPilot CLI — the main entry point."""

from __future__ import annotations

import logging
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from applypilot import __version__

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)

app = typer.Typer(
    name="applypilot",
    help="AI-powered end-to-end job application pipeline.",
    no_args_is_help=True,
)
console = Console()
log = logging.getLogger(__name__)

# Valid pipeline stages (in execution order)
VALID_STAGES = ("discover", "enrich", "score", "tailor", "cover", "pdf")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bootstrap() -> None:
    """Common setup: load env, create dirs, init DB."""
    from applypilot.config import load_env, ensure_dirs
    from applypilot.database import init_db

    load_env()
    ensure_dirs()
    init_db()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"[bold]applypilot[/bold] {__version__}")
        raise typer.Exit()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-V",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """ApplyPilot — AI-powered end-to-end job application pipeline."""


@app.command()
def init() -> None:
    """Run the first-time setup wizard (profile, resume, search config)."""
    from applypilot.wizard.init import run_wizard

    run_wizard()


@app.command()
def run(
    stages: Optional[list[str]] = typer.Argument(
        None,
        help=(
            "Pipeline stages to run. "
            f"Valid: {', '.join(VALID_STAGES)}, all. "
            "Defaults to 'all' if omitted."
        ),
    ),
    min_score: int = typer.Option(7, "--min-score", help="Minimum fit score for tailor/cover stages."),
    workers: int = typer.Option(1, "--workers", "-w", help="Parallel threads for discovery/enrichment stages."),
    stream: bool = typer.Option(False, "--stream", help="Run stages concurrently (streaming mode)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview stages without executing."),
    validation: str = typer.Option(
        "normal",
        "--validation",
        help=(
            "Validation strictness for tailor/cover stages. "
            "strict: banned words = errors, judge must pass. "
            "normal: banned words = warnings only (default, recommended for Gemini free tier). "
            "lenient: banned words ignored, LLM judge skipped (fastest, fewest API calls)."
        ),
    ),
) -> None:
    """Run pipeline stages: discover, enrich, score, tailor, cover, pdf."""
    _bootstrap()

    from applypilot.pipeline import run_pipeline

    stage_list = stages if stages else ["all"]

    # Validate stage names
    for s in stage_list:
        if s != "all" and s not in VALID_STAGES:
            console.print(
                f"[red]Unknown stage:[/red] '{s}'. "
                f"Valid stages: {', '.join(VALID_STAGES)}, all"
            )
            raise typer.Exit(code=1)

    # Gate AI stages behind Tier 2
    llm_stages = {"score", "tailor", "cover"}
    if any(s in stage_list for s in llm_stages) or "all" in stage_list:
        from applypilot.config import check_tier
        check_tier(2, "AI scoring/tailoring")

    # Validate the --validation flag value
    valid_modes = ("strict", "normal", "lenient")
    if validation not in valid_modes:
        console.print(
            f"[red]Invalid --validation value:[/red] '{validation}'. "
            f"Choose from: {', '.join(valid_modes)}"
        )
        raise typer.Exit(code=1)

    result = run_pipeline(
        stages=stage_list,
        min_score=min_score,
        dry_run=dry_run,
        stream=stream,
        workers=workers,
        validation_mode=validation,
    )

    if result.get("errors"):
        raise typer.Exit(code=1)


@app.command()
def apply(
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Max applications to submit."),
    workers: int = typer.Option(1, "--workers", "-w", help="Number of parallel browser workers."),
    min_score: int = typer.Option(7, "--min-score", help="Minimum fit score for job selection."),
    model: str = typer.Option("auto", "--model", "-m", help="Apply agent model (auto for Cursor)."),
    continuous: bool = typer.Option(False, "--continuous", "-c", help="Run forever, polling for new jobs."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview actions without submitting."),
    headless: bool = typer.Option(False, "--headless", help="Run browsers in headless mode."),
    url: Optional[str] = typer.Option(None, "--url", help="Apply to a specific job URL."),
    gen: bool = typer.Option(False, "--gen", help="Generate prompt file for manual debugging instead of running."),
    mark_applied: Optional[str] = typer.Option(None, "--mark-applied", help="Manually mark a job URL as applied."),
    mark_failed: Optional[str] = typer.Option(None, "--mark-failed", help="Manually mark a job URL as failed (provide URL)."),
    fail_reason: Optional[str] = typer.Option(None, "--fail-reason", help="Reason for --mark-failed."),
    reset_failed: bool = typer.Option(False, "--reset-failed", help="Reset all failed jobs for retry."),
) -> None:
    """Launch auto-apply to submit job applications."""
    _bootstrap()

    from applypilot.config import check_tier, PROFILE_PATH as _profile_path
    from applypilot.database import get_connection

    # --- Utility modes (no Chrome/agent needed) ---

    if mark_applied:
        from applypilot.apply.launcher import mark_job
        mark_job(mark_applied, "applied")
        console.print(f"[green]Marked as applied:[/green] {mark_applied}")
        return

    if mark_failed:
        from applypilot.apply.launcher import mark_job
        mark_job(mark_failed, "failed", reason=fail_reason)
        console.print(f"[yellow]Marked as failed:[/yellow] {mark_failed} ({fail_reason or 'manual'})")
        return

    if reset_failed:
        from applypilot.apply.launcher import reset_failed as do_reset
        count = do_reset()
        console.print(f"[green]Reset {count} failed job(s) for retry.[/green]")
        return

    # --- Full apply mode ---

    # Check 1: Tier 3 required (Cursor API + Chrome)
    check_tier(3, "auto-apply")

    # Check 2: Profile exists
    if not _profile_path.exists():
        console.print(
            "[red]Profile not found.[/red]\n"
            "Run [bold]applypilot init[/bold] to create your profile first."
        )
        raise typer.Exit(code=1)

    # Check 3: Tailored resumes exist (skip for --gen with --url)
    if not (gen and url):
        conn = get_connection()
        ready = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE tailored_resume_path IS NOT NULL AND applied_at IS NULL"
        ).fetchone()[0]
        if ready == 0:
            console.print(
                "[red]No tailored resumes ready.[/red]\n"
                "Run [bold]applypilot run score tailor[/bold] first to prepare applications."
            )
            raise typer.Exit(code=1)

    if gen:
        from applypilot.apply.launcher import gen_prompt, BASE_CDP_PORT
        target = url or ""
        if not target:
            console.print("[red]--gen requires --url to specify which job.[/red]")
            raise typer.Exit(code=1)
        prompt_file = gen_prompt(target, min_score=min_score, model=model)
        if not prompt_file:
            console.print("[red]No matching job found for that URL.[/red]")
            raise typer.Exit(code=1)
        mcp_path = _profile_path.parent / ".mcp-apply-0.json"
        console.print(f"[green]Wrote prompt to:[/green] {prompt_file}")
        console.print(f"\n[bold]Run manually:[/bold]")
        console.print(
            f"  Use a Cursor agent with the prompt file and MCP config above."
        )
        return

    from applypilot.apply.launcher import main as apply_main
    from applypilot.apply.cursor_apply import get_apply_backend

    backend = get_apply_backend()
    apply_model = model if not (backend == "cursor" and model in ("sonnet", "haiku", "opus")) else "auto"

    effective_limit = limit if limit is not None else (0 if continuous else 1)

    console.print("\n[bold blue]Launching Auto-Apply[/bold blue]")
    console.print(f"  Backend:  {backend}")
    console.print(f"  Limit:    {'unlimited' if continuous else effective_limit}")
    console.print(f"  Workers:  {workers}")
    console.print(f"  Model:    {apply_model}")
    console.print(f"  Headless: {headless}")
    console.print(f"  Dry run:  {dry_run}")
    if url:
        console.print(f"  Target:   {url}")
    console.print()

    apply_main(
        limit=effective_limit,
        target_url=url,
        min_score=min_score,
        headless=headless,
        model=apply_model,
        dry_run=dry_run,
        continuous=continuous,
        workers=workers,
    )


@app.command()
def status() -> None:
    """Show pipeline statistics from the database."""
    _bootstrap()

    from applypilot.database import get_stats

    stats = get_stats()

    console.print("\n[bold]ApplyPilot Pipeline Status[/bold]\n")

    # Summary table
    summary = Table(title="Pipeline Overview", show_header=True, header_style="bold cyan")
    summary.add_column("Metric", style="bold")
    summary.add_column("Count", justify="right")

    summary.add_row("Total jobs discovered", str(stats["total"]))
    summary.add_row("With full description", str(stats["with_description"]))
    summary.add_row("Pending enrichment", str(stats["pending_detail"]))
    summary.add_row("Enrichment errors", str(stats["detail_errors"]))
    summary.add_row("Scored by LLM", str(stats["scored"]))
    summary.add_row("Pending scoring", str(stats["unscored"]))
    summary.add_row("Tailored resumes", str(stats["tailored"]))
    summary.add_row("Pending tailoring (7+)", str(stats["untailored_eligible"]))
    summary.add_row("Cover letters", str(stats["with_cover_letter"]))
    summary.add_row("Ready to apply", str(stats["ready_to_apply"]))
    summary.add_row("Applied", str(stats["applied"]))
    summary.add_row("Apply errors", str(stats["apply_errors"]))

    console.print(summary)

    from applypilot.apply.cursor_apply import gmail_mcp_token_healthy
    from applypilot.apply.health import apply_is_blocked, read_apply_health
    from applypilot.database import get_connection

    last_applied = get_connection().execute(
        "SELECT applied_at, title, company FROM jobs "
        "WHERE apply_status = 'applied' OR applied_at IS NOT NULL "
        "ORDER BY datetime(applied_at) DESC LIMIT 1"
    ).fetchone()
    if last_applied and last_applied["applied_at"]:
        console.print(
            f"  Last applied: [bold]{last_applied['applied_at'][:19].replace('T', ' ')}[/bold]  "
            f"[dim]{last_applied['title'] or ''}[/dim]"
        )
    else:
        console.print("  Last applied: [dim]none[/dim]")

    gmail_ok, gmail_detail = gmail_mcp_token_healthy()
    health = read_apply_health()
    if not gmail_ok:
        console.print(
            f"  [red]Daily apply blocked:[/red] Gmail token is dead ({gmail_detail}). "
            "Re-run: [bold]bash scripts/gmail_oauth_readonly.sh[/bold]"
        )
    elif apply_is_blocked(health):
        console.print(
            f"  [red]Daily apply blocked:[/red] {health.get('reason', 'unknown')} — "
            f"{health.get('detail') or health.get('updated_at') or ''}"
        )
    elif health:
        reason = health.get("reason") or "ok"
        style = "yellow" if reason == "queue_empty" else "green"
        console.print(
            f"  Daily apply health: [{style}]{health.get('status', 'ok')}[/{style}] "
            f"[dim]{reason} {health.get('updated_at', '')}[/dim]"
        )

    # Score distribution
    if stats["score_distribution"]:
        dist_table = Table(title="\nScore Distribution", show_header=True, header_style="bold yellow")
        dist_table.add_column("Score", justify="center")
        dist_table.add_column("Count", justify="right")
        dist_table.add_column("Bar")

        max_count = max(count for _, count in stats["score_distribution"]) or 1
        for score, count in stats["score_distribution"]:
            bar_len = int(count / max_count * 30)
            if score >= 7:
                color = "green"
            elif score >= 5:
                color = "yellow"
            else:
                color = "red"
            bar = f"[{color}]{'=' * bar_len}[/{color}]"
            dist_table.add_row(str(score), str(count), bar)

        console.print(dist_table)

    # By site
    if stats["by_site"]:
        site_table = Table(title="\nJobs by Source", show_header=True, header_style="bold magenta")
        site_table.add_column("Site")
        site_table.add_column("Count", justify="right")

        for site, count in stats["by_site"]:
            site_table.add_row(site or "Unknown", str(count))

        console.print(site_table)

    console.print()


@app.command()
def dashboard() -> None:
    """Generate and open the HTML dashboard in your browser."""
    _bootstrap()

    from applypilot.view import open_dashboard

    open_dashboard()


@app.command("linkedin-auth")
def linkedin_auth(
    set_cookie: Optional[str] = typer.Option(
        None, "--set", help="Save a pasted li_at cookie to ~/.applypilot/.env",
    ),
    check: bool = typer.Option(False, "--check", help="Validate the current cookie only."),
    refresh: bool = typer.Option(
        False, "--refresh",
        help="Pull a rotated li_at from the persistent LinkedIn Chrome profile.",
    ),
    login: bool = typer.Option(
        False, "--login",
        help="Open Chrome and wait for you to sign in to LinkedIn.",
    ),
    timeout: int = typer.Option(300, "--timeout", help="Seconds to wait for interactive login."),
    headless_refresh: bool = typer.Option(
        True, "--headless-refresh/--headed-refresh",
        help="Run profile refresh headless (default) or headed.",
    ),
) -> None:
    """Capture or refresh the LinkedIn li_at cookie used for ATS URL resolution.

    Cookies expire. Prefer --login once (saves a persistent Chrome profile), then
    --refresh later to pull rotated cookies without pasting. Never commit li_at.
    """
    _bootstrap()
    from applypilot.discovery import linkedin_auth as li_auth

    if set_cookie:
        path = li_auth.save_li_at(set_cookie)
        ok, reason = li_auth.cookie_looks_valid()
        status = "[green]valid[/green]" if ok else f"[yellow]saved but {reason}[/yellow]"
        console.print(f"Saved LINKEDIN_LI_AT to {path} ({status})")
        return

    if check:
        present = bool(li_auth.get_li_at())
        if not present:
            console.print("[red]No LINKEDIN_LI_AT in env.[/red] Run: applypilot linkedin-auth --login")
            raise typer.Exit(code=1)
        ok, reason = li_auth.cookie_looks_valid()
        if ok:
            console.print(f"[green]LinkedIn cookie OK[/green] ({reason})")
            raise typer.Exit(code=0)
        console.print(f"[red]LinkedIn cookie invalid[/red] ({reason})")
        console.print("Refresh: [bold]applypilot linkedin-auth --refresh[/bold]")
        console.print("Or login: [bold]applypilot linkedin-auth --login[/bold]")
        raise typer.Exit(code=1)

    if refresh:
        console.print("Refreshing li_at from persistent LinkedIn Chrome profile...")
        token = li_auth.refresh_li_at_from_profile(headless=headless_refresh)
        if not token:
            console.print("[red]Profile has no LinkedIn session and LINKEDIN_LI_AT is missing or invalid.[/red]")
            console.print("Run: [bold]applypilot linkedin-auth --login[/bold]")
            raise typer.Exit(code=1)
        ok, reason = li_auth.cookie_looks_valid(token)
        if ok:
            console.print(f"[green]LinkedIn li_at ready[/green] ({reason})")
            console.print("[dim]If morning --refresh used to fail, the .env cookie was re-seeded into linkedin-chrome.[/dim]")
            raise typer.Exit(code=0)
        console.print(f"[yellow]Saved cookie but validation failed ({reason}). Try --login.[/yellow]")
        raise typer.Exit(code=1)

    if login:
        console.print(
            "Opening LinkedIn in Chrome. Sign in if prompted; "
            f"waiting up to {timeout}s for li_at..."
        )
        try:
            li_auth.interactive_login(timeout_sec=timeout, headed=True)
        except TimeoutError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1)
        ok, reason = li_auth.cookie_looks_valid()
        if ok:
            console.print(f"[green]LinkedIn login captured[/green] ({reason})")
            raise typer.Exit(code=0)
        console.print(f"[yellow]Cookie saved but validation failed ({reason}).[/yellow]")
        raise typer.Exit(code=1)

    # Default: validate → refresh profile → interactive login if needed
    console.print("Ensuring LinkedIn session...")
    token, status = li_auth.ensure_li_at(allow_interactive=True, timeout_sec=timeout)
    if token:
        console.print(f"[green]LinkedIn session ready[/green] ({status})")
        raise typer.Exit(code=0)
    console.print(f"[red]Could not obtain LinkedIn session[/red] ({status})")
    raise typer.Exit(code=1)


@app.command()
def doctor() -> None:
    """Check your setup and diagnose missing requirements."""
    import shutil
    from applypilot.config import (
        load_env, PROFILE_PATH, RESUME_PATH, RESUME_PDF_PATH,
        SEARCH_CONFIG_PATH, ENV_PATH, get_chrome_path,
    )

    load_env()

    ok_mark = "[green]OK[/green]"
    fail_mark = "[red]MISSING[/red]"
    warn_mark = "[yellow]WARN[/yellow]"

    results: list[tuple[str, str, str]] = []  # (check, status, note)

    # --- Tier 1 checks ---
    # Profile
    if PROFILE_PATH.exists():
        results.append(("profile.json", ok_mark, str(PROFILE_PATH)))
    else:
        results.append(("profile.json", fail_mark, "Run 'applypilot init' to create"))

    # Resume
    if RESUME_PATH.exists():
        results.append(("resume.txt", ok_mark, str(RESUME_PATH)))
    elif RESUME_PDF_PATH.exists():
        results.append(("resume.txt", warn_mark, "Only PDF found — plain-text needed for AI stages"))
    else:
        results.append(("resume.txt", fail_mark, "Run 'applypilot init' to add your resume"))

    # Search config
    if SEARCH_CONFIG_PATH.exists():
        results.append(("searches.yaml", ok_mark, str(SEARCH_CONFIG_PATH)))
    else:
        results.append(("searches.yaml", warn_mark, "Will use example config — run 'applypilot init'"))

    # jobspy (discovery dep installed separately)
    try:
        import jobspy  # noqa: F401
        results.append(("python-jobspy", ok_mark, "Job board scraping available"))
    except ImportError:
        results.append(("python-jobspy", warn_mark,
                        "pip install --no-deps python-jobspy && pip install pydantic tls-client requests markdownify regex"))

    # --- Tier 2 checks ---
    import os
    has_cursor = bool(os.environ.get("CURSOR_API_KEY"))
    has_openrouter = bool(os.environ.get("OPENROUTER_API_KEY"))
    has_gemini = bool(os.environ.get("GEMINI_API_KEY"))
    has_openai = bool(os.environ.get("OPENAI_API_KEY"))
    has_local = bool(os.environ.get("LLM_URL"))
    if has_cursor:
        model = os.environ.get("LLM_MODEL", "auto")
        results.append(("LLM API key", ok_mark, f"Cursor Auto ({model})"))
    elif has_openrouter:
        model = os.environ.get("LLM_MODEL", "openrouter/free")
        results.append(("LLM API key", ok_mark, f"OpenRouter ({model})"))
    elif has_gemini:
        model = os.environ.get("LLM_MODEL", "gemini-2.0-flash")
        results.append(("LLM API key", ok_mark, f"Gemini ({model})"))
    elif has_openai:
        model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
        results.append(("LLM API key", ok_mark, f"OpenAI ({model})"))
    elif has_local:
        results.append(("LLM API key", ok_mark, f"Local: {os.environ.get('LLM_URL')}"))
    else:
        results.append(("LLM API key", fail_mark,
                        "Set CURSOR_API_KEY or OPENROUTER_API_KEY in ~/.applypilot/.env (run 'applypilot init')"))

    # --- Tier 3 checks ---
    from applypilot.apply.cursor_apply import get_apply_backend
    apply_backend = get_apply_backend()

    if apply_backend == "cursor" and has_cursor:
        results.append(("Apply agent", ok_mark, "Cursor SDK + Playwright + Gmail MCP"))
    else:
        results.append(("Apply agent", fail_mark,
                        "Set CURSOR_API_KEY in ~/.applypilot/.env (auto-apply)"))

    # Chrome
    try:
        chrome_path = get_chrome_path()
        results.append(("Chrome/Chromium", ok_mark, chrome_path))
    except FileNotFoundError:
        results.append(("Chrome/Chromium", fail_mark,
                        "Install Chrome or set CHROME_PATH env var (needed for auto-apply)"))

    # Node.js / npx (for Playwright MCP)
    npx_bin = shutil.which("npx")
    if npx_bin:
        results.append(("Node.js (npx)", ok_mark, npx_bin))
    else:
        results.append(("Node.js (npx)", fail_mark,
                        "Install Node.js 18+ from nodejs.org (needed for auto-apply)"))

    # CapSolver (optional)
    capsolver = os.environ.get("CAPSOLVER_API_KEY")
    if capsolver:
        # Live balance check when possible (non-fatal on network errors)
        try:
            import json
            import urllib.request
            payload = json.dumps({"clientKey": capsolver}).encode()
            req = urllib.request.Request(
                "https://api.capsolver.com/getBalance",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            if data.get("errorId") == 0:
                bal = data.get("balance")
                try:
                    low = float(bal) < 2
                except (TypeError, ValueError):
                    low = False
                if low:
                    results.append(("CapSolver API key", warn_mark,
                                    f"balance ${bal} — replenish before CAPTCHA jobs fail"))
                else:
                    results.append(("CapSolver API key", ok_mark, f"balance ${bal}"))
            else:
                results.append(("CapSolver API key", fail_mark,
                                f"{data.get('errorCode') or 'invalid key'}"))
        except Exception as exc:
            results.append(("CapSolver API key", ok_mark,
                            f"set (balance check failed: {exc})"))
    else:
        results.append(("CapSolver API key", "[dim]optional[/dim]",
                        "Set CAPSOLVER_API_KEY in .env for CAPTCHA solving"))

    # LinkedIn apply-URL session cookie (optional; expires — refresh via linkedin-auth)
    from applypilot.discovery import linkedin_auth as li_auth
    if li_auth.get_li_at():
        ok_li, detail_li = li_auth.cookie_looks_valid()
        if ok_li:
            results.append(("LinkedIn li_at", ok_mark,
                            f"{detail_li} — .env cookie valid; --refresh re-seeds linkedin-chrome if needed"))
        else:
            results.append(("LinkedIn li_at", fail_mark,
                            f"{detail_li} — run: applypilot linkedin-auth --login"))
    else:
        results.append(("LinkedIn li_at", "[dim]optional[/dim]",
                        "For LinkedIn→ATS URL resolve: applypilot linkedin-auth --login"))

    # Gmail MCP OAuth — required for ATS email OTP / verification links during apply
    from applypilot.apply.cursor_apply import (
        gmail_mcp_authenticated,
        gmail_mcp_credentials_path,
        gmail_mcp_token_healthy,
    )
    if gmail_mcp_authenticated():
        ok, detail = gmail_mcp_token_healthy()
        if ok:
            results.append(("Gmail MCP auth", ok_mark, f"{gmail_mcp_credentials_path()} ({detail})"))
        else:
            results.append(("Gmail MCP auth", fail_mark,
                            f"token dead — {detail}. Re-run: bash scripts/gmail_oauth_readonly.sh"))
    else:
        results.append(("Gmail MCP auth", fail_mark,
                        "Missing ~/.gmail-mcp/credentials.json. "
                        "Run: bash scripts/gmail_oauth_readonly.sh "
                        "(readonly OTP / verify-link access; "
                        "APPLY_ALLOW_GMAIL_SEND=1 only with explicit consent to send)"))

    # --- Render results ---
    console.print()
    console.print("[bold]ApplyPilot Doctor[/bold]\n")

    col_w = max(len(r[0]) for r in results) + 2
    for check, status, note in results:
        pad = " " * (col_w - len(check))
        console.print(f"  {check}{pad}{status}  [dim]{note}[/dim]")

    console.print()

    # Tier summary
    from applypilot.config import get_tier, TIER_LABELS
    tier = get_tier()
    console.print(f"[bold]Current tier: Tier {tier} — {TIER_LABELS[tier]}[/bold]")

    if tier == 1:
        console.print("[dim]  → Tier 2 unlocks: scoring, tailoring, cover letters (needs LLM API key)[/dim]")
        console.print("[dim]  → Tier 3 unlocks: auto-apply (needs Chrome + Node.js + CURSOR_API_KEY)[/dim]")
    elif tier == 2:
        console.print("[dim]  → Tier 3 unlocks: auto-apply (needs Chrome + Node.js + CURSOR_API_KEY)[/dim]")

    console.print()


if __name__ == "__main__":
    app()
