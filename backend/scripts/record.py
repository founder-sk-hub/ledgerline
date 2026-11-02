"""Run the agent live on a batch from the command line and (optionally) save it as a replay.

    .venv/bin/python backend/scripts/record.py --provider meta --save meta-sample
    .venv/bin/python backend/scripts/record.py --provider private --save private-sample
    .venv/bin/python backend/scripts/record.py --provider meta --limit 3      # quick smoke test

Needs MODEL_API_KEY (meta) or BASETEN_API_KEY (private) in .env. Respects the local budget guard.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ledgerline.agents import Run  # noqa: E402
from ledgerline.config import BUDGET_USD, MAX_CONCURRENCY, providers  # noqa: E402
from ledgerline.db import DB  # noqa: E402
from ledgerline.documents import load_sample_batch  # noqa: E402
from ledgerline.events import Bus  # noqa: E402
from ledgerline.providers import Provider  # noqa: E402
from ledgerline.replay import export_replay  # noqa: E402
from ledgerline.state import evaluate, fold  # noqa: E402
from ledgerline.tools import Books  # noqa: E402


class PrintingBus(Bus):
    def emit(self, run_id, type_, payload=None, *, agent=None, doc_id=None):
        ev = super().emit(run_id, type_, payload, agent=agent, doc_id=doc_id)
        p = payload or {}
        if type_ == "stage.started":
            print(f"\n== {p['stage']} ==", flush=True)
        elif type_ == "llm.call" and not p.get("ok"):
            print(f"  ! model error ({p.get('agent')}): {p.get('error')}", flush=True)
        elif type_ == "doc.extracted":
            ex = p["extraction"]
            print(f"  read  {ex.get('doc_type'):13} {ex.get('vendor_name', '')[:34]:34} {ex.get('gross_total')}", flush=True)
        elif type_ == "doc.failed":
            print(f"  FAIL  {doc_id}: {p.get('error')}", flush=True)
        elif type_ == "decision.verified":
            print(f"  done  {doc_id}: {p['final_status']:9} {p.get('verdict')} {p.get('reason') or ''}", flush=True)
        elif type_ in ("draft.email",):
            print(f"  email {p['to']}: {p['subject']}", flush=True)
        elif type_ == "run.failed":
            print(f"RUN FAILED: {p.get('error')}", flush=True)
        return ev


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["meta", "private"], default="meta")
    ap.add_argument("--limit", type=int, default=0, help="only the first N documents (smoke test)")
    ap.add_argument("--save", help="save the run as data/replays/<name>.json")
    args = ap.parse_args()

    cfg = providers()[args.provider]
    if not cfg.available:
        sys.exit(f"No API key for {cfg.label}. Add it to .env.")
    db = DB()
    if db.total_spend() >= BUDGET_USD:
        sys.exit(f"Local budget guard reached ({db.total_spend():.2f} / {BUDGET_USD} USD).")
    docs = load_sample_batch(db)
    if args.limit:
        docs = docs[: args.limit]
    run_id = uuid.uuid4().hex[:12]
    db.create_run(run_id, "sample", args.provider, "live")
    b = Books(buyer=db.buyer(), vendors=db.ref("vendor"), purchase_orders=db.ref("purchase_order"),
              contracts=db.ref("contract"), history=db.ref("history"))
    b.docs = {d["doc_id"]: d for d in docs}
    print(f"run {run_id} · {cfg.model} @ {cfg.base_url} · {len(docs)} documents")
    t0 = time.time()
    try:
        await Run(run_id, db, PrintingBus(db), Provider(cfg, MAX_CONCURRENCY), b, docs).execute()
    except Exception as e:  # noqa: BLE001 - already logged as run.failed
        print(f"stopped: {e}")
    st = fold(db.run(run_id), db.events(run_id))
    m = st["metrics"]
    print(f"\nstatus {st['run']['status']} · {time.time() - t0:.0f}s · {m['llm_calls']} calls ({m['llm_errors']} errors) · "
          f"${m['cost_usd']:.4f} · EUR at risk {m['eur_at_risk']:,.2f} · total spend so far ${db.total_spend():.2f}")
    ev = evaluate(st) if not args.limit else None
    if ev:
        print(f"benchmark: stopped {ev['anomalous_documents_stopped']}/{ev['anomalous_documents']} anomalous docs · "
              f"flag recall {ev['flag_recall']} · precision {ev['flag_precision']} · decisions {ev['decision_accuracy']}")
        for r in ev["rows"]:
            if not r["decision_ok"] or r["flags"] != r["expected_flags"]:
                print(f"  diff {r['filename']}: expected {r['expected_decision']} {r['expected_flags']} "
                      f"got {r['decision']} {r['flags']}")
    if args.save and st["run"]["status"] == "awaiting_approval":
        meta = export_replay(db, run_id, args.save)
        print(f"saved replay data/replays/{args.save}.json ({meta['stats']})")
    print(f"open: http://localhost:8000/#/run/{run_id}/run")


if __name__ == "__main__":
    asyncio.run(main())
