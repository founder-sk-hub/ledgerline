"""With a perfect read of each document, the deterministic tools must surface exactly the planted anomalies."""

import pytest

from ledgerline.tools import (check_goods_receipt, check_vat, combine_at_risk, compare_to_po, detect_duplicate,
                             doc_gross, lookup_vendor)

TOOLS = (lookup_vendor, compare_to_po, check_vat, detect_duplicate, check_goods_receipt)
KEYS = [f"D{i:02d}" for i in range(1, 33)]


def run_all(books, key):
    issues = []
    for t in TOOLS:
        issues += t(books, key)["issues"]
    return issues


@pytest.mark.parametrize("key", KEYS)
def test_planted_flags(books, truth, key):
    issues = run_all(books, key)
    assert {i["code"] for i in issues} == set(truth[key]["flags"]), [i["message"] for i in issues]


@pytest.mark.parametrize("key", KEYS)
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


def test_three_way_match(books):
    milk = check_goods_receipt(books, "D03")
    assert milk["issues"][0]["details"]["received"] == 280
    photo = check_goods_receipt(books, "D07")["issues"][0]
    assert photo["details"]["received"] == 540 and photo["at_risk_eur"] == 426.0
    # the other Colombia invoice and the next milk week are not touched by that evidence
    assert check_goods_receipt(books, "D08")["issues"] == []
    assert check_goods_receipt(books, "D04")["issues"] == []
    assert check_goods_receipt(books, "D32")["applies_to"][0]["invoice"] == "RGC-1022"


def test_misread_iban_is_not_a_bank_change(books):
    from ledgerline.tools import iban_valid

    master = books.vendor("V002")["iban"]
    misread = master[:2] + "46" + master[4:]  # a blurry photo turned check digits 26 into 46
    assert iban_valid(master) and not iban_valid(misread)
    books.extractions["D20"]["iban"] = misread
    out = lookup_vendor(books, "D20")
    assert out["issues"] == [] and out["iban_check"].startswith("unreadable")
    # a real, valid foreign IBAN (the fraud email) is still flagged
    assert any(i["code"] == "BANK_DETAILS_CHANGED" for i in lookup_vendor(books, "D15")["issues"])
