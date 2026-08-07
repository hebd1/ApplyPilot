from playwright.sync_api import sync_playwright

candidates = [
    "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
    "/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
]

for exe in candidates:
    from pathlib import Path
    if not Path(exe).exists():
        print("missing", exe)
        continue
    print("trying", exe)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=exe, headless=True)
            page = browser.new_page()
            page.set_content("<h1>Test</h1>")
            page.pdf(path="/tmp/test_applypilot.pdf", format="Letter")
            browser.close()
        print("OK", exe)
        break
    except Exception as e:
        print("FAIL", type(e).__name__, str(e)[:200])
