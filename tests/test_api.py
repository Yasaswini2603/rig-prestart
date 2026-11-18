import pytest
from fastapi.testclient import TestClient

from app.checklist import CHECKLIST


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Each test gets its own fresh database file.
    monkeypatch.setenv("RIGBY_DB", str(tmp_path / "test.db"))
    from app.main import app
    with TestClient(app) as c:
        yield c


def all_pass(**overrides):
    items = [{"key": i["key"], "result": "pass"} for i in CHECKLIST]
    for key, (result, comment) in overrides.items():
        for it in items:
            if it["key"] == key:
                it.update(result=result, comment=comment)
    return items


def prestart(client, rig_id=1, hours=1000, items=None):
    return client.post("/api/prestarts", json={
        "rig_id": rig_id, "operator": "Sam Taylor", "shift": "day",
        "hour_meter": hours, "items": items or all_pass(),
    })


def test_seeded_rigs(client):
    rigs = client.get("/api/rigs").json()
    assert len(rigs) == 5
    assert rigs[0]["name"] == "AC-01"


def test_all_pass_is_go_and_creates_no_actions(client):
    r = prestart(client)
    assert r.status_code == 201
    assert r.json()["outcome"] == "go"
    assert client.get("/api/actions").json() == []


def test_high_fail_is_go_with_defects_and_creates_action(client):
    r = prestart(client, items=all_pass(hoses=("fail", "Weeping fitting on rotation head")))
    assert r.json()["outcome"] == "go_with_defects"
    actions = client.get("/api/actions").json()
    assert len(actions) == 1
    assert actions[0]["severity"] == "high"
    assert "Weeping fitting" in actions[0]["description"]


def test_critical_fail_stops_rig(client):
    r = prestart(client, items=all_pass(estops=("fail", "Cab e-stop not latching")))
    assert r.json()["outcome"] == "do_not_operate"
    rig = next(f for f in client.get("/api/dashboard").json()["fleet"] if f["rig_id"] == 1)
    assert rig["status"] == "do_not_operate"


def test_open_critical_action_keeps_rig_stopped_until_closed(client):
    prestart(client, hours=1000, items=all_pass(guards=("fail", "Guard bolt missing")))
    prestart(client, hours=1001)  # next prestart passes, but the defect is still open
    rig = next(f for f in client.get("/api/dashboard").json()["fleet"] if f["rig_id"] == 1)
    assert rig["status"] == "do_not_operate"

    action_id = client.get("/api/actions").json()[0]["id"]
    assert client.post(f"/api/actions/{action_id}/close", json={"closed_by": "Fitter Jo"}).status_code == 200
    rig = next(f for f in client.get("/api/dashboard").json()["fleet"] if f["rig_id"] == 1)
    assert rig["status"] == "go"


def test_failed_item_needs_a_comment(client):
    r = prestart(client, items=all_pass(coolant=("fail", "")))
    assert r.status_code == 422


def test_every_item_must_be_answered(client):
    r = prestart(client, items=all_pass()[:-1])
    assert r.status_code == 422


def test_hour_meter_cannot_go_backwards(client):
    prestart(client, hours=1500)
    r = prestart(client, hours=1400)
    assert r.status_code == 422
    assert "lower than the last reading" in r.json()["detail"]


def test_unknown_rig(client):
    assert prestart(client, rig_id=999).status_code == 404


def test_cannot_close_action_twice(client):
    prestart(client, items=all_pass(lights=("fail", "Beacon out")))
    action_id = client.get("/api/actions").json()[0]["id"]
    client.post(f"/api/actions/{action_id}/close", json={"closed_by": "Fitter Jo"})
    r = client.post(f"/api/actions/{action_id}/close", json={"closed_by": "Fitter Jo"})
    assert r.status_code == 409


def test_dashboard_compliance(client):
    prestart(client, rig_id=1)
    prestart(client, rig_id=2)
    d = client.get("/api/dashboard").json()
    assert d["prestarts_done"] == 2
    assert d["compliance_pct"] == 40


def test_csv_export(client):
    prestart(client)
    r = client.get("/api/export/prestarts.csv")
    assert r.status_code == 200
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("id,shift_date")
    assert len(lines) == 2
