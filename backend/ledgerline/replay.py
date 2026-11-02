"""Record and replay runs.

A replay file is the exact event log of a real live run (every Muse Spark call with its
latency, token usage, cost and response id; every tool call and result). Replaying re-emits
those events with their original timing (optionally sped up) so anyone can watch the run
without API keys. The human approval step is never recorded: in a replay, you are the approver.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
from datetime import datetime, timezone

from .config import REPLAYS, ROOT
from .db import DB
from .events import Bus
from .state import fold

FORMAT = "ledgerline-replay/1"
STOP_AT = "run.awaiting_approval"


def export_replay(db: DB, run_id: str, name: str) -> dict:
    run = db.run(run_id)
    events = db.events(run_id)
    if not run or not events:
        raise ValueError(f"run {run_id} not found")
    cut = next((i for i, e in enumerate(events) if e["type"] == STOP_AT), None)
    if cut is None:
        raise ValueError("run did not reach the approval gate; only complete runs can be recorded")
    events = events[: cut + 1]
    t0 = events[0]["ts"]
    st = fold(run, events)
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                                text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = ""
    data = {
        "format": FORMAT, "name": name, "source_run_id": run_id, "batch_id": run["batch_id"],
        "recorded_at": datetime.fromtimestamp(t0, timezone.utc).isoformat(timespec="seconds"),
        "git_commit": commit, "provider": st["run"].get("provider"),
        "stats": {k: st["metrics"][k] for k in ("llm_calls", "cost_usd", "wall_seconds", "eur_at_risk",
                                                "input_tokens", "output_tokens", "documents")},
        "events": [{"t": round(e["ts"] - t0, 3), "type": e["type"], "agent": e["agent"], "doc_id": e["doc_id"],
                    "payload": e["payload"]} for e in events],
    }
    REPLAYS.mkdir(parents=True, exist_ok=True)
    (REPLAYS / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str))
    return {k: v for k, v in data.items() if k != "events"}


def list_replays() -> list[dict]:
    out = []
    for p in sorted(REPLAYS.glob("*.json")):
        try:
            data = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
        if data.get("format") != FORMAT:
            continue
        out.append({"id": p.stem, **{k: v for k, v in data.items() if k != "events"}})
    return out


def load_replay(replay_id: str) -> dict:
    path = REPLAYS / f"{replay_id}.json"
    if not path.exists() or path.parent != REPLAYS:
        raise FileNotFoundError(replay_id)
    return json.loads(path.read_text())


async def play(db: DB, bus: Bus, run_id: str, data: dict, speed: float = 4.0, max_gap: float = 1.5) -> None:
    prev = 0.0
    for e in data["events"]:
        gap = (e["t"] - prev) / max(speed, 0.1)
        prev = e["t"]
        if gap > 0:
            await asyncio.sleep(min(gap, max_gap))
        payload = e["payload"]
        if e["type"] == "run.started":
            payload = {**payload, "replay": {"id": data.get("name"), "recorded_at": data.get("recorded_at"),
                                             "source_run_id": data.get("source_run_id"), "speed": speed,
                                             "git_commit": data.get("git_commit"), "played_at": time.time(),
                                             "wall_seconds": data.get("stats", {}).get("wall_seconds")}}
        bus.emit(run_id, e["type"], payload, agent=e.get("agent"), doc_id=e.get("doc_id"))
