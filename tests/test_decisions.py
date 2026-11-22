import csv
import re
import threading
from datetime import datetime

import pytest

from app import decisions
from app.decisions import COLUMNS, DecisionLog

BODY = {
    "day_type": "weekday",
    "forecast_max_temp_c": 33,
    "safety_margin_pct": 10,
    "tank_capacity_rth": 10000,
    "tank_level_22_rth": 1500,
    "forecast_error_pct": 0,
}


@pytest.fixture
def log(client, tmp_path):
    old = client.app.state.decision_log
    client.app.state.decision_log = DecisionLog(tmp_path / "log.csv")
    yield client.app.state.decision_log
    client.app.state.decision_log = old


def _read(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def test_approve_appends_one_row_with_server_numbers(client, log):
    rec = client.post("/recommend", json=BODY).json()
    r = client.post("/decisions", json={**BODY, "action": "approved"})
    assert r.status_code == 200
    rows = _read(log.path)
    assert len(rows) == 1
    assert list(rows[0].keys()) == COLUMNS
    row = rows[0]
    target = round(rec["recommendation"]["charge_target_rth"], 1)
    assert float(row["operator_target_rth"]) == float(row["ai_target_rth"]) == target
    ai = next(c for c in rec["comparison"] if c["strategy"] == "ai_forecast")
    assert float(row["ec_kwh_ai_forecast"]) == round(ai["ec_energy_kwh"], 1)
    assert float(row["chosen_ec_kwh"]) == round(ai["ec_energy_kwh"], 1)
    assert row["label"] == "SIMULATED"
    assert r.json()["row"]["action"] == "approved"


def test_adjust_logs_operator_outcome(client, log):
    body = {**BODY, "action": "adjusted", "charge_target_override_rth": 9000}
    rec = client.post("/recommend", json={**BODY, "charge_target_override_rth": 9000}).json()
    assert client.post("/decisions", json=body).status_code == 200
    row = _read(log.path)[0]
    assert row["action"] == "adjusted"
    assert float(row["operator_target_rth"]) == 9000
    assert float(row["chosen_ec_kwh"]) == round(rec["operator_plan"]["ec_energy_kwh"], 1)


def test_client_numbers_ignored(client, log):
    body = {**BODY, "action": "approved", "chosen_ec_kwh": 1, "label": "REAL"}
    r = client.post("/decisions", json=body)
    assert r.status_code == 200
    row = _read(log.path)[0]
    assert row["chosen_ec_kwh"] != "1"
    assert row["label"] == "SIMULATED"


def test_adjust_without_override_422(client, log):
    assert client.post("/decisions", json={**BODY, "action": "adjusted"}).status_code == 422
    assert not log.path.exists()


def test_approve_with_override_422(client, log):
    body = {**BODY, "action": "approved", "charge_target_override_rth": 9000}
    assert client.post("/decisions", json=body).status_code == 422


def test_get_decisions_newest_first(client, log):
    client.post("/decisions", json={**BODY, "action": "approved"})
    client.post(
        "/decisions", json={**BODY, "action": "adjusted", "charge_target_override_rth": 9000}
    )
    d = client.get("/decisions").json()
    assert d["label"] == "SIMULATED"
    assert [r["action"] for r in d["rows"]] == ["adjusted", "approved"]


def test_get_decisions_missing_file_empty(client, log):
    assert client.get("/decisions").json() == {"rows": [], "label": "SIMULATED"}


def test_csv_download_header(client, log):
    r = client.get("/decisions.csv")
    assert r.headers["content-type"].startswith("text/csv")
    assert r.text.splitlines()[0] == ",".join(COLUMNS)
    client.post("/decisions", json={**BODY, "action": "approved"})
    r = client.get("/decisions.csv")
    assert r.text.splitlines()[0] == ",".join(COLUMNS)
    assert len(r.text.splitlines()) == 2


def test_header_mismatch_rotates_old_file(tmp_path):
    p = tmp_path / "log.csv"
    p.write_bytes(b"a,b\r\n1,2\r\n")
    dl = DecisionLog(p)
    dl.append(dict.fromkeys(COLUMNS, "x"))
    olds = list(tmp_path.glob("*.old.csv"))
    assert len(olds) == 1
    assert re.search(r"^log\.\d{8}-\d{6}(-\d+)?\.old\.csv$", olds[0].name)
    assert olds[0].read_bytes() == b"a,b\r\n1,2\r\n"
    rows = _read(p)
    assert len(rows) == 1 and list(rows[0].keys()) == COLUMNS


def test_two_rotations_same_second_are_distinct(tmp_path, monkeypatch):
    monkeypatch.setattr(decisions, "_now", lambda: datetime(2026, 11, 22, 15, 30, 12))
    p = tmp_path / "log.csv"
    dl = DecisionLog(p)
    p.write_text("a\n1\n")
    dl.append(dict.fromkeys(COLUMNS, "x"))
    p.write_text("b\n2\n")
    dl.append(dict.fromkeys(COLUMNS, "y"))
    olds = sorted(f.name for f in tmp_path.glob("*.old.csv"))
    assert olds == ["log.20261122-153012-1.old.csv", "log.20261122-153012.old.csv"]
    contents = {(tmp_path / n).read_text() for n in olds}
    assert contents == {"a\n1\n", "b\n2\n"}


def test_concurrent_appends(tmp_path):
    dl = DecisionLog(tmp_path / "log.csv")
    ts = [
        threading.Thread(target=dl.append, args=(dict.fromkeys(COLUMNS, str(i)),))
        for i in range(20)
    ]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len((tmp_path / "log.csv").read_text().splitlines()) == 21
    assert len(_read(tmp_path / "log.csv")) == 20


def test_decision_row_rounds_and_timestamps(client):
    resp = client.post("/recommend", json=BODY).json()
    row = decisions.decision_row("approved", BODY, resp, datetime(2026, 1, 2, 3, 4, 5, 999))
    assert row["timestamp"] == "2026-01-02T03:04:05"
    assert set(row) == set(COLUMNS)
