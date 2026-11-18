"""Rig Prestart: a prestart checklist for drill crews, with a manager dashboard.

Crew submit a prestart on their phone -> failed items automatically become
maintenance actions -> managers see which rigs are safe to run and what's open.
"""

import csv
import io
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from .checklist import CHECKLIST, ITEMS_BY_KEY
from .db import connect, init_db

PERTH = ZoneInfo("Australia/Perth")
STATIC = Path(__file__).parent / "static"


def now_perth() -> datetime:
    return datetime.now(PERTH)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Rig Prestart", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


# ---------- Request models (validation happens here) ----------

class ItemResult(BaseModel):
    key: str
    result: Literal["pass", "fail", "na"]
    comment: Optional[str] = None


class PrestartIn(BaseModel):
    rig_id: int
    operator: str = Field(min_length=2, max_length=80)
    shift: Literal["day", "night"]
    hour_meter: float = Field(ge=0)
    items: list[ItemResult]
    notes: Optional[str] = None

    @model_validator(mode="after")
    def check_items(self):
        keys = [i.key for i in self.items]
        unknown = set(keys) - set(ITEMS_BY_KEY)
        if unknown:
            raise ValueError(f"Unknown checklist items: {sorted(unknown)}")
        missing = set(ITEMS_BY_KEY) - set(keys)
        if missing:
            raise ValueError(f"Every checklist item must be answered. Missing: {sorted(missing)}")
        if len(keys) != len(set(keys)):
            raise ValueError("Each checklist item can only be answered once")
        for i in self.items:
            if i.result == "fail" and not (i.comment and i.comment.strip()):
                raise ValueError(f"Describe the defect for failed item '{ITEMS_BY_KEY[i.key]['label']}'")
        return self


class CloseActionIn(BaseModel):
    closed_by: str = Field(min_length=2, max_length=80)
    note: Optional[str] = None


# ---------- Pages ----------

@app.get("/", include_in_schema=False)
def crew_page():
    return FileResponse(STATIC / "index.html")


@app.get("/manager", include_in_schema=False)
def manager_page():
    return FileResponse(STATIC / "manager.html")


# ---------- API ----------

@app.get("/api/checklist")
def get_checklist():
    return CHECKLIST


@app.get("/api/rigs")
def get_rigs():
    with connect() as conn:
        rows = conn.execute(
            """SELECT r.*, (SELECT MAX(hour_meter) FROM prestarts p WHERE p.rig_id = r.id) AS last_hour_meter
               FROM rigs r ORDER BY r.name"""
        ).fetchall()
    return [dict(r) for r in rows]


def decide_outcome(items: list[ItemResult]) -> str:
    """Any critical fail stops the rig; any other fail means it runs with defects logged."""
    failed = [ITEMS_BY_KEY[i.key]["severity"] for i in items if i.result == "fail"]
    if "critical" in failed:
        return "do_not_operate"
    if failed:
        return "go_with_defects"
    return "go"


@app.post("/api/prestarts", status_code=201)
def submit_prestart(body: PrestartIn):
    ts = now_perth()
    with connect() as conn:
        rig = conn.execute("SELECT * FROM rigs WHERE id = ?", (body.rig_id,)).fetchone()
        if rig is None:
            raise HTTPException(404, "Rig not found")

        # Data quality check: hour meters only go up.
        last = conn.execute(
            "SELECT MAX(hour_meter) FROM prestarts WHERE rig_id = ?", (body.rig_id,)
        ).fetchone()[0]
        if last is not None and body.hour_meter < last:
            raise HTTPException(
                422, f"Hour meter {body.hour_meter:g} is lower than the last reading ({last:g}) for {rig['name']}"
            )

        outcome = decide_outcome(body.items)
        cur = conn.execute(
            """INSERT INTO prestarts (rig_id, operator, shift, hour_meter, outcome, notes, submitted_at, shift_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (body.rig_id, body.operator.strip(), body.shift, body.hour_meter, outcome,
             body.notes, ts.isoformat(timespec="seconds"), ts.date().isoformat()),
        )
        prestart_id = cur.lastrowid

        conn.executemany(
            "INSERT INTO prestart_items (prestart_id, item_key, result, comment) VALUES (?, ?, ?, ?)",
            [(prestart_id, i.key, i.result, i.comment) for i in body.items],
        )

        # Every failed item becomes a maintenance action.
        actions = []
        for i in body.items:
            if i.result != "fail":
                continue
            item = ITEMS_BY_KEY[i.key]
            desc = f"{item['label']}: {i.comment.strip()}"
            conn.execute(
                """INSERT INTO actions (prestart_id, rig_id, item_key, description, severity, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (prestart_id, body.rig_id, i.key, desc, item["severity"], ts.isoformat(timespec="seconds")),
            )
            actions.append({"item": item["label"], "severity": item["severity"]})

    return {"id": prestart_id, "rig": rig["name"], "outcome": outcome, "actions_created": actions}


@app.get("/api/prestarts")
def list_prestarts(date: Optional[str] = Query(None, description="YYYY-MM-DD, defaults to today (Perth)")):
    day = date or now_perth().date().isoformat()
    with connect() as conn:
        rows = conn.execute(
            """SELECT p.*, r.name AS rig_name FROM prestarts p JOIN rigs r ON r.id = p.rig_id
               WHERE p.shift_date = ? ORDER BY p.submitted_at DESC, p.id DESC""",
            (day,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/actions")
def list_actions(status: Literal["open", "closed", "all"] = "open"):
    sql = """SELECT a.*, r.name AS rig_name FROM actions a JOIN rigs r ON r.id = a.rig_id"""
    params: tuple = ()
    if status != "all":
        sql += " WHERE a.status = ?"
        params = (status,)
    sql += """ ORDER BY CASE a.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 ELSE 2 END, a.created_at"""
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


@app.post("/api/actions/{action_id}/close")
def close_action(action_id: int, body: CloseActionIn):
    with connect() as conn:
        action = conn.execute("SELECT * FROM actions WHERE id = ?", (action_id,)).fetchone()
        if action is None:
            raise HTTPException(404, "Action not found")
        if action["status"] == "closed":
            raise HTTPException(409, "Action is already closed")
        conn.execute(
            "UPDATE actions SET status = 'closed', closed_at = ?, closed_by = ?, close_note = ? WHERE id = ?",
            (now_perth().isoformat(timespec="seconds"), body.closed_by.strip(), body.note, action_id),
        )
    return {"id": action_id, "status": "closed"}


@app.get("/api/dashboard")
def dashboard():
    """Everything the manager screen needs in one call."""
    today = now_perth().date().isoformat()
    with connect() as conn:
        rigs = conn.execute("SELECT * FROM rigs ORDER BY name").fetchall()
        fleet = []
        for rig in rigs:
            latest = conn.execute(
                """SELECT operator, shift, hour_meter, outcome, submitted_at FROM prestarts
                   WHERE rig_id = ? AND shift_date = ? ORDER BY submitted_at DESC, id DESC LIMIT 1""",
                (rig["id"], today),
            ).fetchone()
            open_actions = conn.execute(
                "SELECT COUNT(*) FROM actions WHERE rig_id = ? AND status = 'open'", (rig["id"],)
            ).fetchone()[0]
            # An open critical action keeps a rig stopped even if today's prestart passed.
            open_critical = conn.execute(
                "SELECT COUNT(*) FROM actions WHERE rig_id = ? AND status = 'open' AND severity = 'critical'",
                (rig["id"],),
            ).fetchone()[0]
            if open_critical:
                status = "do_not_operate"
            elif latest is None:
                status = "not_started"
            else:
                status = latest["outcome"]
            fleet.append({
                "rig_id": rig["id"], "rig": rig["name"], "type": rig["type"], "site": rig["site"],
                "status": status, "open_actions": open_actions,
                "last_prestart": dict(latest) if latest else None,
            })

        open_by_sev = {s: 0 for s in ("critical", "high", "low")}
        for row in conn.execute(
            "SELECT severity, COUNT(*) AS n FROM actions WHERE status = 'open' GROUP BY severity"
        ):
            open_by_sev[row["severity"]] = row["n"]

    done = sum(1 for r in fleet if r["last_prestart"] is not None)
    return {
        "date": today,
        "rigs_total": len(fleet),
        "prestarts_done": done,
        "compliance_pct": round(100 * done / len(fleet)) if fleet else 0,
        "open_actions": open_by_sev,
        "fleet": fleet,
    }


@app.get("/api/export/prestarts.csv")
def export_csv():
    """All prestarts as CSV, for finance or audits."""
    with connect() as conn:
        rows = conn.execute(
            """SELECT p.id, p.shift_date, p.submitted_at, r.name AS rig, r.site, p.operator, p.shift,
                      p.hour_meter, p.outcome,
                      (SELECT COUNT(*) FROM prestart_items i WHERE i.prestart_id = p.id AND i.result = 'fail') AS failed_items
               FROM prestarts p JOIN rigs r ON r.id = p.rig_id ORDER BY p.submitted_at"""
        ).fetchall()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(rows[0].keys() if rows else
                    ["id", "shift_date", "submitted_at", "rig", "site", "operator", "shift",
                     "hour_meter", "outcome", "failed_items"])
    writer.writerows([tuple(r) for r in rows])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=prestarts.csv"},
    )
