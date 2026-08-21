#!/usr/bin/env bash
# Daily ApplyPilot job: one high-quality ATS apply (default).
# Intended for Windows Task / WSL cron (see install_daily_apply_*.sh).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${APPLYPILOT_DIR:-$HOME/.applypilot}"
LOG_DIR="$APP_DIR/logs"
LIMIT="${DAILY_APPLY_LIMIT:-1}"
MIN_SCORE="${DAILY_APPLY_MIN_SCORE:-8}"
# Stable path so Windows Task + cron share one lock (XDG_RUNTIME_DIR differs).
LOCK_FILE="$LOG_DIR/daily_apply.lock"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
LOG_FILE="$LOG_DIR/daily_apply-$TIMESTAMP.log"

write_health() {
  # status, reason, optional detail
  APPLY_HEALTH_STATUS="$1" APPLY_HEALTH_REASON="$2" APPLY_HEALTH_DETAIL="${3:-}" \
  APPLY_HEALTH_LOG="$LOG_FILE" \
  "$REPO/.venv/bin/python" -c '
import os
from applypilot.apply.health import write_apply_health
write_apply_health(
    status=os.environ["APPLY_HEALTH_STATUS"],
    reason=os.environ["APPLY_HEALTH_REASON"],
    detail=os.environ.get("APPLY_HEALTH_DETAIL", ""),
    log_file=os.environ.get("APPLY_HEALTH_LOG", ""),
)
' || true
}

# Quality gates for Stage 6 (acquire_job / worker_loop)
export DAILY_APPLY_ATS_ONLY="${DAILY_APPLY_ATS_ONLY:-1}"
export APPLY_ATS_ONLY="${APPLY_ATS_ONLY:-$DAILY_APPLY_ATS_ONLY}"
export APPLY_SUCCESS_QUOTA="${APPLY_SUCCESS_QUOTA:-1}"
export APPLY_MAX_ATTEMPTS="${APPLY_MAX_ATTEMPTS:-8}"

mkdir -p "$LOG_DIR"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "daily_apply: another run is in progress; exiting" | tee -a "$LOG_DIR/daily_apply-skipped.log"
  exit 0
fi

cd "$REPO"

{
  echo "========== ApplyPilot daily apply =========="
  echo "started: $(date -Is)"
  echo "repo:    $REPO"
  echo "limit:   $LIMIT success(es)  min_score: $MIN_SCORE"
  echo "ats_only: $APPLY_ATS_ONLY  success_quota: $APPLY_SUCCESS_QUOTA  max_attempts: $APPLY_MAX_ATTEMPTS"
  echo "tz:      ${TZ:-$(cat /etc/timezone 2>/dev/null || echo unknown)}"
  echo

  if [[ ! -x "$REPO/.venv/bin/applypilot" ]]; then
    echo "ERROR: missing $REPO/.venv/bin/applypilot" >&2
    exit 1
  fi

  echo "==> purge unapplyable / excluded / stuck"
  "$REPO/.venv/bin/python" "$REPO/scripts/purge_unapplyable_queue.py" || echo "WARN: purge exited $?"

  echo "==> gmail readonly preflight (OTP / verification links)"
  if ! "$REPO/.venv/bin/python" - <<'PY'
from applypilot.apply.cursor_apply import gmail_mcp_token_healthy
ok, detail = gmail_mcp_token_healthy()
print(detail)
raise SystemExit(0 if ok else 1)
PY
  then
    echo "ERROR: Gmail MCP token unhealthy — re-auth with: bash scripts/gmail_oauth_readonly.sh" >&2
    echo "        Daily apply needs readonly Gmail for ATS email verification." >&2
    if [[ "${DAILY_APPLY_REQUIRE_GMAIL:-1}" == "1" ]]; then
      write_health blocked gmail_auth_required "Token expired or revoked. Re-run: bash scripts/gmail_oauth_readonly.sh"
      exit 1
    fi
    echo "WARN: continuing without healthy Gmail (DAILY_APPLY_REQUIRE_GMAIL=0)"
  fi

  # Refresh LinkedIn li_at from the persistent Chrome profile (non-interactive).
  # Enables LinkedIn→ATS apply URL resolution during discover/enrich.
  # If the profile is logged out, run: applypilot linkedin-auth --login
  if [[ "${DAILY_APPLY_LINKEDIN_REFRESH:-1}" == "1" ]]; then
    echo "==> linkedin session refresh"
    if "$REPO/.venv/bin/applypilot" linkedin-auth --refresh; then
      echo "    LinkedIn li_at refreshed"
    else
      echo "WARN: LinkedIn refresh failed — company-website apply URLs may not resolve"
      echo "      Re-auth interactively: $REPO/.venv/bin/applypilot linkedin-auth --login"
      if [[ "${DAILY_APPLY_REQUIRE_LINKEDIN:-0}" == "1" ]]; then
        exit 1
      fi
    fi
  fi

  # Optional: refresh discovery before scoring (off by default — slow / flaky).
  if [[ "${DAILY_APPLY_DISCOVER:-0}" == "1" ]]; then
    echo "==> discover"
    "$REPO/.venv/bin/applypilot" run discover || echo "WARN: discover exited $?"
  fi

  # Prepare materials for already high-scoring jobs only.
  # Do NOT run `score` here — unscored backlog can be 1000+ jobs and blocks apply for hours.
  if [[ "${DAILY_APPLY_PREP:-1}" == "1" ]]; then
    echo "==> tailor cover pdf (capped score; set DAILY_APPLY_SCORE=1 for full backlog)"
    stages=(tailor cover pdf)
    score_limit="${DAILY_APPLY_SCORE_LIMIT:-8}"
    if [[ "${DAILY_APPLY_SCORE:-0}" == "1" ]]; then
      stages=(score tailor cover pdf)
      echo "    (DAILY_APPLY_SCORE=1 — scoring entire unscored backlog)"
    elif [[ "${score_limit}" != "0" ]]; then
      stages=(score tailor cover pdf)
      export SCORE_LIMIT="$score_limit"
      export DAILY_APPLY_SCORE_LIMIT="$score_limit"
      echo "    (scoring at most $score_limit unscored jobs — DAILY_APPLY_SCORE_LIMIT)"
    fi
    "$REPO/.venv/bin/applypilot" run "${stages[@]}" || echo "WARN: prep exited $?"
  fi

  echo "==> apply --headless -l $LIMIT (min-score $MIN_SCORE, success quota)"
  apply_out="$LOG_DIR/apply-last.txt"
  apply_rc=0
  "$REPO/.venv/bin/applypilot" apply --headless -l "$LIMIT" -w 1 --min-score "$MIN_SCORE" | tee "$apply_out" || apply_rc=$?
  if [[ "$apply_rc" -ne 0 ]]; then
    write_health error apply_failed "applypilot apply exited $apply_rc"
    exit "$apply_rc"
  fi
  applied_n="$("$REPO/.venv/bin/python" -c '
import re, sys
from pathlib import Path
text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
hits = re.findall(r"Done: (\d+) applied", text)
print(hits[-1] if hits else "0")
' "$apply_out")"
  if [[ "${applied_n:-0}" -gt 0 ]]; then
    write_health ok applied "Submitted ${applied_n} application(s)"
  else
    write_health ok queue_empty "Apply finished with 0 submissions (queue empty or all candidates skipped)"
  fi

  if [[ "${DAILY_APPLY_EMAIL_POLL:-1}" == "1" ]]; then
    echo "==> poll application emails (Gmail readonly)"
    "$REPO/.venv/bin/python" "$REPO/scripts/poll_application_emails.py" || echo "WARN: email poll exited $?"
  fi

  echo "==> dashboard"
  "$REPO/.venv/bin/applypilot" dashboard || true

  echo
  echo "finished: $(date -Is)"
  echo "log: $LOG_FILE"
} 2>&1 | tee -a "$LOG_FILE"
