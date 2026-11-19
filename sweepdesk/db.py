"""SQLite storage for competitions, entries, feeds, settings and your profile."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from .extract import PageInfo
from .scoring import legitimacy, priority, verdict

DEFAULT_MIN_VALUE = 200

SCHEMA = """
CREATE TABLE IF NOT EXISTS comps (
    id INTEGER PRIMARY KEY,
    url TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    value_gbp REAL,
    closes_on TEXT,
    frequency TEXT NOT NULL DEFAULT 'once',
    winners INTEGER,
    entry_method TEXT NOT NULL DEFAULT 'form',
    terms_url TEXT,
    uk_eligible INTEGER,
    paid_entry INTEGER NOT NULL DEFAULT 0,
    legit INTEGER NOT NULL DEFAULT 50,
    red_flags TEXT NOT NULL DEFAULT '[]',
    good_signs TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',  -- active | hidden | won
    notes TEXT NOT NULL DEFAULT '',
    added_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY,
    comp_id INTEGER NOT NULL REFERENCES comps(id) ON DELETE CASCADE,
    entered_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feeds (url TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS profile (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

PROFILE_FIELDS = ["full_name", "email", "phone", "address_line1", "address_line2",
                  "town", "county", "postcode", "date_of_birth"]


def db_path() -> Path:
    return Path(os.environ.get("SWEEPDESK_DB", Path.home() / ".sweepdesk" / "sweepdesk.db"))


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(path) if path else db_path()
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


# ---------------------------------------------------------------- settings/profile


def get_setting(conn, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()


def min_value(conn) -> float:
    return float(get_setting(conn, "min_value", str(DEFAULT_MIN_VALUE)))


def get_profile(conn) -> dict[str, str]:
    return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM profile")}


def set_profile(conn, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO profile (key, value) VALUES (?, ?)", (key, value))
    conn.commit()


# ----------------------------------------------------------------------- comps


def save_comp(conn, info: PageInfo) -> int:
    legit = legitimacy(info)
    row = dict(
        url=info.url, title=info.title or info.url, value_gbp=info.value_gbp,
        closes_on=info.closes_on.isoformat() if info.closes_on else None,
        frequency=info.frequency, winners=info.winners, entry_method=info.entry_method,
        terms_url=info.terms_url,
        uk_eligible=None if info.uk_eligible is None else int(info.uk_eligible),
        paid_entry=int(info.paid_entry), legit=legit,
        red_flags=json.dumps(info.red_flags), good_signs=json.dumps(info.good_signs),
        added_at=datetime.now().isoformat(timespec="seconds"),
    )
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    updates = ", ".join(f"{c} = excluded.{c}" for c in row if c not in ("url", "added_at"))
    conn.execute(f"INSERT INTO comps ({cols}) VALUES ({marks}) "
                 f"ON CONFLICT(url) DO UPDATE SET {updates}", list(row.values()))
    conn.commit()
    return conn.execute("SELECT id FROM comps WHERE url = ?", (info.url,)).fetchone()["id"]


EDITABLE = {"title", "value_gbp", "closes_on", "frequency", "winners", "entry_method",
            "status", "notes", "uk_eligible"}


def update_comp(conn, comp_id: int, **fields) -> None:
    bad = set(fields) - EDITABLE
    if bad:
        raise ValueError(f"cannot edit {', '.join(sorted(bad))}")
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE comps SET {sets} WHERE id = ?", [*fields.values(), comp_id])
    conn.commit()


def record_entry(conn, comp_id: int, when: datetime | None = None) -> None:
    when = when or datetime.now()
    conn.execute("INSERT INTO entries (comp_id, entered_at) VALUES (?, ?)",
                 (comp_id, when.isoformat(timespec="seconds")))
    conn.commit()


def _last_entry(conn, comp_id: int) -> datetime | None:
    row = conn.execute("SELECT MAX(entered_at) AS t FROM entries WHERE comp_id = ?",
                       (comp_id,)).fetchone()
    return datetime.fromisoformat(row["t"]) if row["t"] else None


def is_due(frequency: str, last: datetime | None, now: datetime) -> bool:
    """Whether the rules allow another entry yet. Never more often than allowed."""
    if last is None:
        return True
    if frequency == "daily":
        return last.date() < now.date()
    if frequency == "weekly":
        return now - last >= timedelta(days=7)
    return False  # one entry only


def listing(conn, *, include_all: bool = False, now: datetime | None = None) -> list[dict]:
    """Competitions with derived fields, best first.

    By default hides: hidden/won, closed, below your minimum value, not open to
    UK residents, paid entry, and anything scored 'avoid'.
    """
    now = now or datetime.now()
    floor = min_value(conn)
    out = []
    for r in conn.execute("SELECT * FROM comps"):
        c = dict(r)
        c["red_flags"] = json.loads(c["red_flags"])
        c["good_signs"] = json.loads(c["good_signs"])
        closes = date.fromisoformat(c["closes_on"]) if c["closes_on"] else None
        last = _last_entry(conn, c["id"])
        c["last_entered"] = last
        c["entries"] = conn.execute("SELECT COUNT(*) FROM entries WHERE comp_id = ?",
                                    (c["id"],)).fetchone()[0]
        c["closed"] = bool(closes and closes < now.date())
        c["due"] = not c["closed"] and is_due(c["frequency"], last, now)
        c["verdict"] = verdict(c["legit"])
        c["priority"] = priority(c["value_gbp"], c["winners"], c["entry_method"],
                                 closes, c["legit"], now.date())
        reasons = []
        if c["status"] != "active":
            reasons.append(c["status"])
        if c["closed"]:
            reasons.append("closed")
        if c["value_gbp"] is not None and c["value_gbp"] < floor:
            reasons.append(f"under £{floor:,.0f}")
        if c["uk_eligible"] == 0:
            reasons.append("not open to UK")
        if c["paid_entry"]:
            reasons.append("paid entry")
        if c["verdict"] == "avoid":
            reasons.append("scam risk")
        c["hidden_because"] = reasons
        if include_all or not reasons:
            out.append(c)
    out.sort(key=lambda c: (not c["due"], -c["priority"]))
    return out


def feeds(conn) -> list[str]:
    return [r["url"] for r in conn.execute("SELECT url FROM feeds ORDER BY url")]


def add_feed(conn, url: str) -> None:
    conn.execute("INSERT OR IGNORE INTO feeds (url) VALUES (?)", (url,))
    conn.commit()


def remove_feed(conn, url: str) -> None:
    conn.execute("DELETE FROM feeds WHERE url = ?", (url,))
    conn.commit()


def known_url(conn, url: str) -> bool:
    return conn.execute("SELECT 1 FROM comps WHERE url = ?", (url,)).fetchone() is not None
