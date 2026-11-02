"""Regression tests for edge cases found in code review (no paid model calls)."""

import asyncio
from types import SimpleNamespace

import pytest

from ledgerline.agents import Run
from ledgerline.execution import build_execution


def review_run(books):
    return Run("audit-test", None, None, SimpleNamespace(cfg=SimpleNamespace(media=False)),
               books, list(books.docs.values()))


def test_duplicate_draft_ids_do_not_double_payment(books):
    run = review_run(books)
    did = next(k for k, ex in books.extractions.items() if ex["doc_type"] == "invoice")
    run.final[did] = {"final_status": "approve"}
    once = run._payment_items([did], "2026-11-03")
    repeated = run._payment_items([did, did], "2026-11-03")
    assert once["items"]
    assert repeated == once


@pytest.mark.parametrize("claims", [[], [{"claim": "IBAN matches", "supported": False}]])
def test_confident_verifier_cannot_approve_without_supported_claims(books, monkeypatch, claims):
    run = review_run(books)
    did = next(k for k, ex in books.extractions.items() if ex["doc_type"] == "invoice")
    run.decisions[did] = {"decision": "approve", "confidence": 0.99, "flags": [], "rationale": "Looks fine"}

    async def inconsistent_verdict(*args, **kwargs):
        return {"verdict": "confirmed", "overall_confidence": 0.99, "claims": claims, "notes": ""}

    monkeypatch.setattr(run, "structured", inconsistent_verdict)
    monkeypatch.setattr(run, "doc_content", lambda doc: [])
    monkeypatch.setattr(run, "emit", lambda *args, **kwargs: None)
    asyncio.run(run.verify(books.docs[did]))
    assert run.final[did]["final_status"] == "escalate"


def test_reviewed_exception_never_adds_document_iban_to_export(tmp_path, monkeypatch):
    from ledgerline import execution

    monkeypatch.setattr(execution, "RUNTIME", tmp_path)
    payment = {"vendor_id": "V1", "vendor_name": "Known supplier", "iban": "DE-MASTER",
               "amount": 100.0, "doc_ids": ["invoice"], "reference": "RE 1"}
    st = {"payment_batch": {"items": [payment], "debtor": {}, "execution_date": "2026-11-03"},
          "emails": [], "docs": [{"doc_id": "exception", "filename": "unknown.pdf", "final_status": "escalate",
                                   "decision": {}, "verification": {},
                                   "extraction": {"vendor_name": "Unknown", "iban": "LT-UNTRUSTED", "gross_total": 900}}],
          "approvals": {"pay:V1": {"decision": "approved"}, "doc:exception": {"decision": "approved"}}}
    result = build_execution(st, "regression")
    assert result["total"] == 100
    assert len(result["payments"]) == 1
    xml = (tmp_path / "exports" / "regression" / "pain001.xml").read_text()
    assert "DE-MASTER" in xml
    assert "LT-UNTRUSTED" not in xml
