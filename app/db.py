import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "ml.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS developments (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,              -- HPD | HCR
    hid TEXT,                          -- HCR development id
    name TEXT NOT NULL,
    address TEXT,
    borough TEXT,                      -- NYC borough, or county name upstate
    county TEXT,
    kind TEXT,                         -- Coop | Rental
    senior_only INTEGER DEFAULT 0,
    units INTEGER,
    agent_name TEXT,
    agent_address TEXT,
    phone TEXT,
    email TEXT,
    email_source TEXT,                 -- official | company-match
    agency TEXT,                       -- DHCR | HFA | HUD (HCR side)
    federally_subsidized INTEGER,
    on_open_list INTEGER DEFAULT 0,    -- appears on HPD open-waitlist PDF
    on_short_list INTEGER DEFAULT 0,   -- appears on HPD short-waitlist PDF
    wl_studio TEXT, wl_1br TEXT, wl_2br TEXT, wl_3br TEXT, wl_4br TEXT,
    lat REAL, lng REAL,
    miles_to_midtown REAL,
    est_transit_min INTEGER,
    UNIQUE(source, name, address)
);

CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY,
    development_id INTEGER NOT NULL REFERENCES developments(id),
    to_email TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',   -- draft | approved | sent | error | skipped
    error TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    sent_at TEXT,
    UNIQUE(development_id)
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con
