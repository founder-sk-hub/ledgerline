"""End-to-end plumbing test through the HTTP API with a scripted stand-in for the model.

The fake follows the same protocol as Muse Spark (structured outputs, tool calls) so this
exercises the orchestrator, event log, state fold, approval gate, SEPA export and replay
recorder without network access. It is a test double only - never used at runtime.
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from conftest import perfect_extraction

FULL = {"DUPLICATE", "BANK_DETAILS_CHANGED", "SENDER_DOMAIN_MISMATCH"}


def tc(i, name, args):
    return SimpleNamespace(id=f"call_{i}_{name}", type="function",
                           function=SimpleNamespace(name=name, arguments=json.dumps(args)))


class FakeMedia:
    """Stands in for Muse Voice Transcribe and SAM 3.1."""

    async def transcribe(self, wav, *, languages, keywords):
        from ledgerline.providers import MediaResult

        return MediaResult({"transcript": "Nur 28 Kannen statt 40 gekommen.", "turns": [], "audioDurationMs": 22880},
                           5, 0.001, "muse-voice-transcribe-1.0")

    async def segment(self, jpeg, phrase):
        from ledgerline.providers import MediaResult

        return MediaResult({"phrase": phrase, "count": 9, "boxes": [[10, 10, 20, 20]] * 9}, 5, 0.0025, "sam-3.1")


class FakeProvider:
    def __init__(self, cfg, concurrency=6, docs=None):
        self.cfg = cfg
        self.by_file = {d.filename: perfect_extraction(d) for d in docs}

    def instructions(self, text):
        return {"role": self.cfg.developer_role, "content": text}

    async def chat(self, messages, *, tools=None, tool_choice=None, response_format=None, effort=None,
                   max_tokens=4096):
        from ledgerline.providers import LLMResult

        names = [t["function"]["name"] for t in tools or []]
        schema = (response_format or {}).get("json_schema", {}).get("name") or (names[0] if len(names) == 1 else None)
        text = _all_text(messages)
        content, calls = None, []
        if schema == "extraction":
            fname = text.split("Document file: ", 1)[1].split("\n", 1)[0].split("<")[0].strip()
            content = json.dumps(self.by_file[fname])
        elif schema == "batch_plan":
            content = json.dumps({"summary": "test plan", "steps": [{"title": "Read", "detail": "all"}], "watchlist": []})
        elif schema == "verification":
            content = json.dumps({"verdict": "confirmed", "overall_confidence": 0.93, "notes": "",
                                  "claims": [{"claim": "amount", "supported": True, "page": 1, "quote": "x",
                                              "bbox": [1, 2, 3, 4], "confidence": 0.9}]})
        elif schema == "reread":
            content = json.dumps({"answer": "n/a", "quote": "", "page": 1, "confidence": 0.5})
        elif "submit_decision" in names:
            did = text.split("doc_id: ", 1)[1].split("\n", 1)[0].strip()
            tool_msgs = [json.loads(m["content"]) for m in messages if m.get("role") == "tool"]
            if not tool_msgs:
                calls = [tc(i, n, {"doc_id": did}) for i, n in enumerate(
                    ["lookup_vendor", "compare_to_po", "check_vat", "detect_duplicate", "check_goods_receipt"])]
            else:
                codes = sorted({i["code"] for t in tool_msgs for i in t.get("issues", [])})
                decision = ("reject" if FULL & set(codes) else "escalate" if {"UNKNOWN_VENDOR", "MISSING_PO"} & set(codes)
                            else "hold" if set(codes) - {"CONTRACT_PRICE_CHANGE"} else "approve")
                if any(f'"doc_type": "{t}"' in text for t in ("receipt", "contract", "delivery_note", "other",
                                                               "receiving_note", "delivery_photo")):
                    decision = "file"
                calls = [tc(9, "submit_decision", {"doc_id": did, "decision": decision, "rationale": "scripted",
                                                    "confidence": 0.9,
                                                    "flags": [{"code": c, "message": c} for c in codes]})]
        elif "request_approval" in names:
            if not any(m.get("role") == "tool" for m in messages):
                rows = json.loads(text.split("Final status of every document in this batch:\n", 1)[1].rsplit("\nToday", 1)[0])
                approved = [r["doc_id"] for r in rows if r["final_status"] == "approve"]
                calls = [tc(1, "draft_payment", {"doc_ids": approved})]
                for j, r in enumerate(x for x in rows if x["final_status"] == "hold"):
                    calls.append(tc(10 + j, "draft_email", {"vendor_id": r["vendor_id"], "doc_ids": [r["doc_id"]],
                                                            "subject": "Korrektur", "body": "Bitte korrigieren.",
                                                            "language": "de", "purpose": "hold"}))
            else:
                calls = [tc(99, "request_approval", {"summary": "scripted summary"})]
        msg = SimpleNamespace(content=content, tool_calls=calls or None)
        usage = {"input_tokens": 1000, "output_tokens": 200, "cached_tokens": 0, "reasoning_tokens": 50}
        return LLMResult(msg, usage, latency_ms=5, cost_usd=0.002, response_id="fake")


def _all_text(messages):
    out = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            out.append(c)
        elif isinstance(c, list):
            out += [p["text"] for p in c if p.get("type") == "text"]
    return "\n".join(out)


@pytest.fixture()
def client(monkeypatch, sample_docs):
    monkeypatch.setenv("MODEL_API_KEY", "test-key")
    from ledgerline import api

    monkeypatch.setattr(api, "MODE", "live")
    monkeypatch.setattr(api, "Provider", lambda cfg, conc: FakeProvider(cfg, conc, sample_docs))
    monkeypatch.setattr(api, "media", lambda: FakeMedia())
    with TestClient(api.app) as c:
        yield c


def wait_for(client, run_id, status, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = client.get(f"/api/runs/{run_id}").json()
        if st["run"]["status"] in (status, "failed"):
            return st
        time.sleep(0.1)
    raise TimeoutError(status)


def test_live_run_to_approval_and_execution(client, truth):
    run_id = client.post("/api/runs", json={"mode": "live", "provider": "meta", "batch_id": "sample"}).json()["run_id"]
    st = wait_for(client, run_id, "awaiting_approval")
    assert st["run"]["status"] == "awaiting_approval", st["run"]
    by_file = {d["filename"]: d for d in st["docs"]}
    assert len(by_file) == 32

    ev = st["evaluation"]
    assert ev["flag_recall"] == 1.0 and ev["flag_precision"] == 1.0, [r for r in ev["rows"] if r["flags"] != r["expected_flags"]]
    assert st["metrics"]["eur_at_risk"] == pytest.approx(8339.21, abs=0.01)
    sam = next(d for d in st["docs"] if d["filename"].startswith("Wareneingang"))
    assert sam["extraction"]["counted"]["count"] == 9

    # payments go to master IBANs only, credit note nets against Kaffeeimport Hansa
    pay = {p["vendor_id"]: p for p in st["payment_batch"]["items"]}
    assert pay["V001"]["amount"] == pytest.approx(2182.80 - 72.76, abs=0.01)
    assert all(p["iban"].startswith(("DE", "NL", "IE")) for p in pay.values())
    assert not any("LT" in p["iban"][:2] for p in pay.values())

    # human gate: nothing executes while items are pending
    assert client.post(f"/api/runs/{run_id}/execute").status_code == 409
    for item in st["approval_items"]:
        decision = "rejected" if item["kind"] == "escalation" else "approved"
        r = client.post(f"/api/runs/{run_id}/approvals", json={"item": item["item"], "decision": decision})
        assert r.status_code == 200, r.text
    result = client.post(f"/api/runs/{run_id}/execute").json()
    assert result["sepa_file"] == "pain001.xml"
    xml = client.get(f"/api/runs/{run_id}/exports/pain001.xml").text
    assert "<CtrlSum>" in xml and "pain.001.001.09" in xml
    assert client.get(f"/api/runs/{run_id}").json()["run"]["status"] == "completed"


def test_record_and_replay(client, tmp_path, monkeypatch):
    from ledgerline import replay

    monkeypatch.setattr(replay, "REPLAYS", tmp_path)
    run_id = client.post("/api/runs", json={"mode": "live", "provider": "meta"}).json()["run_id"]
    wait_for(client, run_id, "awaiting_approval")
    meta = client.post(f"/api/runs/{run_id}/record", json={"name": "test-run"}).json()
    assert meta["stats"]["documents"] == 32

    rid = client.post("/api/runs", json={"mode": "replay", "replay_id": "test-run", "speed": 1000}).json()["run_id"]
    st = wait_for(client, rid, "awaiting_approval")
    assert st["run"]["replay"]["id"] == "test-run"
    assert st["metrics"]["eur_at_risk"] == pytest.approx(8339.21, abs=0.01)
    assert len(st["approval_items"]) > 0
