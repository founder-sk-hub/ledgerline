"""SQLite storage.

The audit trail is event-sourced: every step the agent takes is an append-only row in
`events`. Run state (decisions, drafts, approvals, metrics) is a pure fold over those
events (see state.py), which is what makes runs replayable.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any

from .config import DB_PATH, SAMPLES

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    batch_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    mode TEXT NOT NULL,
    replay_of TEXT
);
CREATE TABLE IF NOT EXISTS events (
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    ts REAL NOT NULL,
    type TEXT NOT NULL,
    agent TEXT,
    doc_id TEXT,
    payload TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    filename TEXT NOT NULL,
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    meta TEXT NOT NULL,
    PRIMARY KEY (batch_id, doc_id)
);
CREATE TABLE IF NOT EXISTS reference (
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (kind, key)
);
CREATE TABLE IF NOT EXISTS spend (
    ts REAL NOT NULL,
    run_id TEXT,
    provider TEXT,
    model TEXT,
    cost_usd REAL NOT NULL
);
"""

REFERENCE_FILES = {
    "vendor": ("vendors.json", "vendor_id"),
    "purchase_order": ("purchase_orders.json", "po_number"),
    "contract": ("contracts.json", "contract_id"),
    "history": ("invoice_history.json", None),
}


class DB:
    def __init__(self, path=DB_PATH):
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.lock = threading.RLock()
        self.conn.executescript(SCHEMA)
        self._seq: dict[str, int] = {}
        self.seed_reference()

    # ------------------------------------------------------------ reference data
    def seed_reference(self) -> None:
        """(Re)load the synthetic company's master data: vendors, POs, contracts, paid history."""
        ref = SAMPLES / "reference"
        with self.lock:
            self.conn.execute("DELETE FROM reference")
            for kind, (fname, key) in REFERENCE_FILES.items():
                rows = json.loads((ref / fname).read_text())
                for i, row in enumerate(rows):
                    k = row[key] if key else f"{row['vendor_id']}:{row['invoice_number']}:{i}"
                    self.conn.execute("INSERT INTO reference VALUES (?,?,?)", (kind, k, json.dumps(row)))
            buyer = json.loads((ref / "buyer.json").read_text())
            self.conn.execute("INSERT INTO reference VALUES (?,?,?)", ("buyer", "buyer", json.dumps(buyer)))

    def ref(self, kind: str) -> list[dict]:
        with self.lock:
            rows = self.conn.execute("SELECT data FROM reference WHERE kind=? ORDER BY key", (kind,)).fetchall()
        return [json.loads(r["data"]) for r in rows]

    def buyer(self) -> dict:
        return self.ref("buyer")[0]

    # ------------------------------------------------------------ documents
    def upsert_document(self, batch_id: str, doc: dict) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?,?,?,?)",
                (doc["doc_id"], batch_id, doc["idx"], doc["filename"], doc["kind"], doc["path"], doc["sha256"],
                 json.dumps(doc.get("meta", {}))),
            )

    def documents(self, batch_id: str) -> list[dict]:
        with self.lock:
            rows = self.conn.execute("SELECT * FROM documents WHERE batch_id=? ORDER BY idx", (batch_id,)).fetchall()
        return [self._doc(r) for r in rows]

    def document(self, doc_id: str) -> dict | None:
        with self.lock:
            r = self.conn.execute("SELECT * FROM documents WHERE doc_id=? LIMIT 1", (doc_id,)).fetchone()
        return self._doc(r) if r else None

    @staticmethod
    def _doc(r: sqlite3.Row) -> dict:
        d = dict(r)
        d["meta"] = json.loads(d["meta"])
        return d

    # ------------------------------------------------------------ runs + events
    def create_run(self, run_id: str, batch_id: str, provider: str, mode: str, replay_of: str | None = None) -> None:
        with self.lock:
            self.conn.execute("INSERT INTO runs VALUES (?,?,?,?,?,?)",
                              (run_id, time.time(), batch_id, provider, mode, replay_of))
            self._seq[run_id] = 0

    def runs(self) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute("SELECT * FROM runs ORDER BY created_at DESC").fetchall()]

    def run(self, run_id: str) -> dict | None:
        with self.lock:
            r = self.conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return dict(r) if r else None

    def append_event(self, run_id: str, type_: str, payload: dict[str, Any], agent: str | None = None,
                     doc_id: str | None = None, ts: float | None = None) -> dict:
        with self.lock:
            if run_id not in self._seq:
                row = self.conn.execute("SELECT MAX(seq) FROM events WHERE run_id=?", (run_id,)).fetchone()
                self._seq[run_id] = row[0] or 0
            self._seq[run_id] += 1
            seq = self._seq[run_id]
            ev = {"run_id": run_id, "seq": seq, "ts": ts or time.time(), "type": type_, "agent": agent,
                  "doc_id": doc_id, "payload": payload}
            self.conn.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?)",
                              (run_id, seq, ev["ts"], type_, agent, doc_id, json.dumps(payload, default=str)))
        return ev

    def events(self, run_id: str, after: int = 0) -> list[dict]:
        with self.lock:
            rows = self.conn.execute("SELECT * FROM events WHERE run_id=? AND seq>? ORDER BY seq",
                                     (run_id, after)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d["payload"])
            out.append(d)
        return out

    # ------------------------------------------------------------ spend guard
    def add_spend(self, run_id: str, provider: str, model: str, cost: float) -> None:
        with self.lock:
            self.conn.execute("INSERT INTO spend VALUES (?,?,?,?,?)", (time.time(), run_id, provider, model, cost))

    def total_spend(self) -> float:
        with self.lock:
            return float(self.conn.execute("SELECT COALESCE(SUM(cost_usd),0) FROM spend").fetchone()[0])
