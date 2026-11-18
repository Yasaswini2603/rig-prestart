"""SQLite database: schema, connection and seed data."""

import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS rigs (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL UNIQUE,
    type    TEXT NOT NULL,
    site    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prestarts (
    id            INTEGER PRIMARY KEY,
    rig_id        INTEGER NOT NULL REFERENCES rigs(id),
    operator      TEXT NOT NULL,
    shift         TEXT NOT NULL CHECK (shift IN ('day', 'night')),
    hour_meter    REAL NOT NULL,
    outcome       TEXT NOT NULL CHECK (outcome IN ('go', 'go_with_defects', 'do_not_operate')),
    notes         TEXT,
    submitted_at  TEXT NOT NULL,   -- ISO timestamp, Perth time
    shift_date    TEXT NOT NULL    -- YYYY-MM-DD, Perth time
);

CREATE TABLE IF NOT EXISTS prestart_items (
    id           INTEGER PRIMARY KEY,
    prestart_id  INTEGER NOT NULL REFERENCES prestarts(id),
    item_key     TEXT NOT NULL,
    result       TEXT NOT NULL CHECK (result IN ('pass', 'fail', 'na')),
    comment      TEXT
);

CREATE TABLE IF NOT EXISTS actions (
    id           INTEGER PRIMARY KEY,
    prestart_id  INTEGER NOT NULL REFERENCES prestarts(id),
    rig_id       INTEGER NOT NULL REFERENCES rigs(id),
    item_key     TEXT NOT NULL,
    description  TEXT NOT NULL,
    severity     TEXT NOT NULL CHECK (severity IN ('critical', 'high', 'low')),
    status       TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    created_at   TEXT NOT NULL,
    closed_at    TEXT,
    closed_by    TEXT,
    close_note   TEXT
);

CREATE INDEX IF NOT EXISTS idx_prestarts_date ON prestarts(shift_date);
CREATE INDEX IF NOT EXISTS idx_actions_status ON actions(status);
"""

SEED_RIGS = [
    ("RC-01", "Reverse Circulation", "Pilbara – Site A"),
    ("RC-02", "Reverse Circulation", "Pilbara – Site A"),
    ("DD-01", "Diamond Core", "Goldfields – Site B"),
    ("DD-02", "Diamond Core", "Goldfields – Site B"),
    ("AC-01", "Air Core", "Goldfields – Site B"),
]


def db_path() -> str:
    return os.environ.get("RIGBY_DB", "prestart.db")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create tables and add the demo rigs if the database is empty."""
    with connect() as conn:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM rigs").fetchone()[0] == 0:
            conn.executemany("INSERT INTO rigs (name, type, site) VALUES (?, ?, ?)", SEED_RIGS)
