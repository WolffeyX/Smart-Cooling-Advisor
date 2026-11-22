"""Start the app on port 8765 and capture the README and user-guide screenshots."""

import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
LAUNCH_ARGS = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]

SCENARIOS = [
    ("hot_weekday", "weekday", 34),
    ("cool_weekday", "weekday", 29),
    ("semester_break", "semester_break", 31),
]

# 3D camera positions (world units). HOME is [28, 20, 30] in static/plant3d-scene.js.
NIGHT_CAMERA = [-26, 46, 22]  # 02:00 charging: front-left, high (labels all readable)
DAY_CAMERA = [30, 6, 34]  # 13:00 discharging: front-right, low (labels do not overlap)
NIGHT_HOUR = 4  # 02:00 (charging)
DAY_HOUR = 15  # 13:00 (daytime discharge)


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


def shoot_plant(browser, name, hour, camera):
    """Plant card in 3D at one hour and camera angle (weekday, 31 C, the page default)."""
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
    page = ctx.new_page()
    page.goto(BASE)
    page.wait_for_selector("#hero-target:not(:empty)")
    page.click("#view-3d")
    page.wait_for_function("window.__plant3d && window.__plant3d.ready")
    page.evaluate("i => window.SCA.setHour(i)", hour)
    page.evaluate("p => window.__plant3d.setCamera(p)", camera)
    page.wait_for_timeout(800)
    page.locator("section.plant-card").screenshot(path=str(OUT / f"{name}.png"))
    print(name, "hour", hour, "camera", page.evaluate("window.__plant3d.camera"))
    ctx.close()


def shoot_explainer(browser):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
    page = ctx.new_page()
    page.goto(BASE)
    page.wait_for_selector("#hero-target:not(:empty)")
    page.wait_for_selector("#explain-path li")
    page.locator("details#explain").screenshot(path=str(OUT / "rf_panel.png"))
    print("rf_panel written")
    ctx.close()


def shoot_decision_log(browser, log_path):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
    page = ctx.new_page()
    page.goto(BASE)
    page.wait_for_selector("#hero-target:not(:empty)")
    rows = page.locator("#decision-log tbody tr")

    with page.expect_response(
        lambda r: r.url.endswith("/decisions") and r.request.method == "POST"
    ):
        page.click("#approve")

    page.click("#adjust")
    page.fill("#override-input", "9000")
    with page.expect_response(lambda r: r.url.endswith("/recommend")):
        page.click("#override-preview")
    with page.expect_response(
        lambda r: r.url.endswith("/decisions") and r.request.method == "POST"
    ):
        page.click("#override-confirm")

    page.wait_for_function("() => document.querySelectorAll('#decision-log tbody tr').length >= 2")
    assert rows.count() >= 2
    page.locator("section:has(#decision-log)").screenshot(path=str(OUT / "decision_log.png"))
    print("decision_log rows", rows.count(), "log", log_path)
    ctx.close()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    log_dir = tempfile.mkdtemp(prefix="sca-shots-")
    log_path = os.path.join(log_dir, "decision_log.csv")
    env = {**os.environ, "SCA_DECISION_LOG": log_path}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT)],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    try:
        wait_ready(proc)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=LAUNCH_ARGS)
            for name, day_type, temp in SCENARIOS:
                shoot(browser, name, day_type, temp)
            shoot_plant(browser, "3d_night", NIGHT_HOUR, NIGHT_CAMERA)
            shoot_plant(browser, "3d_day", DAY_HOUR, DAY_CAMERA)
            shoot_explainer(browser)
            shoot_decision_log(browser, log_path)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
