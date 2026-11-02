"""Append-only event log + in-process fan-out for the live timeline (SSE)."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, AsyncIterator

from .db import DB

TERMINAL = {"run.awaiting_approval", "run.completed", "run.failed"}


class Bus:
    def __init__(self, db: DB):
        self.db = db
        self.subs: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def emit(self, run_id: str, type_: str, payload: dict[str, Any] | None = None, *, agent: str | None = None,
             doc_id: str | None = None) -> dict:
        ev = self.db.append_event(run_id, type_, payload or {}, agent=agent, doc_id=doc_id)
        for q in list(self.subs[run_id]):
            q.put_nowait(ev)
        return ev

    async def stream(self, run_id: str, after: int = 0) -> AsyncIterator[dict]:
        """Backlog first, then live events. Never misses or duplicates an event."""
        q: asyncio.Queue = asyncio.Queue()
        self.subs[run_id].add(q)
        try:
            last = after
            for ev in self.db.events(run_id, after):
                last = ev["seq"]
                yield ev
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield {"type": "ping", "seq": last}
                    continue
                if ev["seq"] <= last:
                    continue
                last = ev["seq"]
                yield ev
        finally:
            self.subs[run_id].discard(q)
