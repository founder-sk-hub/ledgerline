"""Deterministic back-office tools the agents call.

Design rule: the model decides WHICH checks matter and what to do about them; code does
the arithmetic and the lookups. Every issue a tool raises carries the computed
EUR-at-risk so the final numbers never depend on model arithmetic.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from difflib import SequenceMatcher
from typing import Any

from .config import POLICY

EU = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU",
      "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"}
PAYABLE = {"invoice", "credit_note", "reminder"}
FULL_AMOUNT_CODES = {"DUPLICATE", "BANK_DETAILS_CHANGED", "SENDER_DOMAIN_MISMATCH", "UNKNOWN_VENDOR", "MISSING_PO"}
INFO_CODES = {"CONTRACT_PRICE_CHANGE"}
LEGAL_SUFFIX = re.compile(r"\b(gmbh|eg|ug|b\.?v\.?|ltd|limited|ag|kg|ohg|e\.?k\.?|inc|co|haftungsbeschränkt)\b\.?", re.I)
MONTHS = {
    "januar": 1, "january": 1, "jan": 1, "februar": 2, "february": 2, "feb": 2, "märz": 3, "maerz": 3, "march": 3,
    "april": 4, "mai": 5, "may": 5, "juni": 6, "june": 6, "juli": 7, "july": 7, "august": 8, "aug": 8,
    "september": 9, "sept": 9, "sep": 9, "oktober": 10, "october": 10, "okt": 10, "oct": 10, "november": 11,
    "nov": 11, "dezember": 12, "december": 12, "dez": 12, "dec": 12,
}


# ---------------------------------------------------------------- helpers
def r2(x: float) -> float:
    return float(f"{x + (1e-9 if x >= 0 else -1e-9):.2f}")


def num(x: Any) -> float:
    if x is None or x == "":
        return 0.0
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).replace("€", "").replace("EUR", "").replace(" ", "").strip()
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def norm_id(s: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def norm_name(s: str | None) -> str:
    s = unicodedata.normalize("NFKC", (s or "").lower())
    s = LEGAL_SUFFIX.sub(" ", s)
    return re.sub(r"[^a-z0-9äöüß]+", " ", s).strip()


def tokens(s: str | None) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9äöüß]+", (s or "").lower()) if len(t) > 1}


def sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def parse_date(s: str | None) -> date | None:
    if not s:
        return None
    s = s.strip()
    for pat, order in ((r"(\d{4})-(\d{1,2})-(\d{1,2})", "ymd"), (r"(\d{1,2})\.(\d{1,2})\.(\d{4})", "dmy")):
        m = re.search(pat, s)
        if m:
            a, b, c = map(int, m.groups())
            try:
                return date(a, b, c) if order == "ymd" else date(c, b, a)
            except ValueError:
                return None
    return None


def norm_period(s: str | None) -> str:
    s = (s or "").lower().strip()
    if not s:
        return ""
    for name, n in sorted(MONTHS.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{name}\b", s):
            y = re.search(r"(20\d\d)", s)
            return f"{y.group(1) if y else ''}-{n:02d}"
    m = re.search(r"(kw|week|cw)\s*(\d{1,2})", s)
    if m:
        return f"w{int(m.group(2))}"
    return re.sub(r"[^0-9a-z]", "", s)


def domain_of(email: str | None) -> str:
    m = re.search(r"@([A-Za-z0-9.-]+)", email or "")
    return m.group(1).lower().rstrip(".>") if m else ""


def issue(code: str, message: str, at_risk: float = 0.0, severity: str = "warning", **details) -> dict:
    if code in INFO_CODES:
        severity = "info"
    return {"code": code, "severity": severity, "message": message, "at_risk_eur": r2(max(at_risk, 0.0)),
            "details": details}


def doc_gross(ex: dict) -> float:
    g = num(ex.get("gross_total"))
    if not g:
        g = num(ex.get("net_total")) + num(ex.get("vat_total"))
    return abs(g)


def combine_at_risk(issues: list[dict], gross: float) -> float:
    """Doc-level exposure: a full-amount issue puts the whole invoice at risk; partial issues add up."""
    if any(i["code"] in FULL_AMOUNT_CODES and i.get("at_risk_eur", 0) > 0 for i in issues):
        return r2(gross)
    return r2(min(sum(i.get("at_risk_eur", 0) for i in issues if i["code"] not in INFO_CODES), gross or 1e12))


# ---------------------------------------------------------------- context
@dataclass
class Books:
    """The company's systems of record plus what the agent has read in this batch."""

    buyer: dict
    vendors: list[dict]
    purchase_orders: list[dict]
    contracts: list[dict]
    history: list[dict]
    docs: dict[str, dict] = field(default_factory=dict)  # doc_id -> registry row
    extractions: dict[str, dict] = field(default_factory=dict)  # doc_id -> extraction

    def vendor(self, vendor_id: str | None) -> dict | None:
        return next((v for v in self.vendors if v["vendor_id"] == vendor_id), None)


# ---------------------------------------------------------------- lookup_vendor
def match_vendor(books: Books, ex: dict, doc: dict | None = None) -> tuple[dict | None, str]:
    vat = norm_id(ex.get("vendor_vat_id"))
    if vat:
        for v in books.vendors:
            if norm_id(v["vat_id"]) == vat:
                return v, "vat_id"
    name = norm_name(ex.get("vendor_name"))
    best, score = None, 0.0
    for v in books.vendors:
        s = sim(name, norm_name(v["name"]))
        if s > score:
            best, score = v, s
    if best and score >= 0.82:
        return best, f"name ({score:.2f})"
    sender = domain_of((doc or {}).get("meta", {}).get("from")) or domain_of(ex.get("vendor_email"))
    for v in books.vendors:
        if sender and sender == v["domain"]:
            return v, "sender domain"
    return None, ""


def lookup_vendor(books: Books, doc_id: str) -> dict:
    ex, doc = books.extractions[doc_id], books.docs.get(doc_id, {})
    v, how = match_vendor(books, ex, doc)
    dtype = ex.get("doc_type", "invoice")
    gross = doc_gross(ex)
    issues: list[dict] = []
    out: dict[str, Any] = {"doc_id": doc_id, "matched": bool(v), "match_method": how}

    sender = domain_of(doc.get("meta", {}).get("from"))
    out["sender_domain"] = sender or None
    if not v:
        if dtype in PAYABLE or (dtype == "receipt" and gross > POLICY["receipt_no_vendor_limit_eur"]):
            issues.append(issue("UNKNOWN_VENDOR", f"'{ex.get('vendor_name')}' is not in the vendor master; "
                                f"{gross:,.2f} EUR would go to an unverified payee.", gross))
        else:
            out["note"] = (f"No vendor master record needed: {dtype} under "
                           f"{POLICY['receipt_no_vendor_limit_eur']:.0f} EUR.")
        out["issues"] = issues
        return out

    out["vendor"] = {k: v[k] for k in ("vendor_id", "name", "country", "vat_id", "email", "domain", "iban",
                                        "payment_terms_days", "contact", "language")}
    out["contracts"] = [c["contract_id"] + ": " + c["title"] for c in books.contracts if c["vendor_id"] == v["vendor_id"]]
    out["open_pos"] = [p["po_number"] for p in books.purchase_orders if p["vendor_id"] == v["vendor_id"]]
    out["recent_paid_invoices"] = [
        {k: h[k] for k in ("invoice_number", "issue_date", "gross", "paid_on")}
        for h in sorted((h for h in books.history if h["vendor_id"] == v["vendor_id"]),
                        key=lambda h: h["issue_date"], reverse=True)[:3]
    ]

    doc_iban = norm_id(ex.get("iban"))
    if not doc_iban:
        out["iban_check"] = "not on document (master IBAN will be used)"
    elif doc_iban == norm_id(v["iban"]):
        out["iban_check"] = "matches vendor master"
    else:
        out["iban_check"] = "MISMATCH"
        if dtype in PAYABLE:
            issues.append(issue("BANK_DETAILS_CHANGED",
                                f"Document asks for payment to {ex.get('iban')} but the vendor master has "
                                f"{v['iban']}. Bank details must be confirmed via a known channel before any payment.",
                                gross, document_iban=ex.get("iban"), master_iban=v["iban"]))

    if sender:
        own = domain_of(books.buyer.get("email"))
        if sender == v["domain"] or sender.endswith("." + v["domain"]):
            out["sender_check"] = "matches vendor domain"
        elif sender == own:
            out["sender_check"] = "internal forward from our own domain"
        elif sim(sender.split(".")[0], v["domain"].split(".")[0]) >= 0.8:
            out["sender_check"] = "LOOKALIKE"
            if dtype in PAYABLE:
                issues.append(issue("SENDER_DOMAIN_MISMATCH",
                                    f"Sent from '{sender}', which imitates the vendor's real domain '{v['domain']}'.",
                                    gross, sender_domain=sender, vendor_domain=v["domain"]))
        else:
            out["sender_check"] = f"different domain ({sender})"
    out["issues"] = issues
    return out


# ---------------------------------------------------------------- compare_to_po
def _best_line(desc: str, candidates: list[dict], desc_key: str) -> tuple[dict | None, float]:
    toks = tokens(desc)
    best, best_score = None, 0.0
    for c in candidates:
        kw = {k.lower() for k in c.get("keywords", [])}
        hits = sum(1 for k in kw if any(k in t or t in k for t in toks if len(t) > 2))
        jacc = len(toks & tokens(c[desc_key])) / max(len(toks | tokens(c[desc_key])), 1)
        score = hits + jacc
        if score > best_score:
            best, best_score = c, score
    return (best, best_score) if best_score >= 1.0 else (None, best_score)


def _dup_key(books: Books, doc_id: str) -> str:
    ex = books.extractions[doc_id]
    v, _ = match_vendor(books, ex, books.docs.get(doc_id))
    return f"{v['vendor_id'] if v else norm_name(ex.get('vendor_name'))}:{norm_id(ex.get('invoice_number'))}"


def _order(books: Books, doc_id: str) -> tuple:
    ex = books.extractions[doc_id]
    return (parse_date(ex.get("issue_date")) or date.max, books.docs.get(doc_id, {}).get("idx", 0))


def _consumed(books: Books, po_number: str, po_line: dict, before: str) -> float:
    """Quantity of a PO line already invoiced: paid history + earlier docs in this batch (duplicates counted once)."""
    total = 0.0
    for h in books.history:
        if norm_id(h.get("po_number")) == norm_id(po_number):
            for l in h.get("lines", []):
                if _best_line(l["description"], [po_line], "description")[0]:
                    total += num(l["quantity"])
    seen: set[str] = set()
    for did in sorted(books.extractions, key=lambda d: _order(books, d)):
        if did == before or _order(books, did) >= _order(books, before):
            continue
        ex = books.extractions[did]
        if ex.get("doc_type") != "invoice" or norm_id(ex.get("po_number")) != norm_id(po_number):
            continue
        key = _dup_key(books, did)
        if key in seen:
            continue
        seen.add(key)
        for l in ex.get("lines", []):
            if _best_line(l.get("description", ""), [po_line], "description")[0]:
                total += num(l.get("quantity"))
    return total


def compare_to_po(books: Books, doc_id: str, po_number: str | None = None) -> dict:
    ex = books.extractions[doc_id]
    v, _ = match_vendor(books, ex, books.docs.get(doc_id))
    dtype = ex.get("doc_type", "invoice")
    gross = doc_gross(ex)
    po_no = po_number or ex.get("po_number") or ""
    po = next((p for p in books.purchase_orders if norm_id(p["po_number"]) == norm_id(po_no)), None) if po_no else None
    contracts = [c for c in books.contracts if v and c["vendor_id"] == v["vendor_id"]]
    terms = [{**t, "contract_id": c["contract_id"]} for c in contracts for t in c["terms"]]
    tol = POLICY["price_tolerance_pct"]
    issues: list[dict] = []
    lines_out: list[dict] = []
    out: dict[str, Any] = {"doc_id": doc_id, "po_number": po["po_number"] if po else (po_no or None),
                           "contracts": [c["contract_id"] for c in contracts]}

    if po_no and not po:
        out["po_status"] = f"PO '{po_no}' not found in the purchasing system"
    if po and v and po["vendor_id"] != v["vendor_id"]:
        issues.append(issue("OTHER", f"PO {po['po_number']} belongs to another vendor ({po['vendor_id']}).", 0))

    if dtype == "contract":
        # Compare any prices in the new contract against the existing agreement.
        for t in ex.get("contract_terms", []) + [{"term": l.get("description"), "value": l.get("unit_price")}
                                                  for l in ex.get("lines", [])]:
            match, _ = _best_line(str(t.get("term", "")), terms, "item")
            new = num(t.get("value"))
            if match and new and abs(new - match["price"]) > 0.005:
                pct = (new - match["price"]) / match["price"] * 100
                issues.append(issue("CONTRACT_PRICE_CHANGE",
                                    f"{match['item']}: {match['price']:.2f} -> {new:.2f} EUR per {match['unit']} "
                                    f"({pct:+.1f}%), vs contract {match['contract_id']}.", 0,
                                    old_price=match["price"], new_price=new, change_pct=round(pct, 1),
                                    annual_impact_eur=r2((new - match["price"]) * (12 if match["unit"] == "month" else 1))))
                break
        out["issues"] = issues
        return out

    if dtype in ("delivery_note", "receipt", "other"):
        out["note"] = f"{dtype}: no price check needed"
        if dtype == "delivery_note" and po:
            out["goods_receipt"] = [{"description": l.get("description"), "quantity": num(l.get("quantity"))}
                                    for l in ex.get("lines", [])]
        out["issues"] = issues
        return out

    for l in ex.get("lines", []):
        qty, price = num(l.get("quantity")), num(l.get("unit_price"))
        rate = num(l.get("vat_rate"))
        row: dict[str, Any] = {"description": l.get("description"), "quantity": qty, "unit_price": price}
        if dtype == "credit_note" or qty < 0 or price < 0:
            row["check"] = "credit line, not price-checked"
            lines_out.append(row)
            continue
        po_line = _best_line(l.get("description", ""), po["lines"], "description")[0] if po else None
        term = None if po_line else _best_line(l.get("description", ""), terms, "item")[0]
        agreed_src = po_line or term
        if not agreed_src:
            row["check"] = "no matching PO line or contract term"
            lines_out.append(row)
            continue
        agreed = po_line["unit_price"] if po_line else term["price"]
        row["agreed_price"] = agreed
        row["source"] = f"{po['po_number']} line {po_line['line']}" if po_line else f"contract {term['contract_id']}"
        delta = (price - agreed) / agreed * 100 if agreed else 0.0
        row["price_delta_pct"] = round(delta, 2)
        if delta > tol:
            risk = (price - agreed) * qty * (1 + rate / 100)
            issues.append(issue("PRICE_DRIFT", f"'{l.get('description')}' billed at {price:.2f} vs agreed {agreed:.2f} "
                                f"({row['source']}), {delta:+.1f}% on {qty:g} units.", risk,
                                agreed_price=agreed, invoiced_price=price, quantity=qty, delta_pct=round(delta, 2)))
        if po_line:
            consumed = _consumed(books, po["po_number"], po_line, doc_id)
            remaining = po_line["quantity"] - consumed
            row.update({"po_quantity": po_line["quantity"], "already_invoiced": consumed, "remaining": remaining})
            if qty > remaining + 1e-6:
                excess = qty - max(remaining, 0)
                issues.append(issue("QTY_EXCEEDS_PO", f"PO {po['po_number']} line {po_line['line']} ordered "
                                    f"{po_line['quantity']:g}, {consumed:g} already invoiced, this invoice bills {qty:g} "
                                    f"({excess:g} over).", excess * min(price, agreed) * (1 + rate / 100),
                                    ordered=po_line["quantity"], already_invoiced=consumed, billed=qty, excess=excess))
        lines_out.append(row)

    out["lines"] = lines_out
    if not po and not contracts and dtype in ("invoice", "reminder"):
        threshold = POLICY["po_required_above_eur"]
        if gross > threshold:
            issues.append(issue("MISSING_PO", f"No purchase order or contract covers this {gross:,.2f} EUR invoice "
                                f"(policy: PO required above {threshold:.0f} EUR).", gross))
        else:
            out["policy"] = f"No PO required below {threshold:.0f} EUR."
    out["issues"] = issues
    return out


# ---------------------------------------------------------------- check_vat
def expected_vat(vendor_country: str, buyer_country: str, category: str) -> tuple[float | None, str]:
    vc = (vendor_country or "").upper()
    if vc == buyer_country == "DE":
        return (7.0, "DE reduced rate (food)") if category == "food" else (19.0, "DE standard rate")
    if vc in EU and vc != buyer_country:
        return 0.0, "intra-EU B2B: 0% on invoice, reverse charge / intra-Community acquisition by the buyer"
    return None, "third-country supplier: no automatic VAT rule"


def check_vat(books: Books, doc_id: str) -> dict:
    ex = books.extractions[doc_id]
    v, _ = match_vendor(books, ex, books.docs.get(doc_id))
    dtype = ex.get("doc_type", "invoice")
    country = (v or {}).get("country") or (ex.get("vendor_country") or "").upper()
    issues: list[dict] = []
    out: dict[str, Any] = {"doc_id": doc_id, "vendor_country": country or None, "buyer_country": books.buyer["country"]}
    if dtype in ("contract", "delivery_note", "other"):
        out["note"] = f"{dtype}: no VAT check"
        out["issues"] = []
        return out

    lines = ex.get("lines", [])
    incl = bool(ex.get("prices_include_vat")) or dtype == "receipt"
    rate_checks = []
    if dtype in PAYABLE:  # receipts are already paid; only their arithmetic is checked
        for l in lines:
            rate, cat = num(l.get("vat_rate")), l.get("vat_category") or "goods"
            exp, rule = expected_vat(country, books.buyer["country"], cat)
            row = {"description": l.get("description"), "category": cat, "charged_rate": rate, "expected_rate": exp,
                   "rule": rule}
            rate_checks.append(row)
            if exp is not None and abs(rate - exp) > 0.01:
                base = num(l.get("net_amount")) or num(l.get("quantity")) * num(l.get("unit_price"))
                over = base * (rate - exp) / 100
                issues.append(issue("VAT_RATE", f"'{l.get('description')}' charged {rate:g}% VAT; expected {exp:g}% "
                                    f"({rule}).", over, charged_rate=rate, expected_rate=exp, base=r2(base)))
    out["rate_checks"] = rate_checks

    # arithmetic
    arith: dict[str, Any] = {}
    line_sum = 0.0
    for l in lines:
        q, p, n = num(l.get("quantity")), num(l.get("unit_price")), num(l.get("net_amount"))
        line_sum += n if n else q * p
        if q and p and n and abs(q * p - n) > max(0.02, abs(n) * 0.001):
            issues.append(issue("ARITHMETIC", f"Line '{l.get('description')}': {q:g} x {p:.3f} = {q * p:,.2f} "
                                f"but the line says {n:,.2f}.", max(n - q * p, 0) * (1 + num(l.get('vat_rate')) / 100)))
    net, vat, gross = num(ex.get("net_total")), num(ex.get("vat_total")), num(ex.get("gross_total"))
    arith.update({"sum_of_lines": r2(line_sum), "stated_net": net, "stated_vat": vat, "stated_gross": gross})
    if incl:
        if gross and abs(line_sum - gross) > 0.02:
            issues.append(issue("ARITHMETIC", f"Line prices (VAT incl.) add up to {line_sum:,.2f} but the total says "
                                f"{gross:,.2f}.", max(gross - line_sum, 0)))
    else:
        if net and abs(line_sum - net) > 0.02:
            eff_rate = vat / net if net else 0
            issues.append(issue("ARITHMETIC", f"Lines add up to {line_sum:,.2f} but the stated net total is "
                                f"{net:,.2f} (difference {net - line_sum:+,.2f}).",
                                max(net - line_sum, 0) * (1 + eff_rate), sum_of_lines=r2(line_sum), stated_net=net))
        breakdown = ex.get("vat_breakdown") or []
        if breakdown:
            exp_vat = sum(num(b.get("net")) * num(b.get("rate")) / 100 for b in breakdown)
        else:
            exp_vat = sum((num(l.get("net_amount")) or num(l.get("quantity")) * num(l.get("unit_price")))
                          * num(l.get("vat_rate")) / 100 for l in lines)
            if net and line_sum and abs(net - line_sum) > 0.02:  # VAT is computed on the stated net
                exp_vat *= net / line_sum
        arith["expected_vat_from_rates"] = r2(exp_vat)
        if net and abs(exp_vat - vat) > 0.02 * max(len(breakdown), 1) + 0.01:
            issues.append(issue("VAT_ARITHMETIC", f"VAT should be {exp_vat:,.2f} at the stated rates but the invoice "
                                f"says {vat:,.2f}.", max(vat - exp_vat, 0)))
        if net and gross and abs(net + vat - gross) > 0.02:
            issues.append(issue("ARITHMETIC", f"Net {net:,.2f} + VAT {vat:,.2f} = {net + vat:,.2f}, but the total "
                                f"due says {gross:,.2f}.", max(gross - net - vat, 0)))
    out["arithmetic"] = arith
    out["issues"] = issues
    return out


# ---------------------------------------------------------------- detect_duplicate
def detect_duplicate(books: Books, doc_id: str) -> dict:
    ex = books.extractions[doc_id]
    dtype = ex.get("doc_type", "invoice")
    out: dict[str, Any] = {"doc_id": doc_id, "invoice_number": ex.get("invoice_number"), "matches": []}
    if dtype not in PAYABLE or dtype == "credit_note":
        out["note"] = f"{dtype}: not checked for duplicates"
        out["issues"] = []
        return out
    v, _ = match_vendor(books, ex, books.docs.get(doc_id))
    vid = v["vendor_id"] if v else None
    me_num, me_gross = norm_id(ex.get("invoice_number")), doc_gross(ex)
    me_period, me_date = norm_period(ex.get("service_period")), parse_date(ex.get("issue_date"))
    window = timedelta(days=POLICY["duplicate_window_days"])

    candidates = [{"source": "paid history", "vendor_id": h["vendor_id"], "invoice_number": h["invoice_number"],
                   "gross": h["gross"], "issue_date": h["issue_date"], "service_period": h.get("service_period"),
                   "paid_on": h.get("paid_on")} for h in books.history]
    my_idx = books.docs.get(doc_id, {}).get("idx", 0)
    for did, other in books.extractions.items():
        if did == doc_id or books.docs.get(did, {}).get("idx", 0) > my_idx:
            continue  # only documents that arrived earlier can be the original
        if other.get("doc_type") not in ("invoice", "reminder"):
            continue
        ov, _ = match_vendor(books, other, books.docs.get(did))
        candidates.append({"source": f"this batch ({books.docs.get(did, {}).get('filename', did)})", "doc_id": did,
                           "vendor_id": ov["vendor_id"] if ov else None, "invoice_number": other.get("invoice_number"),
                           "gross": doc_gross(other), "issue_date": other.get("issue_date"),
                           "service_period": other.get("service_period")})

    best = None
    for c in candidates:
        if not vid or c["vendor_id"] != vid:
            continue
        cn = norm_id(c["invoice_number"])
        score, why = 0.0, ""
        if cn and cn == me_num:
            score, why = 1.0, "same vendor and invoice number"
        elif cn and me_num and (cn.startswith(me_num) or me_num.startswith(cn)) and abs(len(cn) - len(me_num)) <= 3:
            score, why = 0.9, f"invoice number {ex.get('invoice_number')} is a re-issue of {c['invoice_number']}"
        elif abs(num(c["gross"]) - me_gross) < 0.01:
            cp, cd = norm_period(c.get("service_period")), parse_date(c.get("issue_date"))
            if me_period and cp:
                if cp == me_period:
                    score, why = 0.8, "same vendor, amount and service period"
            elif me_date and cd and abs((me_date - cd).days) <= 3:
                score, why = 0.75, "same vendor and amount, issued within 3 days"
        if score and me_date and parse_date(c.get("issue_date")) and score < 1.0:
            if abs(me_date - parse_date(c.get("issue_date"))) > window:
                score = 0.0
        if score:
            m = {**c, "similarity": score, "reason": why}
            out["matches"].append(m)
            if not best or score > best["similarity"]:
                best = m
    issues = []
    if best and best["similarity"] >= 0.75:
        status = f"already PAID on {best['paid_on']}" if best.get("paid_on") else "already in this batch"
        issues.append(issue("DUPLICATE", f"Duplicate of {best['invoice_number']} ({best['source']}), {status}: "
                            f"{best['reason']}.", me_gross, original=best["invoice_number"], source=best["source"],
                            similarity=best["similarity"]))
    out["issues"] = issues
    return out


# ---------------------------------------------------------------- tool schemas (OpenAI function format)
def fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": required}}}


DOC = {"doc_id": {"type": "string", "description": "The document id being reviewed."}}
FLAG_CODES = ["DUPLICATE", "PRICE_DRIFT", "QTY_EXCEEDS_PO", "MISSING_PO", "VAT_RATE", "VAT_ARITHMETIC", "ARITHMETIC",
              "BANK_DETAILS_CHANGED", "SENDER_DOMAIN_MISMATCH", "UNKNOWN_VENDOR", "CONTRACT_PRICE_CHANGE", "OTHER"]
DECISIONS = ["approve", "hold", "reject", "escalate", "file"]

INVESTIGATOR_TOOLS = [
    fn("lookup_vendor", "Match the document's vendor against the vendor master; checks bank details (IBAN) and the "
       "sender's email domain. Returns the vendor profile, contracts, open POs and recent paid invoices.", DOC, ["doc_id"]),
    fn("compare_to_po", "Compare line prices and quantities with the purchase order or the vendor's contract, and "
       "apply the PO policy. For contracts, compares new terms against the existing agreement.",
       {**DOC, "po_number": {"type": "string", "description": "Optional PO number if the extraction missed it."}},
       ["doc_id"]),
    fn("check_vat", "Check VAT rates against German / intra-EU rules and verify the invoice arithmetic "
       "(line totals, net, VAT, gross).", DOC, ["doc_id"]),
    fn("detect_duplicate", "Look for the same invoice in the paid history and among earlier documents in this batch.",
       DOC, ["doc_id"]),
    fn("reread_document", "Ask a focused question about the original document image/text (e.g. 'What IBAN is printed "
       "in the footer?'). Use when a field is unclear or a tool result conflicts with the extraction.",
       {**DOC, "question": {"type": "string"}, "page": {"type": "integer", "description": "1-based page, optional"}},
       ["doc_id", "question"]),
    fn("submit_decision", "Submit the final decision for this document. Call exactly once, last.", {
        **DOC,
        "decision": {"type": "string", "enum": DECISIONS},
        "flags": {"type": "array", "items": {"type": "object", "properties": {
            "code": {"type": "string", "enum": FLAG_CODES}, "message": {"type": "string"}},
            "required": ["code", "message"]}},
        "rationale": {"type": "string", "description": "2-4 sentences for the bookkeeper, with concrete numbers."},
        "confidence": {"type": "number", "description": "0-1"},
    }, ["doc_id", "decision", "flags", "rationale", "confidence"]),
]

DRAFTER_TOOLS = [
    fn("draft_payment", "Draft the SEPA payment batch from approved documents, executed on the next business day. "
       "Credit notes net against the same vendor. Always pays to the vendor-master IBAN.", {
           "doc_ids": {"type": "array", "items": {"type": "string"}},
       }, ["doc_ids"]),
    fn("draft_email", "Draft (not send) an email to a vendor's known contact from the vendor master.", {
        "vendor_id": {"type": "string"},
        "doc_ids": {"type": "array", "items": {"type": "string"}},
        "subject": {"type": "string"},
        "body": {"type": "string"},
        "language": {"type": "string", "enum": ["de", "en"]},
        "purpose": {"type": "string", "description": "One line: why this email is needed."},
    }, ["vendor_id", "doc_ids", "subject", "body", "language", "purpose"]),
    fn("request_approval", "Stop and hand the drafted batch and emails to a human approver. Call last.", {
        "summary": {"type": "string", "description": "3-5 sentences for the approver."},
    }, ["summary"]),
]
