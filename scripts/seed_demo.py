"""Load a realistic morning of prestarts so the manager screen has something to show.

Run from the project folder:  python -m scripts.seed_demo
"""

from fastapi.testclient import TestClient

from app.checklist import CHECKLIST
from app.main import app


def items(**fails):
    out = []
    for i in CHECKLIST:
        if i["key"] in fails:
            out.append({"key": i["key"], "result": "fail", "comment": fails[i["key"]]})
        else:
            out.append({"key": i["key"], "result": "pass"})
    return out


DEMO = [
    (1, "Sam Taylor", 12450.5, items()),
    (2, "Priya Nair", 9820.0, items(hoses="Weeping fitting on rotation head hose",
                                    lights="Rear work light out")),
    (3, "Jack Morrison", 15302.2, items(estops="Drill panel e-stop not latching")),
    (4, "Lena Fischer", 7710.8, items(housekeeping="Core trays stacked on walkway")),
]

with TestClient(app) as client:
    for rig_id, operator, hours, its in DEMO:
        r = client.post("/api/prestarts", json={
            "rig_id": rig_id, "operator": operator, "shift": "day", "hour_meter": hours, "items": its,
        })
        print(rig_id, r.status_code, r.json().get("outcome", r.json()))
    print("Done. AC-01 is left without a prestart so it shows as 'not started'.")
