#!/usr/bin/env bash
# Clear job queue and generated materials for a fresh pipeline run.
# Keeps ~/.applypilot/.env (API keys). Use before `applypilot init` for full re-onboard.
set -euo pipefail

KEEP_CONFIG=0
for arg in "$@"; do
  case "$arg" in
    --keep-config) KEEP_CONFIG=1 ;;
    -h|--help)
      echo "Usage: reset_for_fresh_start.sh [--keep-config]"
      echo "  --keep-config  Keep profile.json, resume files, and searches.yaml"
      exit 0
      ;;
    *) echo "Unknown option: $arg" >&2; exit 1 ;;
  esac
done

APPLYPILOT_DIR="${APPLYPILOT_DIR:-$HOME/.applypilot}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export APPLYPILOT_DIR ROOT

echo "==> Resetting ApplyPilot data in ${APPLYPILOT_DIR}"

mkdir -p "${APPLYPILOT_DIR}/tailored_resumes" "${APPLYPILOT_DIR}/cover_letters"

echo "==> Clearing jobs database..."
if [[ -f "${APPLYPILOT_DIR}/applypilot.db" ]]; then
  "${ROOT}/.venv/bin/python" - <<'PY'
import os
import sqlite3
from pathlib import Path

db = Path(os.environ["APPLYPILOT_DIR"]) / "applypilot.db"
conn = sqlite3.connect(db)
conn.execute("DELETE FROM jobs")
conn.commit()
conn.execute("VACUUM")
conn.close()
print(f"    Deleted all rows from jobs table ({db}).")
PY
else
  echo "    No database file (will be created on next run)."
fi

echo "==> Removing tailored resumes and cover letters..."
rm -f "${APPLYPILOT_DIR}/tailored_resumes"/*
rm -f "${APPLYPILOT_DIR}/cover_letters"/*

echo "==> Removing dashboard..."
rm -f "${APPLYPILOT_DIR}/dashboard.html"

if [[ "$KEEP_CONFIG" -eq 0 ]]; then
  echo "==> Removing profile, resume, and search config (re-enter via applypilot init)..."
  rm -f "${APPLYPILOT_DIR}/profile.json"
  rm -f "${APPLYPILOT_DIR}/resume.txt"
  rm -f "${APPLYPILOT_DIR}/resume.pdf"
  rm -f "${APPLYPILOT_DIR}/searches.yaml"
else
  echo "==> Keeping profile.json, resume files, and searches.yaml (--keep-config)."
fi

echo ""
echo "Done. Preserved: ${APPLYPILOT_DIR}/.env"
echo "Next steps:"
echo "  1. .venv/bin/applypilot init     # update profile, resume, searches"
echo "  2. .venv/bin/applypilot run      # discover through cover (+ PDFs)"
echo "  3. .venv/bin/applypilot dashboard"
