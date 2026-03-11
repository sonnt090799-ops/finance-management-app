from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS category (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL CHECK (kind IN ('income','expense')),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tx (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tx_date TEXT NOT NULL, -- YYYY-MM-DD
  description TEXT NOT NULL,
  amount_cents INTEGER NOT NULL, -- signed: income positive, expense negative
  category_id INTEGER,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (category_id) REFERENCES category(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS budget (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  month TEXT NOT NULL, -- YYYY-MM
  category_id INTEGER NOT NULL,
  amount_cents INTEGER NOT NULL, -- positive
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (month, category_id),
  FOREIGN KEY (category_id) REFERENCES category(id) ON DELETE CASCADE
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    seed_defaults(conn)


def seed_defaults(conn: sqlite3.Connection) -> None:
    # Insert a small starter set (idempotent).
    defaults = [
        ("Salary", "income"),
        ("Freelance", "income"),
        ("Groceries", "expense"),
        ("Rent", "expense"),
        ("Utilities", "expense"),
        ("Dining", "expense"),
        ("Transport", "expense"),
        ("Entertainment", "expense"),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO category (name, kind) VALUES (?, ?)",
        defaults,
    )
    conn.commit()


@dataclass(frozen=True)
class Money:
    cents: int

    @staticmethod
    def from_decimal_str(s: str) -> "Money":
        # Accept "12.34", "12", "-12.34"
        s = s.strip().replace(",", "")
        if s == "":
            raise ValueError("Empty amount")
        neg = s.startswith("-")
        if neg:
            s = s[1:]
        if "." in s:
            whole, frac = s.split(".", 1)
            frac = (frac + "00")[:2]
        else:
            whole, frac = s, "00"
        cents = int(whole or "0") * 100 + int(frac)
        return Money(-cents if neg else cents)

    def abs(self) -> "Money":
        return Money(abs(self.cents))

    def format(self) -> str:
        sign = "-" if self.cents < 0 else ""
        cents = abs(self.cents)
        return f"{sign}${cents // 100:,}.{cents % 100:02d}"


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def to_int(v: Any, default: int | None = None) -> int | None:
    try:
        return int(v)
    except Exception:
        return default


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]

