from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
create table if not exists runs (
    id integer primary key,
    site text not null,
    started_at text not null,
    items integer not null default 0
);
create table if not exists snapshots (
    run_id integer not null references runs(id),
    site text not null,
    key text not null,
    price real,
    data text not null,
    seen_at text not null
);
create index if not exists snapshots_key on snapshots(site, key, seen_at);
"""


@dataclass
class Change:
    key: str
    title: str
    old: float | None
    new: float | None

    @property
    def percent(self) -> float:
        if not self.old or self.new is None:
            return 0.0
        return (self.new - self.old) / self.old * 100


class Store:
    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)

    def save_run(self, site: str, rows: list[dict], key: str) -> tuple[int, list[Change], list[dict]]:
        """Store a crawl and return (run id, price changes, new items) against the previous snapshot."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        prev = self.latest(site)
        cur = self.db.execute("insert into runs(site, started_at, items) values (?, ?, ?)",
                              (site, now, len(rows)))
        run_id = cur.lastrowid
        changes, new = [], []
        seen = set()
        for row in rows:
            k = row.get(key)
            if not k or k in seen:
                continue
            seen.add(k)
            price = row.get("price")
            self.db.execute(
                "insert into snapshots(run_id, site, key, price, data, seen_at) values (?, ?, ?, ?, ?, ?)",
                (run_id, site, k, price, json.dumps(row, ensure_ascii=False), now),
            )
            if k not in prev:
                new.append(row)
            elif prev[k] != price:
                changes.append(Change(k, str(row.get("title") or k), prev[k], price))
        self.db.commit()
        return run_id, changes, new

    def latest(self, site: str) -> dict[str, float | None]:
        run = self.db.execute("select max(id) from runs where site = ?", (site,)).fetchone()[0]
        if run is None:
            return {}
        return dict(self.db.execute("select key, price from snapshots where run_id = ?", (run,)))

    def history(self, site: str, key: str) -> list[tuple[str, float | None]]:
        return self.db.execute(
            "select seen_at, price from snapshots where site = ? and key = ? order by seen_at",
            (site, key),
        ).fetchall()

    def rows(self, site: str, run_id: int | None = None) -> list[dict]:
        if run_id is None:
            run_id = self.db.execute("select max(id) from runs where site = ?", (site,)).fetchone()[0]
        return [json.loads(d) for (d,) in self.db.execute(
            "select data from snapshots where run_id = ? order by rowid", (run_id,))]

    def close(self):
        self.db.close()
