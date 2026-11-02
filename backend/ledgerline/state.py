"""Fold a run's event log into the state the UI shows. Pure function of the events."""

from __future__ import annotations

import json
import statistics
from typing import Any

from .config import POLICY, SAMPLES

OPEN_STATUSES = {"hold", "reject", "escalate"}


def fold(run: dict, events: list[dict]) -> dict:
    st: dict[str, Any] = {
        "run": {**run, "status": "running", "error": None, "started_at": None, "ended_at": None},
        "stage": None, "stages": [], "plan": None, "docs": {}, "order": [], "payment_batch": None,
        "emails": [], "approval": None, "approvals": {}, "executed": None, "system": [], "last_seq": 0,
    }
    llm_calls: list[dict] = []
    for ev in events:
        t, p, did = ev["type"], ev["payload"], ev.get("doc_id")
        st["last_seq"] = ev["seq"]
        doc = st["docs"].get(did) if did else None
        if t == "run.started":
            st["run"]["started_at"] = ev["ts"]
            st["run"]["provider"] = p["provider"]
            if p.get("replay"):
                st["run"]["replay"] = p["replay"]
            for d in p["docs"]:
                st["docs"][d["doc_id"]] = {**d, "status": "queued", "extraction": None, "decision": None,
                                           "verification": None, "final_status": None, "at_risk_eur": 0.0,
                                           "steps": []}
                st["order"].append(d["doc_id"])
        elif t == "stage.started":
            st["stage"] = p["stage"]
            st["stages"].append({"stage": p["stage"], "ts": ev["ts"]})
            if p["stage"] == "intake":
                for d in st["docs"].values():
                    d["status"] = "reading"
            if p["stage"] == "review":
                for d in st["docs"].values():
                    if d["status"] == "extracted":
                        d["status"] = "investigating"
        elif t == "plan.created":
            st["plan"] = p
        elif t == "doc.extracted" and doc:
            doc["extraction"] = p["extraction"]
            doc["status"] = "extracted"
        elif t == "doc.failed" and doc:
            doc["status"] = "failed"
            doc["error"] = p.get("error")
        elif t == "decision.proposed" and doc:
            doc["decision"] = p
            doc["status"] = "verifying"
        elif t == "decision.verified" and doc:
            doc["verification"] = p
            doc["final_status"] = p["final_status"]
            doc["at_risk_eur"] = (doc["decision"] or {}).get("at_risk_eur", 0.0) if p["final_status"] != "approve" else 0.0
            doc["status"] = "done"
        elif t == "draft.payment_batch":
            st["payment_batch"] = p
        elif t == "draft.email":
            st["emails"] = [e for e in st["emails"] if e["email_id"] != p["email_id"]] + [p]
        elif t == "approval.requested":
            st["approval"] = {**p, "ts": ev["ts"]}
        elif t == "run.awaiting_approval":
            st["run"]["status"] = "awaiting_approval"
            st["run"]["ended_at"] = ev["ts"]
        elif t == "approval.decided":
            st["approvals"][p["item"]] = p
        elif t == "run.executed":
            st["executed"] = p
            st["run"]["status"] = "completed"
        elif t == "run.failed":
            st["run"]["status"] = "failed"
            st["run"]["error"] = p.get("error")
            st["run"]["ended_at"] = ev["ts"]

        if t == "llm.call":
            llm_calls.append({**p, "ts": ev["ts"], "doc_id": did})
        if doc is not None and t in ("llm.call", "tool.called", "tool.result", "agent.message", "doc.extracted",
                                     "decision.proposed", "decision.verified", "doc.failed", "media.transcribed",
                                     "media.segmented"):
            doc["steps"].append({"seq": ev["seq"], "ts": ev["ts"], "type": t, "agent": ev.get("agent"),
                                 "payload": _slim(t, p)})
        elif did is None and t in ("llm.call", "tool.called", "tool.result", "agent.message"):
            st["system"].append({"seq": ev["seq"], "ts": ev["ts"], "type": t, "agent": ev.get("agent"),
                                 "payload": _slim(t, p)})

    st["docs"] = [st["docs"][d] for d in st["order"]]
    del st["order"]
    st["metrics"] = metrics(st, llm_calls)
    return st


def _slim(t: str, p: dict) -> dict:
    if t == "doc.extracted":
        ex = p["extraction"]
        return {"doc_type": ex.get("doc_type"), "vendor_name": ex.get("vendor_name"),
                "invoice_number": ex.get("invoice_number"), "gross_total": ex.get("gross_total")}
    return p


def metrics(st: dict, llm_calls: list[dict]) -> dict:
    docs = st["docs"]
    done = [d for d in docs if d["final_status"]]
    flagged = [d for d in done if d["final_status"] in OPEN_STATUSES]
    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    flag_counts: dict[str, int] = {}
    for d in done:
        by_status[d["final_status"]] = by_status.get(d["final_status"], 0) + 1
        typ = (d["extraction"] or {}).get("doc_type", "unreadable")
        by_type[typ] = by_type.get(typ, 0) + 1
        for f in (d["decision"] or {}).get("flags", []):
            flag_counts[f["code"]] = flag_counts.get(f["code"], 0) + 1
    ok_calls = [c for c in llm_calls if c.get("ok")]
    lat = [c["latency_ms"] for c in ok_calls]
    by_agent: dict[str, dict] = {}
    for c in ok_calls:
        a = by_agent.setdefault(c["agent"], {"calls": 0, "cost_usd": 0.0, "latency_ms": 0})
        a["calls"] += 1
        a["cost_usd"] += c["cost_usd"]
        a["latency_ms"] += c["latency_ms"]
    for a in by_agent.values():
        a["avg_latency_ms"] = int(a.pop("latency_ms") / max(a["calls"], 1))
        a["cost_usd"] = round(a["cost_usd"], 4)
    wall = (st["run"]["ended_at"] or (st["stages"][-1]["ts"] if st["stages"] else 0)) - (st["run"]["started_at"] or 0)
    if st["run"].get("replay", {}).get("wall_seconds"):  # replays are sped up; report the recorded run's time
        wall = st["run"]["replay"]["wall_seconds"]
    manual = len(docs) * POLICY["manual_minutes_per_document"]
    review = len(flagged) * POLICY["review_minutes_per_flag"] + 0.1 * len(done)
    verified = [d["verification"] for d in done if d["verification"] and d["verification"].get("verdict") != "skipped"]
    pay = st["payment_batch"] or {}
    return {
        "documents": len(docs), "processed": len(done), "by_status": by_status, "by_type": by_type,
        "flags": flag_counts, "flagged_documents": len(flagged),
        "eur_at_risk": round(sum(d["at_risk_eur"] for d in flagged), 2),
        "eur_payment_batch": pay.get("total", 0.0), "payments": len(pay.get("items", [])),
        "emails": len(st["emails"]),
        "llm_calls": len(llm_calls), "llm_errors": len(llm_calls) - len(ok_calls),
        "input_tokens": sum(c.get("input_tokens", 0) for c in ok_calls),
        "output_tokens": sum(c.get("output_tokens", 0) for c in ok_calls),
        "reasoning_tokens": sum(c.get("reasoning_tokens", 0) for c in ok_calls),
        "cost_usd": round(sum(c.get("cost_usd", 0) for c in ok_calls), 4),
        "avg_latency_ms": int(statistics.mean(lat)) if lat else 0,
        "p95_latency_ms": int(sorted(lat)[int(0.95 * (len(lat) - 1))]) if lat else 0,
        "by_agent": by_agent,
        "models": sorted({c["model"] for c in ok_calls}),
        "wall_seconds": round(max(wall, 0), 1),
        "manual_minutes": manual, "human_review_minutes": round(review, 1),
        "minutes_saved": round(max(manual - review, 0), 1),
        "assumptions": {"manual_minutes_per_document": POLICY["manual_minutes_per_document"],
                        "review_minutes_per_flag": POLICY["review_minutes_per_flag"]},
        "verified": len(verified),
        "verifier_confirmed": sum(1 for v in verified if v.get("verdict") == "confirmed"),
        "verifier_escalations": sum(1 for d in done if (d["verification"] or {}).get("escalated")),
        "avg_verifier_confidence": round(statistics.mean([float(v.get("overall_confidence") or 0) for v in verified]), 3)
        if verified else None,
    }


def evaluate(st: dict) -> dict | None:
    """Score a run on the synthetic sample batch against its planted ground truth."""
    gt_path = SAMPLES / "ground_truth.json"
    if st["run"].get("batch_id") != "sample" or not gt_path.exists():
        return None
    truth = {t["filename"]: t for t in json.loads(gt_path.read_text())["documents"]}
    tp = fp = fn = 0
    decisions_ok = 0
    rows = []
    for d in st["docs"]:
        t = truth.get(d["filename"])
        if not t or not d["final_status"]:
            continue
        expected = set(t["flags"])
        got = {f["code"] for f in (d["decision"] or {}).get("flags", [])}
        if "VAT_ARITHMETIC" in got and "ARITHMETIC" in expected:
            got = (got - {"VAT_ARITHMETIC"}) | {"ARITHMETIC"}
        tp += len(expected & got)
        fp += len(got - expected)
        fn += len(expected - got)
        caught = bool(expected) == bool(got - {"CONTRACT_PRICE_CHANGE"} or (expected & got))
        decision_ok = d["final_status"] == t["decision"] or (t["decision"] in OPEN_STATUSES
                                                              and d["final_status"] in OPEN_STATUSES)
        decisions_ok += decision_ok
        rows.append({"filename": d["filename"], "expected_flags": sorted(expected), "flags": sorted(got),
                     "expected_decision": t["decision"], "decision": d["final_status"], "decision_ok": decision_ok,
                     "caught": caught})
    planted = sum(1 for t in truth.values() if t["flags"] and t["decision"] in OPEN_STATUSES)
    caught_docs = sum(1 for r in rows if r["expected_decision"] in OPEN_STATUSES and r["decision"] in OPEN_STATUSES)
    return {
        "documents": len(rows), "flag_precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "flag_recall": round(tp / (tp + fn), 3) if tp + fn else None, "decision_accuracy": round(decisions_ok / len(rows), 3)
        if rows else None, "anomalous_documents": planted, "anomalous_documents_stopped": caught_docs,
        "eur_at_risk_planted": round(sum(t.get("at_risk", 0) for t in truth.values()), 2), "rows": rows,
    }
