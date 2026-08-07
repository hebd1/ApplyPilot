#!/usr/bin/env bash
# Install Playwright Chromium and Linux system dependencies for high-quality PDFs.
# Run from WSL in the ApplyPilot project directory.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> Installing Playwright Python package (if needed)..."
.venv/bin/pip install -q playwright

echo "==> Installing Chromium browser binaries..."
.venv/bin/playwright install chromium

echo "==> Installing Linux system dependencies (requires root)..."
if [ "$(id -u)" -eq 0 ]; then
  .venv/bin/playwright install-deps chromium
else
  sudo .venv/bin/playwright install-deps chromium
fi

echo "==> Verifying Chromium can launch..."
.venv/bin/python scripts/test_playwright_pdf.py

echo ""
echo "Done. Playwright PDF rendering is ready."
echo "Regenerate materials: .venv/bin/python scripts/regenerate_pdfs_playwright.py"
