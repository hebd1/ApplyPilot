"""Smoke-test Playwright Chromium PDF rendering in WSL."""
from pathlib import Path

from playwright.sync_api import sync_playwright

out = Path("/tmp/applypilot_playwright_test.pdf")
html = """<!DOCTYPE html><html><head><style>
body { font-family: Calibri, sans-serif; color: #1a3a5c; }
h1 { border-bottom: 2px solid #2a7ab5; }
</style></head><body><h1>Playwright PDF Test</h1><p>ApplyPilot resume rendering.</p></body></html>"""

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.set_content(html, wait_until="networkidle")
    page.pdf(path=str(out), format="Letter", print_background=True)
    browser.close()

print("OK", out, out.stat().st_size, "bytes")
