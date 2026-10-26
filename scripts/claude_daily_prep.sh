#!/usr/bin/env bash
# Morning prep for the Claude in Chrome apply routine (run inside WSL).
#
#   discover -> enrich -> score (capped) -> tailor/cover/pdf (score >= MIN) -> queue
#
# Scoring and tailoring go through `claude -p` (LLM_PROVIDER=claude). Holds the
# Phobos session lock while it works; when the machine is busy (a build, an
# emulator, or Game mode) it skips the heavy stages and only builds the queue
# from jobs that are already tailored. Prints the queue JSON path on the last line.
#
# Env knobs: CLAUDE_PREP_DISCOVER (1), CLAUDE_PREP_SCORE_LIMIT (40),
# CLAUDE_APPLY_MIN_SCORE (8), CLAUDE_APPLY_COUNT (3), CLAUDE_PREP_DISCOVER_MIN (50),
# CLAUDE_PREP_ENRICH_MIN (30).
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${APPLYPILOT_DIR:-$HOME/.applypilot}"
LOG_DIR="$APP_DIR/logs"
AP="$REPO/.venv/bin/applypilot"
PY="$REPO/.venv/bin/python"
MIN_SCORE="${CLAUDE_APPLY_MIN_SCORE:-8}"
COUNT="${CLAUDE_APPLY_COUNT:-3}"
LOCK="$HOME/.claude/skills/mac-session-lock/scripts/session-lock.sh"
OWNER="ApplyPilot routine (Claude)"
export SESSION_LOCK_SESSION="applypilot-routine"
export LLM_PROVIDER="${LLM_PROVIDER:-claude}"
export PATH="$HOME/.local/bin:$PATH"   # claude CLI

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/claude_prep-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

# Same file the old daily_apply.sh used, so the two never overlap.
exec 9>"$LOG_DIR/daily_apply.lock"
if ! flock -n 9; then
  echo "claude_prep: another ApplyPilot run holds $LOG_DIR/daily_apply.lock; exiting"
  exit 3
fi

echo "========== ApplyPilot Claude prep =========="
echo "started: $(date -Is)  min_score: $MIN_SCORE  count: $COUNT  provider: $LLM_PROVIDER"
cd "$REPO"

held_lock=0
release() { [[ "$held_lock" == "1" ]] && "$LOCK" release --owner "$OWNER" --no-cleanup >/dev/null 2>&1; }
trap release EXIT

if [[ -x "$LOCK" ]] && "$LOCK" claim --owner "$OWNER" --task "applypilot: daily discover/score/tailor"; then
  held_lock=1
else
  echo "WARN: session lock not available (machine busy or Game mode); skipping discover/score/tailor."
  echo "      Building the queue from jobs that are already tailored."
fi

if [[ "$held_lock" == "1" ]]; then
  echo "==> purge unapplyable / excluded / stuck"
  "$PY" scripts/purge_unapplyable_queue.py || echo "WARN: purge exited $?"

  echo "==> linkedin session refresh (non-fatal)"
  "$AP" linkedin-auth --refresh || echo "WARN: LinkedIn refresh failed; LinkedIn listings may lack ATS apply URLs"

  # Discovery takes ~3 min per search query; enrich gets its own budget so a
  # long crawl cannot starve it (scoring needs enriched descriptions).
  if [[ "${CLAUDE_PREP_DISCOVER:-1}" == "1" ]]; then
    echo "==> discover (max ${CLAUDE_PREP_DISCOVER_MIN:-50} min)"
    "$LOCK" run --max-min 70 -- timeout "${CLAUDE_PREP_DISCOVER_MIN:-50}m" "$AP" run discover \
      || echo "WARN: discover exited $?"
  fi
  echo "==> enrich (max ${CLAUDE_PREP_ENRICH_MIN:-30} min)"
  "$LOCK" run --max-min 45 -- timeout "${CLAUDE_PREP_ENRICH_MIN:-30}m" "$AP" run enrich \
    || echo "WARN: enrich exited $?"

  echo "==> score (at most ${CLAUDE_PREP_SCORE_LIMIT:-40}) + tailor/cover/pdf (score >= $MIN_SCORE)"
  SCORE_LIMIT="${CLAUDE_PREP_SCORE_LIMIT:-40}" "$LOCK" run --max-min 120 -- \
    "$AP" run score tailor cover pdf --min-score "$MIN_SCORE" || echo "WARN: score/tailor exited $?"
fi

echo "==> pick today's queue"
"$AP" claude queue --count "$COUNT" --min-score "$MIN_SCORE" || { echo "ERROR: queue failed"; exit 1; }

"$AP" dashboard >/dev/null 2>&1 || true
echo "finished: $(date -Is)  log: $LOG_FILE"
echo "QUEUE_JSON=$APP_DIR/claude/queue-$(date +%Y-%m-%d).json"
