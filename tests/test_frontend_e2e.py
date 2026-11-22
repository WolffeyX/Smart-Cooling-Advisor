"""Browser tests for the one-page dashboard (Playwright sync API, Chromium)."""

import os
import shutil
import subprocess
import sys
import tempfile
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
    log_dir = tempfile.mkdtemp(prefix="sca-e2e-")
    env = {**os.environ, "SCA_DECISION_LOG": os.path.join(log_dir, "decision_log.csv")}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
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
        shutil.rmtree(log_dir, ignore_errors=True)


@pytest.fixture(scope="session")
def browser():
    with playwright_sync.sync_playwright() as pw:
        b = pw.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
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
    page.click("#approve")
    page.wait_for_function("document.querySelector('#toast').textContent.includes('Logged')")
    assert "Logged · SIMULATED" in page.inner_text("#toast")


def test_sketch_wording(page, server):
    _ready(page, server)
    assert "Run " in page.inner_text("#chiller-plan")
    assert " electric chillers from " in page.inner_text("#chiller-plan")
    assert page.inner_text("#clock").endswith("tomorrow")
    assert page.inner_text("#t-plant").startswith("Plant view · 12:00 tomorrow")
    assert page.inner_text("#comparison tbody tr:last-child td:first-child") == "AI forecast"
    assert "The advisor only suggests the charge amount." in page.inner_text("body")
    assert "Tomorrow is a" in page.inner_text("body")
    page.click("#reset")
    assert page.inner_text("#clock").endswith("tomorrow")


def _is_post(url_end):
    return lambda r: r.url.endswith(url_end) and r.method == "POST"


def _rows(page):
    return page.locator("#decision-log tbody tr").count()


def test_approve_logs_one_row(page, server):
    _ready(page, server)
    page.wait_for_function("window.SCADecisions !== undefined")
    page.wait_for_timeout(500)
    before = _rows(page)
    posts = []
    page.on("request", lambda r: posts.append(r) if _is_post("/decisions")(r) else None)
    page.dblclick("#approve")  # a double click must still log exactly one row
    page.wait_for_function(
        f"document.querySelectorAll('#decision-log tbody tr').length === {before + 1}"
    )
    page.wait_for_timeout(500)
    assert len(posts) == 1
    assert "approved" in page.inner_text("#decision-log tbody tr:first-child")
    assert _rows(page) == before + 1
    assert not page.is_disabled("#approve")


def test_adjust_preview_then_confirm(page, server):
    _ready(page, server)
    hero = page.inner_text("#hero-target")
    page.click("#adjust")
    assert page.is_visible("#adjust-box")
    page.fill("#override-input", "9000")
    with page.expect_request(_is_post("/recommend")) as req:
        page.click("#override-preview")
    assert req.value.post_data_json["charge_target_override_rth"] == 9000
    page.wait_for_function("document.querySelector('#operator-note').textContent.includes('9,000')")
    assert "9,000" in page.inner_text("#operator-note")
    assert "AI recommended" in page.inner_text("#operator-note")
    assert page.inner_text("#hero-target") == hero
    before = _rows(page)
    with page.expect_request(_is_post("/decisions")) as post:
        page.click("#override-confirm")
    assert post.value.post_data_json["action"] == "adjusted"
    page.wait_for_function(
        f"document.querySelectorAll('#decision-log tbody tr').length === {before + 1}"
    )
    first = page.inner_text("#decision-log tbody tr:first-child")
    assert "adjusted" in first and "9,000" in first
    assert page.is_hidden("#adjust-box")


def test_approve_disabled_during_override_preview(page, server):
    _ready(page, server)
    page.wait_for_function("window.SCADecisions !== undefined")
    posts = []
    page.on("request", lambda r: posts.append(r) if _is_post("/decisions")(r) else None)
    assert not page.is_disabled("#approve")
    page.click("#adjust")
    assert page.is_disabled("#approve")
    page.fill("#override-input", "9000")
    page.click("#override-preview")
    page.wait_for_function("document.querySelector('#operator-note').textContent.includes('9,000')")
    assert page.is_disabled("#approve")
    page.click("#override-cancel")
    page.wait_for_function("!document.querySelector('#approve').disabled")
    assert not page.is_disabled("#approve")
    assert posts == []


def test_input_change_clears_override(page, server):
    _ready(page, server)
    page.click("#adjust")
    page.fill("#override-input", "9000")
    page.click("#override-preview")
    page.wait_for_function("document.querySelector('#operator-note').textContent.includes('9,000')")
    with page.expect_request(_is_post("/recommend")) as req:
        page.fill("#capacity", "6000")
    assert "charge_target_override_rth" not in req.value.post_data_json
    page.wait_for_timeout(800)
    assert page.is_hidden("#adjust-box")
    assert page.is_hidden("#operator-note")
    assert page.is_hidden("#api-error")


def test_slider_drag_logs_nothing(page, server):
    _ready(page, server)
    posts = []
    page.on("request", lambda r: posts.append(r) if _is_post("/decisions")(r) else None)
    for sel, val in (("#temp", "33"), ("#error", "10"), ("#margin", "20")):
        page.fill(sel, val)
    page.wait_for_timeout(800)
    assert posts == []


def test_csv_link(page, server):
    _ready(page, server)
    assert page.get_attribute("#decision-csv", "href") == "/decisions.csv"


_DELAY_SCRIPT = """
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


def test_inflight_preview_dropped_on_input_change(page, server):
    page.add_init_script(_DELAY_SCRIPT)
    _ready(page, server)
    posts = []
    page.on("request", lambda r: posts.append(r) if _is_post("/decisions")(r) else None)
    page.click("#adjust")
    page.fill("#override-input", "9000")
    # The response must land inside the 300 ms input debounce, before the new request bumps seq.
    page.evaluate("window.__delayNext = 250")
    page.click("#override-preview")
    page.evaluate("window.__delayNext = 1500")  # hold the capacity request in flight
    page.fill("#capacity", "6000")
    page.wait_for_timeout(900)  # stale preview response has landed; new one is still pending
    assert page.is_hidden("#operator-note")
    assert page.is_disabled("#override-confirm")
    page.wait_for_timeout(2000)
    assert page.is_hidden("#operator-note")
    assert page.is_disabled("#override-confirm")
    assert page.is_hidden("#api-error")
    assert posts == []


def test_edit_between_preview_and_response_disarms_confirm(page, server):
    page.add_init_script(_DELAY_SCRIPT)
    _ready(page, server)
    page.click("#adjust")
    page.fill("#override-input", "9000")
    page.evaluate("window.__delayNext = 1500")
    page.click("#override-preview")
    page.wait_for_timeout(200)
    page.fill("#override-input", "8000")
    page.wait_for_function("document.querySelector('#operator-note').textContent.includes('9,000')")
    assert page.is_disabled("#override-confirm")


_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

_COUNT_EXPLAIN = """
(() => {
  window.__explainReqs = [];
  const orig = window.fetch.bind(window);
  window.fetch = (...args) => {
    const url = String(args[0] && args[0].url ? args[0].url : args[0]);
    if (url.includes('/explain')) window.__explainReqs.push(url);
    return orig(...args);
  };
})();
"""


def test_explainer_matches_api(page, server):
    _ready(page, server)
    page.wait_for_selector("#explain-features tbody tr")
    reco = page.request.post(f"{server}/recommend", data=BASE_BODY).json()
    date = reco["scenario"]["source_date"]
    ex = page.request.get(f"{server}/explain", params={"source_date": date}).json()
    page.wait_for_selector("#explain-path li")
    assert f"{round(ex['trees']['mean']):,}" in page.text_content("#explain-hist")
    assert abs(reco["recommendation"]["ai_forecast_model_rth"] - ex["trees"]["mean"]) <= 0.5
    assert page.locator("#explain-path li").count() == len(ex["path"]["splits"])
    assert page.locator("#explain-features tbody tr").count() == 12
    training = page.inner_text("#explain-training")
    for m in ex["training_months"]:
        assert _MONTHS[m - 1] in training
    assert "400" in training
    assert "out-of-sample" in training
    card = page.inner_text("#explain")
    assert "SIMULATED" in card and "MEASURED" in card
    assert "distinct training days reaching this split" in card
    assert "never trained on" in page.inner_text("#explain-month-note")
    assert page.locator("#explain-perm .bar").count() == 12
    assert page.locator("#explain-impurity .bar").count() == 12
    assert "before the what-if" in card


def test_explainer_refetches_only_on_date_change(page, server):
    page.add_init_script(_COUNT_EXPLAIN)
    _ready(page, server)
    page.wait_for_selector("#explain-path li")
    assert page.evaluate("window.__explainReqs.length") == 1
    first = page.get_attribute("#scenario-date", "data-date")
    with page.expect_response("**/recommend"):
        page.fill("#margin", "30")
    page.wait_for_timeout(500)
    assert page.evaluate("window.__explainReqs.length") == 1
    new_temp = None
    for t in (24, 26, 28, 33, 35, 38):
        d = page.request.post(f"{server}/recommend", data={**BASE_BODY, "forecast_max_temp_c": t})
        if d.json()["scenario"]["source_date"] != first:
            new_temp = t
            break
    assert new_temp is not None
    page.fill("#temp", str(new_temp))
    page.wait_for_function("window.__explainReqs.length === 2")
    page.wait_for_timeout(500)
    assert page.evaluate("window.__explainReqs.length") == 2


_EXPLAIN_HOOKS = """
(() => {
  window.__explainReqs = [];
  window.__delayExplain = window.__delayExplain || 0;
  window.__failExplain = false;
  const orig = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const url = String(args[0] && args[0].url ? args[0].url : args[0]);
    if (url.includes('/explain')) {
      window.__explainReqs.push(url);
      if (window.__failExplain) return new Response('boom', { status: 500 });
      if (window.__delayExplain) {
        const ms = window.__delayExplain;
        window.__delayExplain = 0;
        const res = await orig(...args);
        await new Promise((r) => setTimeout(r, ms));
        return res;
      }
    }
    return orig(...args);
  };
})();
"""


def _other_temp(page, server, first_date):
    for t in (24, 26, 28, 33, 35, 38):
        r = page.request.post(f"{server}/recommend", data={**BASE_BODY, "forecast_max_temp_c": t})
        if r.json()["scenario"]["source_date"] != first_date:
            return t, r.json()["scenario"]["source_date"]
    raise AssertionError("no temperature gives a different source date")


def test_explainer_slow_then_fast_shows_latest(page, server):
    page.add_init_script("window.__delayExplain = 1800;" + _EXPLAIN_HOOKS)
    page.goto(server)
    page.wait_for_selector("#hero-target:not(:empty)")
    first = page.get_attribute("#scenario-date", "data-date")
    temp, date_b = _other_temp(page, server, first)
    page.fill("#temp", str(temp))
    page.wait_for_selector(f'#explain-date:text-is("{date_b}")')
    page.wait_for_timeout(2500)  # the slow response for the first date lands and must be dropped
    assert page.inner_text("#explain-date") == date_b
    ex_b = page.request.get(f"{server}/explain", params={"source_date": date_b}).json()
    assert f"{round(ex_b['trees']['mean']):,}" in page.text_content("#explain-hist")


def test_explainer_cache_hit_on_return(page, server):
    page.add_init_script(_EXPLAIN_HOOKS)
    _ready(page, server)
    page.wait_for_selector("#explain-path li")
    first = page.get_attribute("#scenario-date", "data-date")
    temp, date_b = _other_temp(page, server, first)
    page.fill("#temp", str(temp))
    page.wait_for_selector(f'#explain-date:text-is("{date_b}")')
    assert page.evaluate("window.__explainReqs.length") == 2
    page.fill("#temp", "31")
    page.wait_for_selector(f'#explain-date:text-is("{first}")')
    page.wait_for_timeout(500)
    assert page.evaluate("window.__explainReqs.length") == 2
    assert page.locator("#explain-features tbody tr").count() == 12


def test_explainer_error_path_and_retry(page, server):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.add_init_script(_EXPLAIN_HOOKS)
    _ready(page, server)
    page.wait_for_selector("#explain-path li")
    first = page.get_attribute("#scenario-date", "data-date")
    temp, date_b = _other_temp(page, server, first)
    page.evaluate("window.__failExplain = true")
    page.fill("#temp", str(temp))
    page.wait_for_selector("#explain-status:not([hidden])")
    assert "Could not load the explanation" in page.inner_text("#explain-status")
    assert page.is_hidden("#explain-body")  # the old day is not shown under the new forecast
    page.evaluate("window.__failExplain = false")
    page.fill("#temp", "31")
    page.wait_for_selector(f'#explain-date:text-is("{first}")')
    page.fill("#temp", str(temp))  # retry of the previously failed date fetches again
    page.wait_for_selector(f'#explain-date:text-is("{date_b}")')
    assert page.is_visible("#explain-body")
    assert errors == []


# ---------- 3D plant view ----------


def _open_3d(page, server):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    _ready(page, server)
    assert page.is_visible("#plant-svg") and page.is_hidden("#plant-3d")
    page.click("#view-3d")
    page.wait_for_function("window.__plant3d && window.__plant3d.ready")
    return errors


def _hourly(page):
    return page.evaluate("window.SCA.getData().hourly")


def test_3d_toggle_and_sync(page, server):
    errors = _open_3d(page, server)
    assert page.is_visible("#plant-3d") and page.is_hidden("#plant-svg")
    hourly = _hourly(page)
    page.evaluate("window.SCA.setHour(4)")
    st = page.evaluate("window.__plant3d")
    assert st["idx"] == 4
    assert hourly[4]["charge_rt"] > 0
    assert st["flows"]["ec_tank"] == hourly[4]["charge_rt"]
    assert st["flows"]["tank_campus"] == 0
    cap = page.evaluate("window.SCA.getData().plant.tank_capacity_rth")
    assert abs(st["waterFraction"] - hourly[4]["tank_level_rth"] / cap) < 1e-6
    page.evaluate("window.SCA.setHour(15)")
    st = page.evaluate("window.__plant3d")
    assert st["flows"]["tank_campus"] == hourly[15]["tank_out_rt"]
    assert st["flows"]["ec_tank"] == 0
    assert st["flows"]["return"] == hourly[15]["campus_load_rt"]
    page.click("#view-2d")
    assert page.is_visible("#plant-svg") and page.is_hidden("#plant-3d")
    assert errors == []


def _dist_box(p, b):
    d = [max(b["min"][i] - p[i], 0, p[i] - b["max"][i]) for i in range(3)]
    return sum(x * x for x in d) ** 0.5


def _dist_seg(p, a, b):
    ab = [b[i] - a[i] for i in range(3)]
    ap = [p[i] - a[i] for i in range(3)]
    n = sum(x * x for x in ab)
    t = 0 if n == 0 else max(0, min(1, sum(ap[i] * ab[i] for i in range(3)) / n))
    return sum((p[i] - (a[i] + t * ab[i])) ** 2 for i in range(3)) ** 0.5


def test_3d_pipes_connected(page, server):
    errors = _open_3d(page, server)
    st = page.evaluate("window.__plant3d")
    boxes, ends, pts = st["boxes"], st["segmentEnds"], st["segmentPoints"]
    assert {"campus_header", "to_academic", "to_evening", "to_base", "return"} <= set(ends)
    for key, e in ends.items():
        for p in e:
            near_box = any(_dist_box(p, b) <= 0.6 for b in boxes)
            near_pipe = any(
                _dist_seg(p, q[i], q[i + 1]) <= 0.6
                for k, q in pts.items()
                if k != key
                for i in range(len(q) - 1)
            )
            assert near_box or near_pipe, f"{key} end {p} is dangling"
    assert errors == []


def test_3d_block_stubs_follow_block_load(page, server):
    errors = _open_3d(page, server)
    hourly = _hourly(page)
    page.evaluate("window.SCA.setHour(15)")
    f = page.evaluate("window.__plant3d.flows")
    assert f["to_academic"] == hourly[15]["academic_rt"]
    assert f["to_evening"] == hourly[15]["evening_rt"]
    assert f["to_base"] == hourly[15]["base_rt"]
    assert f["campus_header"] == hourly[15]["campus_load_rt"]
    page.evaluate("window.SCA.setHour(4)")
    assert page.evaluate("window.__plant3d.flows.to_academic") == 0
    assert errors == []


def test_3d_idle_key_visible(page, server):
    _open_3d(page, server)
    assert page.is_visible("#plant-3d-key")
    assert "idle" in page.inner_text("#plant-3d-key").lower()


def test_3d_labels_from_api(page, server):
    errors = _open_3d(page, server)
    hourly = _hourly(page)
    for i in (4, 15):
        page.evaluate(f"window.SCA.setHour({i})")
        lab = page.evaluate("window.__plant3d.labels")
        assert lab["academic"] == hourly[i]["academic_rt"]
        assert lab["evening"] == hourly[i]["evening_rt"]
        assert lab["base"] == hourly[i]["base_rt"]
    txt = page.inner_text("#plant-3d")
    for name in ("Academic", "Library & evening classes", "Data centre & labs"):
        assert name in txt
    assert "room-equivalents (SIMULATED)" in txt
    assert errors == []


def test_3d_orbit_and_reset(page, server):
    errors = _open_3d(page, server)
    page.wait_for_timeout(300)
    start = page.evaluate("window.__plant3d.camera")
    box = page.locator("#plant-3d canvas").bounding_box()
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(cx, cy)
    page.mouse.down()
    page.mouse.move(cx + 120, cy + 30, steps=8)
    page.mouse.up()
    page.wait_for_timeout(200)
    moved = page.evaluate("window.__plant3d.camera")
    assert max(abs(a - b) for a, b in zip(start, moved)) > 0.1
    page.click("#reset-view")
    page.wait_for_timeout(200)
    back = page.evaluate("window.__plant3d.camera")
    assert max(abs(a - b) for a, b in zip(start, back)) < 1e-6
    assert errors == []


def test_3d_tooltip_on_hover(page, server):
    errors = _open_3d(page, server)
    page.evaluate("window.SCA.setHour(15)")
    found = page.evaluate("window.__plant3d.hoverProbe && window.__plant3d.hoverProbe('tank')")
    assert found
    assert "RTh" in page.inner_text("#plant-tooltip")
    page.evaluate("window.SCA.setHour(4)")
    row = _hourly(page)[4]
    assert row["charge_rt"] > 0
    assert page.evaluate("window.__plant3d.hoverProbe('ec')")
    ec = page.inner_text("#plant-tooltip")
    assert f"charging tank {round(row['charge_rt']):,} RT" in ec
    assert f"to campus {round(row['ec_load_rt']):,} RT" in ec
    assert errors == []


def test_3d_tooltip_refreshes_on_hour_change(page, server):
    errors = _open_3d(page, server)
    page.evaluate("window.SCA.setHour(15)")
    assert page.evaluate("window.__plant3d.hoverProbe('tank')")
    before = page.inner_text("#plant-tooltip")
    page.evaluate("window.SCA.setHour(4)")
    after = page.inner_text("#plant-tooltip")
    level = round(_hourly(page)[4]["tank_level_rth"])
    assert f"{level:,} of" in after
    assert after != before
    assert errors == []


def test_3d_loop_stops_when_hidden(page, server):
    _open_3d(page, server)
    assert page.evaluate("window.__plant3d.rendering") is True
    page.click("#view-2d")
    page.wait_for_timeout(200)
    assert page.evaluate("window.__plant3d.rendering") is False


def test_no_webgl_fallback(browser, server):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    ctx.add_init_script(
        """
        const g = HTMLCanvasElement.prototype.getContext;
        HTMLCanvasElement.prototype.getContext = function (t, ...a) {
          if (t === 'webgl' || t === 'webgl2' || t === 'experimental-webgl') return null;
          return g.call(this, t, ...a);
        };
        """
    )
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    _ready(pg, server)
    pg.wait_for_selector("#view-3d:disabled")
    assert "WebGL" in pg.inner_text("#view-note")
    assert pg.is_visible("#view-note")
    assert pg.is_visible("#plant-svg")
    pg.evaluate("window.SCA.setHour(4)")
    assert "Plant view" in pg.inner_text("#t-plant")
    assert errors == []
    ctx.close()


def _impact_line(line, base):
    kwh = f"{abs(line['kwh_saved']):,.1f}"
    word = "more" if line["kwh_saved"] < 0 else "less"
    return kwh, word


def test_impact_card(page, server):
    _ready(page, server)
    api = page.request.post(f"{server}/recommend", data=BASE_BODY).json()
    page.wait_for_selector("#impact-full:not(:empty)")
    full = page.inner_text("#impact-full").replace("\u00a0", " ")
    kwh, word = _impact_line(api["impact"]["vs_always_full"], "full")
    assert f"{kwh} kWh {word}" in full
    assert "CO₂" in full
    assert "0.740" in page.inner_text("#impact-factor")
    assert "ASSUMPTION" in page.inner_text("#impact-factor")
    assert page.is_visible("#impact-caveat")
    assert "SIMULATED" in page.inner_text("#impact")


def test_impact_card_negative_says_more(page, server):
    page.goto(server)
    page.wait_for_selector("#hero-target:not(:empty)")
    body = {**BASE_BODY, "forecast_max_temp_c": 33}
    api = page.request.post(f"{server}/recommend", data=body).json()
    assert api["impact"]["vs_calendar_rule"]["kwh_saved"] < 0
    with page.expect_response("**/recommend"):
        page.fill("#temp", "33")
    page.wait_for_function("document.getElementById('scenario-date').dataset.date === '2024-10-23'")
    rule = page.inner_text("#impact-rule").replace("\u00a0", " ")
    kwh, _ = _impact_line(api["impact"]["vs_calendar_rule"], "rule")
    assert f"{kwh} kWh more" in rule
    assert "kg CO₂ more" in rule
    assert "−" not in rule
    assert "NaN" not in page.inner_text("#impact")
