"""With a perfect read of each document, the deterministic tools must surface exactly the planted anomalies."""

import pytest

from ledgerline.tools import check_vat, combine_at_risk, compare_to_po, detect_duplicate, doc_gross, lookup_vendor

TOOLS = (lookup_vendor, compare_to_po, check_vat, detect_duplicate)


def run_all(books, key):
    issues = []
    for t in TOOLS:
        issues += t(books, key)["issues"]
    return issues


@pytest.mark.parametrize("key", [f"D{i:02d}" for i in range(1, 31)])
def test_planted_flags(books, truth, key):
    issues = run_all(books, key)
    assert {i["code"] for i in issues} == set(truth[key]["flags"]), [i["message"] for i in issues]


@pytest.mark.parametrize("key", [k for k in (f"D{i:02d}" for i in range(1, 31))])
def test_at_risk_matches_ground_truth(books, truth, key):
    t = truth[key]
    if "at_risk" not in t:
        return
    issues = run_all(books, key)
    assert combine_at_risk(issues, doc_gross(books.extractions[key])) == pytest.approx(t["at_risk"], abs=0.01)


def test_fraud_email_never_trusted(books):
    out = lookup_vendor(books, "D15")
    assert out["iban_check"] == "MISMATCH"
    assert out["sender_check"] == "LOOKALIKE"
    assert out["vendor"]["iban"].startswith("DE")


def test_duplicate_points_at_original(books):
    dup = detect_duplicate(books, "D06")["issues"][0]
    assert dup["details"]["original"] == "PW-2026-3381"
    assert "this batch" in dup["details"]["source"]
    paid = detect_duplicate(books, "D10")["issues"][0]
    assert "PAID" in paid["message"]
    # the original itself is not a duplicate of the later copy
    assert detect_duplicate(books, "D05")["issues"] == []


def test_po_consumption_skips_duplicates(books):
    out = compare_to_po(books, "D18")
    row = out["lines"][0]
    assert row["already_invoiced"] == 10000  # D05 counted once, D06 (copy) ignored
    assert out["issues"][0]["details"]["excess"] == 2000
