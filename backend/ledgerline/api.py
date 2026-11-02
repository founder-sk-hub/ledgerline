"""HTTP API + static frontend. Run: uvicorn ledgerline.api:app (from backend/)."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from . import replay as replays
from .agents import Run
from .config import BUDGET_USD, FRONTEND_DIST, MAX_CONCURRENCY, MODE, RUNTIME, providers
from .db import DB
from .documents import document_text, load_sample_batch, page_images, register_file
from .events import Bus
from .execution import approval_items, build_execution, export_dir
from .providers import Provider
from .state import evaluate, fold
from .tools import Books

db = DB()
bus = Bus(db)
tasks: dict[str, asyncio.Task] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    load_sample_batch(db)
    yield
    for t in tasks.values():
        t.cancel()


app = FastAPI(title="Ledgerline", lifespan=lifespan)


def books() -> Books:
    return Books(buyer=db.buyer(), vendors=db.ref("vendor"), purchase_orders=db.ref("purchase_order"),
                 contracts=db.ref("contract"), history=db.ref("history"))


def live_enabled() -> bool:
    return MODE == "live"


# ---------------------------------------------------------------- config & data
@app.get("/api/config")
def config():
    return {"mode": MODE, "live_enabled": live_enabled(),
            "providers": [p.public() for p in providers().values()], "replays": replays.list_replays(),
            "budget_usd": BUDGET_USD, "spent_usd": round(db.total_spend(), 4), "buyer": db.buyer()}


@app.get("/api/reference")
def reference():
    return {"buyer": db.buyer(), "vendors": db.ref("vendor"), "purchase_orders": db.ref("purchase_order"),
            "contracts": db.ref("contract"), "history": db.ref("history")}


@app.get("/api/batches/{batch_id}")
def batch(batch_id: str):
    docs = db.documents(batch_id)
    if not docs:
        raise HTTPException(404, "batch not found")
    return {"batch_id": batch_id, "documents": [_public_doc(d) for d in docs]}


@app.post("/api/batches")
async def upload(files: list[UploadFile] = File(...)):
    if not live_enabled():
        raise HTTPException(403, "Uploads need live mode (set LEDGERLINE_MODE=live and a model API key).")
    if len(files) > 60:
        raise HTTPException(400, "max 60 files per batch")
    batch_id = "up-" + uuid.uuid4().hex[:8]
    folder = RUNTIME / "uploads" / batch_id
    folder.mkdir(parents=True)
    taken: set[str] = set()
    docs = []
    for i, f in enumerate(files):
        name = re.sub(r"[^\w.\- ()]+", "_", Path(f.filename or f"file{i}").name)[:120]
        path = folder / f"{i:02d}_{name}"
        path.write_bytes(await f.read())
        try:
            docs.append(register_file(db, batch_id, i, path, taken))
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
    return {"batch_id": batch_id, "documents": [_public_doc(d) for d in docs]}


def _public_doc(d: dict) -> dict:
    return {k: d[k] for k in ("doc_id", "idx", "filename", "kind", "meta")}


@app.get("/api/docs/{doc_id}/pages/{n}")
def page(doc_id: str, n: int):
    doc = db.document(doc_id)
    if not doc:
        raise HTTPException(404)
    pages = page_images(doc)
    if not 1 <= n <= len(pages):
        raise HTTPException(404)
    return FileResponse(pages[n - 1], media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})


@app.get("/api/docs/{doc_id}/text")
def text(doc_id: str):
    doc = db.document(doc_id)
    if not doc:
        raise HTTPException(404)
    return {"text": document_text(doc)}


@app.get("/api/docs/{doc_id}/file")
def original(doc_id: str):
    doc = db.document(doc_id)
    if not doc:
        raise HTTPException(404)
    return FileResponse(doc["path"], filename=doc["filename"])


# ---------------------------------------------------------------- runs
class RunRequest(BaseModel):
    mode: str = "replay"  # replay | live
    provider: str = "meta"
    batch_id: str = "sample"
    replay_id: str | None = None
    speed: float = 4.0


@app.post("/api/runs")
async def start_run(req: RunRequest):
    run_id = uuid.uuid4().hex[:12]
    if req.mode == "replay":
        available = replays.list_replays()
        rid = req.replay_id or next((r["id"] for r in available if (r.get("provider") or {}).get("key") == req.provider),
                                    available[0]["id"] if available else None)
        if not rid:
            raise HTTPException(404, "No recorded runs yet (data/replays is empty).")
        try:
            data = replays.load_replay(rid)
        except FileNotFoundError as e:
            raise HTTPException(404, f"replay {rid} not found") from e
        db.create_run(run_id, data["batch_id"], (data.get("provider") or {}).get("key", req.provider), "replay", rid)
        tasks[run_id] = asyncio.create_task(replays.play(db, bus, run_id, data, speed=req.speed))
        return {"run_id": run_id, "mode": "replay", "replay_id": rid}

    if not live_enabled():
        raise HTTPException(403, "Live runs are disabled. Set LEDGERLINE_MODE=live in .env (see README).")
    cfg = providers().get(req.provider)
    if not cfg:
        raise HTTPException(400, f"unknown provider {req.provider}")
    if not cfg.available:
        raise HTTPException(400, f"No API key configured for {cfg.label}.")
    if db.total_spend() >= BUDGET_USD:
        raise HTTPException(402, f"Local budget guard reached ({BUDGET_USD} USD). Raise LEDGERLINE_BUDGET_USD.")
    docs = db.documents(req.batch_id)
    if not docs:
        raise HTTPException(404, "batch not found")
    db.create_run(run_id, req.batch_id, req.provider, "live")
    b = books()
    b.docs = {d["doc_id"]: d for d in docs}
    run = Run(run_id, db, bus, Provider(cfg, MAX_CONCURRENCY), b, docs)
    tasks[run_id] = asyncio.create_task(_guard(run.execute()))
    return {"run_id": run_id, "mode": "live"}


async def _guard(coro):
    try:
        await coro
    except Exception:  # already recorded as run.failed
        pass


@app.get("/api/runs")
def list_runs():
    out = []
    for r in db.runs()[:50]:
        st = fold(r, db.events(r["run_id"]))
        out.append({**r, "status": st["run"]["status"], "provider": st["run"].get("provider"),
                    "metrics": {k: st["metrics"][k] for k in ("documents", "processed", "eur_at_risk", "cost_usd")}})
    return out


def _state(run_id: str) -> dict:
    run = db.run(run_id)
    if not run:
        raise HTTPException(404, "run not found")
    st = fold(run, db.events(run_id))
    st["approval_items"] = approval_items(st) if st["approval"] else []
    st["evaluation"] = evaluate(st) if st["run"]["status"] in ("awaiting_approval", "completed") else None
    return st


@app.get("/api/runs/{run_id}")
def run_state(run_id: str):
    return _state(run_id)


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str, after: int = 0):
    if not db.run(run_id):
        raise HTTPException(404, "run not found")

    async def gen():
        async for ev in bus.stream(run_id, after):
            yield {"event": "message", "id": str(ev.get("seq", 0)), "data": json.dumps(ev, default=str)}

    return EventSourceResponse(gen())


class Approval(BaseModel):
    item: str
    decision: str  # approved | rejected
    note: str = ""
    actor: str = "human approver"


@app.post("/api/runs/{run_id}/approvals")
def approve(run_id: str, a: Approval):
    st = _state(run_id)
    if st["run"]["status"] != "awaiting_approval":
        raise HTTPException(409, f"run is {st['run']['status']}, not awaiting approval")
    if a.decision not in ("approved", "rejected"):
        raise HTTPException(400, "decision must be approved or rejected")
    if a.item not in {i["item"] for i in st["approval_items"]}:
        raise HTTPException(404, f"unknown approval item {a.item}")
    bus.emit(run_id, "approval.decided", {"item": a.item, "decision": a.decision, "note": a.note[:500],
                                          "actor": a.actor[:80]}, agent="human")
    return {"ok": True}


@app.post("/api/runs/{run_id}/execute")
def execute(run_id: str):
    st = _state(run_id)
    if st["run"]["status"] != "awaiting_approval":
        raise HTTPException(409, f"run is {st['run']['status']}")
    pending = [i["item"] for i in st["approval_items"] if i["decision"] == "pending"]
    if pending:
        raise HTTPException(409, f"{len(pending)} item(s) still pending a decision")
    result = build_execution(st, run_id)
    bus.emit(run_id, "run.executed", result, agent="human")
    return result


@app.get("/api/runs/{run_id}/exports/{name}")
def export(run_id: str, name: str):
    path = export_dir(run_id) / Path(name).name
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, filename=f"ledgerline-{run_id}-{path.name}")


class RecordRequest(BaseModel):
    name: str


@app.post("/api/runs/{run_id}/record")
def record(run_id: str, req: RecordRequest):
    if not live_enabled():
        raise HTTPException(403, "recording is only available in live mode")
    name = re.sub(r"[^a-z0-9-]+", "-", req.name.lower()).strip("-")[:60] or run_id
    try:
        return replays.export_replay(db, run_id, name)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


# ---------------------------------------------------------------- frontend
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        target = FRONTEND_DIST / path
        if path and target.is_file() and FRONTEND_DIST in target.resolve().parents:
            return FileResponse(target)
        return FileResponse(FRONTEND_DIST / "index.html")
else:
    @app.get("/", include_in_schema=False)
    def root():
        return JSONResponse({"ledgerline": "API running. Build the frontend: cd frontend && npm i && npm run build"})
