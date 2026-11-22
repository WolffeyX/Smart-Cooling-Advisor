"""Browser tests for the one-page dashboard (Playwright sync API, Chromium)."""

import subprocess
import sys
import time
import urllib.request

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.e2e

PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"

BASE_BODY = {
    "day_type": "weekday",
    "forecast_max_temp_c": 31,
    "safety_margin_pct": 10,
    "tank_capacity_rth": 10000,
    "tank_level_22_rth": 1500,
    "forecast_error_pct": 0,
}


@pytest.fixture(scope="session")
def server():
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                urllib.request.urlopen(f"{BASE}/health", timeout=2)
                break
            except OSError:
                if proc.poll() is not None:
                    raise RuntimeError("uvicorn exited early")
                time.sleep(0.5)
        else:
            raise RuntimeError("server did not become ready in 60 s")
        assert proc.poll() is None, "our uvicorn died; a stale server may own the port"
        yield BASE
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="session")
def browser():
    with playwright_sync.sync_playwright() as pw:
        b = pw.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    pg = ctx.new_page()
    yield pg
    ctx.close()


def _ready(page, server):
    page.goto(server)
    page.wait_for_selector("#hero-target:not(:empty)")


def test_initial_render_uses_api(page, server):
    _ready(page, server)
    api = page.request.post(f"{server}/recommend", data=BASE_BODY).json()
    shown = page.inner_text("#hero-target").replace("\u00a0", " ")
    assert shown.startswith(f"{round(api['recommendation']['charge_target_rth']):,}")
    assert page.locator("#chart-supply .bar").count() == 24
    assert page.locator("#comparison tbody tr").count() == 3
    assert "SIMULATED" in page.inner_text("body")
    assert page.get_attribute("#scenario-date", "data-date") == api["scenario"]["source_date"]
    assert "Left in tank at 21:00" in page.inner_text("#comparison")
    assert api["assumptions"][0][:40] in page.inner_text("#assumptions")
    assert api["recommendation"]["message"] in page.inner_text("#status-note")


def test_day_type_change_refetches(page, server):
    _ready(page, server)
    with page.expect_response("**/recommend"):
        page.click('#day-type [data-value="semester_break"]')


def test_capacity_drop_clamps_level(page, server):
    page.goto(server)
    page.fill("#level", "9000")
    with page.expect_request(
        lambda r: r.url.endswith("/recommend") and '"tank_capacity_rth":6000' in (r.post_data or "")
    ) as req:
        page.fill("#capacity", "6000")
    assert req.value.post_data_json["tank_level_22_rth"] <= 6000
    assert float(page.input_value("#level")) <= 6000


def test_stale_responses_ignored(page, server):
    page.add_init_script(
        """
        (() => {
          const orig = window.fetch.bind(window);
          window.fetch = async (...args) => {
            const url = String(args[0] && args[0].url ? args[0].url : args[0]);
            if (url.includes('/recommend') && window.__delayNext) {
              const ms = window.__delayNext;
              window.__delayNext = 0;
              const res = await orig(...args);
              await new Promise((r) => setTimeout(r, ms));
              return res;
            }
            return orig(...args);
          };
        })();
        """
    )
    _ready(page, server)
    page.evaluate("window.__delayNext = 1500")
    page.click('#day-type [data-value="weekend"]')
    page.wait_for_timeout(400)
    page.click('#day-type [data-value="weekday"]')
    weekday = {**BASE_BODY, "day_type": "weekday"}
    expected = page.request.post(f"{server}/recommend", data=weekday).json()["scenario"][
        "source_date"
    ]
    page.wait_for_selector(f'#scenario-date[data-date="{expected}"]')
    page.wait_for_timeout(2000)  # let the delayed weekend response arrive; it must be ignored
    assert page.get_attribute("#scenario-date", "data-date") == expected


def test_play_stops_at_21_and_reset(page, server):
    _ready(page, server)
    page.click("#play")
    page.wait_for_function("document.querySelector('#scrubber').value == '23'", timeout=20000)
    page.wait_for_timeout(1000)
    assert page.input_value("#scrubber") == "23"
    page.click("#reset")
    assert page.input_value("#scrubber") == "14"


def test_approve_shows_toast(page, server):
    _ready(page, server)
    page.click("text=Approve plan")
    assert "Demo only, nothing is sent" in page.inner_text("#toast")


def test_sketch_wording(page, server):
    _ready(page, server)
    assert "Run " in page.inner_text("#chiller-plan")
    assert " electric chillers from " in page.inner_text("#chiller-plan")
    assert page.inner_text("#clock").endswith("tomorrow")
    assert page.inner_text("#t-plant").startswith("3D plant view · 12:00 tomorrow")
    assert page.inner_text("#comparison tbody tr:last-child td:first-child") == "AI forecast"
    assert "The advisor only suggests the charge amount." in page.inner_text("body")
    assert "Tomorrow is a" in page.inner_text("body")
    page.click("#reset")
    assert page.inner_text("#clock").endswith("tomorrow")
