"""Shared fixtures: perfect extractions built from the sample generator's source data.

These let us test the deterministic tools and the pipeline plumbing offline. They are
never used at runtime and never written into replays.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

# Tests never touch the real database (or its spend ledger).
os.environ["LEDGERLINE_DB"] = str(Path(tempfile.mkdtemp(prefix="ledgerline-test-")) / "test.db")

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "scripts"))

import generate_samples as gs  # noqa: E402

from ledgerline.tools import Books  # noqa: E402

FOOD = re.compile(r"rohkaffee|green coffee|milch|milk|sahne|zucker|zitronen|santos|yirgacheffe|colombia", re.I)
SERVICES = re.compile(r"arbeitszeit|anfahrt|reinigung|kurier", re.I)


def category(doc, line) -> str:
    if FOOD.search(line.desc) and "hafer" not in line.desc.lower():
        return "food"
    if doc.vendor.get("vendor_id") == "V007":
        return "digital_services"
    if SERVICES.search(line.desc):
        return "services"
    return "goods"


def perfect_extraction(doc) -> dict:
    types = {"newsletter": "other"}
    v = doc.vendor
    lines = [{"description": l.desc, "quantity": l.qty, "unit": l.unit, "unit_price": l.price,
              "net_amount": float(l.net), "vat_rate": l.rate, "vat_category": category(doc, l)} for l in doc.lines]
    if doc.lines:
        _, net, vat_parts, vat, gross = doc.totals()
        net, vat, gross = float(net), float(vat), float(gross)
        breakdown = [{"rate": r, "net": float(sum(l.net for l in doc.lines if l.rate == r)), "vat": float(a)}
                     for r, a in vat_parts.items()]
        if doc.net_override is not None:
            breakdown = []
    else:
        net = vat = gross = 0.0
        breakdown = []
    receipt = doc.kind == "receipt"
    if receipt:
        gross = float(sum(l.net for l in doc.lines))
    ex = {
        "doc_type": types.get(doc.kind, doc.kind), "vendor_name": v["name"], "vendor_country": v.get("country", "DE"),
        "vendor_vat_id": v.get("vat_id", ""), "vendor_email": v.get("email", ""),
        "iban": "" if receipt else (doc.iban or v.get("iban", "")), "invoice_number": doc.number,
        "issue_date": doc.date, "service_period": doc.period, "po_number": doc.po or "",
        "related_invoice_number": doc.related, "lines": lines, "prices_include_vat": receipt,
        "net_total": net, "vat_total": vat, "gross_total": gross, "vat_breakdown": breakdown,
        "notes": "", "evidence": [], "confidence": 0.95, "contract_terms": [],
    }
    if doc.kind == "contract":
        ex["invoice_number"] = "OF-2027-0331"
        ex["contract_terms"] = [{"term": "Monthly fee, POS Business plan subscription", "value": "279.00"},
                                {"term": "Term", "value": "2027-01-01 to 2027-12-31"}]
    if doc.email:
        ex["sender_email"] = re.search(r"<(.+)>", doc.email["from"]).group(1)
    if doc.kind == "receiving_note":
        ex.update({"invoice_number": "", "issue_date": "2026-10-23", "service_period": "KW 43", "iban": "",
                   "received_items": [{"description": "Vollmilch", "quantity": 280, "unit": "L"}]})
    if doc.kind == "delivery_photo":
        ex.update({"invoice_number": "", "issue_date": "2026-10-13", "reference": "RGC-1022", "iban": "",
                   "count_target": "jute coffee sack", "unit_size": 60, "counted_items": 9})
    return ex


@pytest.fixture(scope="session")
def sample_docs():
    return gs.build_docs()


@pytest.fixture(scope="session")
def truth():
    data = json.loads((ROOT / "data" / "samples" / "ground_truth.json").read_text())
    return {t["key"]: t for t in data["documents"]}


@pytest.fixture()
def books(sample_docs):
    ref = ROOT / "data" / "samples" / "reference"
    load = lambda n: json.loads((ref / f"{n}.json").read_text())  # noqa: E731
    b = Books(buyer=load("buyer"), vendors=load("vendors"), purchase_orders=load("purchase_orders"),
              contracts=load("contracts"), history=load("invoice_history"))
    for i, d in enumerate(sample_docs):
        meta = {"from": d.email["from"]} if d.email else {}
        b.docs[d.key] = {"doc_id": d.key, "idx": i, "filename": d.filename, "meta": meta}
        b.extractions[d.key] = perfect_extraction(d)
        if d.kind == "delivery_photo":  # what intake adds after SAM 3.1 counts the sacks
            b.extractions[d.key]["counted"] = {"object": "jute coffee sack", "count": 9, "method": "sam-3.1", "boxes": []}
    return b
