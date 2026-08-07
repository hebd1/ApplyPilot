#!/usr/bin/env bash
# Install WSL cron for ApplyPilot daily apply at 08:00 America/Denver.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$REPO/scripts/daily_apply.sh"
MARKER="# applypilot-daily-apply"

chmod +x "$SCRIPT" "$REPO/scripts/install_daily_apply_cron.sh"

# Ensure cron package / daemon (skip sudo prompts when already available)
if ! command -v cron >/dev/null 2>&1 && ! command -v crond >/dev/null 2>&1; then
  echo "cron is not installed. Run once:"
  echo "  sudo apt-get install -y cron && sudo service cron start"
  exit 1
fi

if command -v service >/dev/null 2>&1; then
  if ! service cron status >/dev/null 2>&1; then
    echo "Starting cron (may prompt for sudo)..."
    sudo service cron start || {
      echo "WARN: could not start cron. Run: sudo service cron start"
    }
  else
    echo "cron daemon is already running"
  fi
fi

# crontab entry — CRON_TZ keeps 8am as Mountain (MST/MDT) year-round
CRON_LINE="0 8 * * * $SCRIPT"
EXISTING="$(crontab -l 2>/dev/null || true)"
FILTERED="$(printf '%s\n' "$EXISTING" | grep -vF "$MARKER" | grep -vF "$SCRIPT" || true)"

NEW_CRON="$(cat <<EOF
${FILTERED}

CRON_TZ=America/Denver
${CRON_LINE} ${MARKER}
EOF
)"

# Trim leading blank lines from empty crontab
NEW_CRON="$(printf '%s\n' "$NEW_CRON" | sed '/./,$!d')"
printf '%s\n' "$NEW_CRON" | crontab -

echo "Installed crontab:"
crontab -l
echo
echo "Cron daemon: $(service cron status 2>&1 | head -1 || echo unknown)"
echo
echo "IMPORTANT: Prefer the Windows Task for 08:00 local (primary)."
echo "  powershell.exe -ExecutionPolicy Bypass -File $REPO/scripts/install_daily_apply_windows_task.ps1"
echo "Daily defaults: 1 successful ATS apply (score>=8), purge + Gmail outcome poll."
echo
echo "Test now (real applies):"
echo "  bash $SCRIPT"
echo "Dry-run one:"
echo "  DAILY_APPLY_PREP=0 $REPO/.venv/bin/applypilot apply --dry-run -l 1 --headless"
