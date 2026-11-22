"""Start the app on port 8765 and capture the three README screenshots."""

import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"

SCENARIOS = [
    ("hot_weekday", "weekday", 34),
    ("cool_weekday", "weekday", 29),
    ("semester_break", "semester_break", 31),
]


def wait_ready(proc):
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{BASE}/health", timeout=2)
            assert proc.poll() is None, "our uvicorn died; a stale server may own the port"
            return
        except OSError:
            if proc.poll() is not None:
                raise RuntimeError("uvicorn exited early")
            time.sleep(0.5)
    raise RuntimeError("server did not become ready")


def shoot(browser, name, day_type, temp):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
    page = ctx.new_page()
    page.goto(BASE)
    page.wait_for_selector("#hero-target:not(:empty)")
    with page.expect_response(lambda r: r.url.endswith("/recommend")):
        page.click(f'#day-type [data-value="{day_type}"]')
    with page.expect_response(lambda r: r.url.endswith("/recommend")) as info:
        page.fill("#temp", str(temp))
    body = info.value.json()
    page.wait_for_selector(f'#scenario-date[data-date="{body["scenario"]["source_date"]}"]')
    page.wait_for_function(
        "m => document.querySelector('#status-note').innerText.includes(m.slice(0, 20))",
        arg=body["recommendation"]["message"],
    )
    page.wait_for_timeout(500)
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    print(
        name,
        body["scenario"]["source_date"],
        body["recommendation"]["charge_target_rth"],
        body["recommendation"]["message"],
    )
    ctx.close()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT)],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_ready(proc)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for name, day_type, temp in SCENARIOS:
                shoot(browser, name, day_type, temp)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
