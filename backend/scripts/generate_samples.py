"""Generate the synthetic sample batch for Ledgerline.

Everything produced here is SYNTHETIC: companies, VAT IDs, IBANs (checksum-valid but
random), invoices and anomalies are invented for the demo. Run from the repo root:

    .venv/bin/python backend/scripts/generate_samples.py

Outputs (committed to the repo so judges don't need to regenerate):
    data/samples/reference/{buyer,vendors,purchase_orders,contracts,invoice_history}.json
    data/samples/batch/*            30 documents (PDF, phone photos, scans, emails)
    data/samples/batch/manifest.json   arrival order of the batch
    data/samples/ground_truth.json  planted anomalies, used ONLY by the eval script
"""

from __future__ import annotations

import json
import math
import random
import shutil
import subprocess
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from email.message import EmailMessage
from email.utils import format_datetime
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
from fpdf import FPDF
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "samples"
REF = OUT / "reference"
BATCH = OUT / "batch"
FONTS = Path("/System/Library/Fonts/Supplemental")
RNG = random.Random(1026)


def D(x) -> Decimal:
    return Decimal(str(x))


def q2(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------- synthetic IBANs
def _iban(country: str, bban: str) -> str:
    def num(s: str) -> str:
        return "".join(str(int(c, 36)) for c in s)

    check = 98 - int(num(bban + country + "00")) % 97
    return f"{country}{check:02d}{bban}"


def de_iban(seed: int) -> str:
    r = random.Random(seed)
    return _iban("DE", f"{r.randint(10000000, 99999999)}{r.randint(10**9, 10**10 - 1)}")


def fmt_iban(iban: str) -> str:
    return " ".join(iban[i : i + 4] for i in range(0, len(iban), 4))


# ---------------------------------------------------------------- reference data
BUYER = {
    "name": "Spree Roastery GmbH",
    "address": ["Köpenicker Straße 40", "10179 Berlin", "Deutschland"],
    "country": "DE",
    "vat_id": "DE318840527",
    "email": "ap@spree-roastery.example",
    "iban": de_iban(1),
    "bic": "SYNTDEB1XXX",
    "note": "SYNTHETIC demo company",
}

VENDORS = [
    {
        "vendor_id": "V001", "name": "Kaffeeimport Hansa GmbH", "country": "DE",
        "address": ["Am Sandtorkai 12", "20457 Hamburg"], "vat_id": "DE811290455",
        "email": "rechnung@kaffeeimport-hansa.de", "domain": "kaffeeimport-hansa.de",
        "phone": "+49 40 555 0192", "iban": de_iban(101), "bic": "SYNTDEHHXXX",
        "payment_terms_days": 30, "language": "de", "contact": "Jana Petersen",
    },
    {
        "vendor_id": "V002", "name": "Molkerei Havelland eG", "country": "DE",
        "address": ["Dorfstraße 7", "14641 Nauen"], "vat_id": "DE813377020",
        "email": "faktura@molkerei-havelland.de", "domain": "molkerei-havelland.de",
        "phone": "+49 3321 555 40", "iban": de_iban(102), "bic": "SYNTDEB2XXX",
        "payment_terms_days": 14, "language": "de", "contact": "Uwe Krüger",
    },
    {
        "vendor_id": "V003", "name": "PackWerk Verpackungen GmbH", "country": "DE",
        "address": ["Industriestraße 88", "04129 Leipzig"], "vat_id": "DE296601184",
        "email": "buchhaltung@packwerk.de", "domain": "packwerk.de",
        "phone": "+49 341 555 7700", "iban": de_iban(103), "bic": "SYNTDEL1XXX",
        "payment_terms_days": 30, "language": "de", "contact": "Sabine Wolf",
    },
    {
        "vendor_id": "V004", "name": "Rotterdam Green Coffee Traders B.V.", "country": "NL",
        "address": ["Maashaven 21", "3072 AH Rotterdam", "Netherlands"], "vat_id": "NL859432178B01",
        "email": "accounts@rgc-traders.nl", "domain": "rgc-traders.nl",
        "phone": "+31 10 555 3311", "iban": _iban("NL", "SYNT" + "0417726391"), "bic": "SYNTNL2AXXX",
        "payment_terms_days": 30, "language": "en", "contact": "Pieter de Vries",
    },
    {
        "vendor_id": "V005", "name": "CleanTeam Berlin GmbH", "country": "DE",
        "address": ["Prenzlauer Allee 190", "10405 Berlin"], "vat_id": "DE327718840",
        "email": "rechnungen@cleanteam-berlin.de", "domain": "cleanteam-berlin.de",
        "phone": "+49 30 555 8812", "iban": de_iban(105), "bic": "SYNTDEB3XXX",
        "payment_terms_days": 14, "language": "de", "contact": "Mehmet Aydın",
    },
    {
        "vendor_id": "V006", "name": "Baristech Service GmbH", "country": "DE",
        "address": ["Friedrich-Engels-Straße 24", "14473 Potsdam"], "vat_id": "DE301845562",
        "email": "service@baristech.de", "domain": "baristech.de",
        "phone": "+49 331 555 2040", "iban": de_iban(106), "bic": "SYNTDEB4XXX",
        "payment_terms_days": 14, "language": "de", "contact": "Lukas Brandt",
    },
    {
        "vendor_id": "V007", "name": "Cloudly Software Ltd", "country": "IE",
        "address": ["5 Hanover Quay", "Dublin 2, D02 X285", "Ireland"], "vat_id": "IE3876291QH",
        "email": "billing@cloudly.io", "domain": "cloudly.io",
        "phone": "+353 1 555 0400", "iban": _iban("IE", "SYNT" + "990514" + "33471209"), "bic": "SYNTIE2DXXX",
        "payment_terms_days": 14, "language": "en", "contact": "Aoife Byrne",
    },
    {
        "vendor_id": "V008", "name": "Kurier Blitz Berlin UG", "country": "DE",
        "address": ["Sonnenallee 221", "12059 Berlin"], "vat_id": "DE342210967",
        "email": "abrechnung@kurierblitz.de", "domain": "kurierblitz.de",
        "phone": "+49 30 555 6060", "iban": de_iban(108), "bic": "SYNTDEB5XXX",
        "payment_terms_days": 14, "language": "de", "contact": "Nadine Schulz",
    },
]
V = {v["vendor_id"]: v for v in VENDORS}

PURCHASE_ORDERS = [
    {
        "po_number": "PO-2026-101", "vendor_id": "V001", "issue_date": "2026-10-05", "status": "open",
        "lines": [
            {"line": 1, "description": "Brazil Santos NY2 17/18 green coffee", "keywords": ["santos", "brazil", "brasilien"],
             "quantity": 600, "unit": "kg", "unit_price": 6.80, "vat_category": "food", "pack": {"name": "sack", "size": 60}},
            {"line": 2, "description": "Ethiopia Yirgacheffe G2 green coffee", "keywords": ["yirgacheffe", "ethiopia", "äthiopien"],
             "quantity": 400, "unit": "kg", "unit_price": 9.40, "vat_category": "food"},
        ],
    },
    {
        "po_number": "PO-2026-102", "vendor_id": "V003", "issue_date": "2026-10-02", "status": "open",
        "lines": [
            {"line": 1, "description": "Paper cup 12oz double wall, printed", "keywords": ["becher", "cup", "12oz"],
             "quantity": 20000, "unit": "pcs", "unit_price": 0.085, "vat_category": "goods"},
            {"line": 2, "description": "Kraft coffee bag 250g with valve", "keywords": ["kraft", "beutel", "bag", "250g"],
             "quantity": 5000, "unit": "pcs", "unit_price": 0.21, "vat_category": "goods"},
        ],
    },
    {
        "po_number": "PO-2026-103", "vendor_id": "V004", "issue_date": "2026-09-28", "status": "open",
        "lines": [
            {"line": 1, "description": "Colombia Supremo 17/18 green coffee", "keywords": ["colombia", "supremo", "kolumbien"],
             "quantity": 1200, "unit": "kg", "unit_price": 7.10, "vat_category": "food", "pack": {"name": "sack", "size": 60}},
        ],
    },
    {
        "po_number": "PO-2026-104", "vendor_id": "V002", "issue_date": "2026-10-09", "status": "open",
        "note": "Standing order, 400 L per week, delivery weeks 42-45",
        "lines": [
            {"line": 1, "description": "Whole milk 3.5% (Vollmilch)", "keywords": ["vollmilch", "milch", "milk"],
             "quantity": 1600, "unit": "L", "unit_price": 1.09, "vat_category": "food", "pack": {"name": "can", "size": 10}},
        ],
    },
    {
        "po_number": "PO-2026-105", "vendor_id": "V006", "issue_date": "2026-10-01", "status": "open",
        "lines": [
            {"line": 1, "description": "Grinder burr set Mythos One (pair)", "keywords": ["mahlscheiben", "burr", "mythos"],
             "quantity": 2, "unit": "set", "unit_price": 189.00, "vat_category": "goods"},
        ],
    },
]

CONTRACTS = [
    {
        "contract_id": "C-005", "vendor_id": "V005", "title": "Unterhaltsreinigung 3 Filialen", "start": "2026-01-01", "end": "2026-12-31",
        "terms": [{"item": "Monthly cleaning flat fee", "keywords": ["reinigung", "unterhaltsreinigung", "pauschale", "monat"],
                   "unit": "month", "price": 1450.00, "vat_category": "services"}],
    },
    {
        "contract_id": "C-006", "vendor_id": "V006", "title": "Wartungsvertrag Espressomaschinen", "start": "2026-03-01", "end": "2027-02-28",
        "terms": [
            {"item": "Technician labour", "keywords": ["arbeitszeit", "arbeitsstunde", "techniker", "labour", "labor", "stunde"],
             "unit": "h", "price": 85.00, "vat_category": "services"},
            {"item": "Call-out fee", "keywords": ["anfahrt", "call-out", "callout", "anfahrtspauschale"],
             "unit": "visit", "price": 45.00, "vat_category": "services"},
        ],
    },
    {
        "contract_id": "C-007", "vendor_id": "V007", "title": "Cloudly POS Business plan", "start": "2026-01-01", "end": "2026-12-31",
        "terms": [{"item": "POS Business plan subscription (3 locations)", "keywords": ["subscription", "pos", "business", "plan"],
                   "unit": "month", "price": 249.00, "vat_category": "digital_services"}],
    },
    {
        "contract_id": "C-008", "vendor_id": "V008", "title": "Rahmenvertrag Kurierfahrten", "start": "2026-02-01", "end": "2027-01-31",
        "terms": [{"item": "Same-day delivery within Berlin", "keywords": ["zustellung", "kurierfahrt", "fahrt", "delivery", "lieferung"],
                   "unit": "delivery", "price": 12.50, "vat_category": "services"}],
    },
]


def _hist(vendor_id, number, issue, paid, net, rate, po=None, period=None, lines=None):
    net = D(net)
    vat = q2(net * D(rate) / 100)
    return {
        "vendor_id": vendor_id, "invoice_number": number, "issue_date": issue, "paid_on": paid,
        "po_number": po, "service_period": period, "net": float(net), "vat": float(vat),
        "gross": float(net + vat), "status": "paid", "lines": lines or [],
    }


INVOICE_HISTORY = [
    _hist("V001", "KH-24-0877", "2026-08-19", "2026-09-15", "4080.00", 7, "PO-2026-077",
          lines=[{"description": "Brazil Santos NY2 green coffee", "quantity": 600, "unit_price": 6.80}]),
    _hist("V002", "MH-77779", "2026-10-02", "2026-10-14", "436.00", 7, "PO-2026-088", "KW 40"),
    _hist("V002", "MH-77790", "2026-10-09", "2026-10-21", "436.00", 7, "PO-2026-088", "KW 41"),
    _hist("V003", "PW-2026-3301", "2026-09-10", "2026-10-08", "1700.00", 19, "PO-2026-071"),
    _hist("V004", "RGC-0988", "2026-09-04", "2026-10-02", "4260.00", 0, "PO-2026-069"),
    _hist("V005", "CT-2026-08", "2026-08-31", "2026-09-10", "1450.00", 19, None, "August 2026"),
    _hist("V005", "CT-2026-09", "2026-09-30", "2026-10-05", "1450.00", 19, None, "September 2026"),
    _hist("V006", "BT-5502", "2026-09-15", "2026-09-26", "215.00", 19, None),
    _hist("V007", "CL-IE-87102", "2026-09-01", "2026-09-03", "249.00", 0, None, "September 2026"),
    _hist("V008", "KB-1160", "2026-09-30", "2026-10-09", "200.00", 19, None, "September 2026"),
]


# ---------------------------------------------------------------- documents
@dataclass
class Line:
    desc: str
    qty: float
    unit: str
    price: float
    rate: int  # VAT percent printed on the invoice

    @property
    def net(self) -> Decimal:
        return q2(D(self.qty) * D(self.price))


@dataclass
class Doc:
    key: str  # D01..D30
    filename: str
    kind: str  # invoice | credit_note | receipt | contract | delivery_note | newsletter | reminder
    fmt: str  # pdf | photo | scan | email
    vendor: dict
    lang: str = "de"
    style: str = "modern"
    number: str = ""
    date: str = ""
    po: str | None = None
    lines: list[Line] = field(default_factory=list)
    net_override: Decimal | None = None  # planted arithmetic error
    iban: str | None = None
    vat_note: str = ""
    extra: list[str] = field(default_factory=list)  # free text lines under the table
    period: str = ""
    related: str = ""
    stamp: str = ""
    handwriting: str = ""
    email: dict | None = None
    truth: dict = field(default_factory=dict)

    def totals(self):
        net_lines = sum((l.net for l in self.lines), Decimal("0"))
        net = self.net_override if self.net_override is not None else net_lines
        by_rate: dict[int, Decimal] = {}
        for l in self.lines:
            by_rate[l.rate] = by_rate.get(l.rate, Decimal("0")) + l.net
        if self.net_override is not None:  # VAT computed on the (wrong) stated net
            vat_parts = {r: q2(net * D(r) / 100) for r in by_rate}
        else:
            vat_parts = {r: q2(n * D(r) / 100) for r, n in by_rate.items()}
        vat = sum(vat_parts.values(), Decimal("0"))
        return net_lines, net, vat_parts, vat, net + vat


def money(x: Decimal, lang: str) -> str:
    s = f"{abs(x):,.2f}"
    if lang == "de":
        s = s.replace(",", "X").replace(".", ",").replace("X", ".")
        return ("-" if x < 0 else "") + s + " €"
    return ("-" if x < 0 else "") + "€" + s


def qty_fmt(q: float, lang: str) -> str:
    s = f"{q:,.0f}" if float(q).is_integer() else f"{q:,.1f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".") if lang == "de" else s


def de_date(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{d}.{m}.{y}"


def en_date(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%d %b %Y")


LABELS = {
    "de": {
        "invoice": "RECHNUNG", "credit_note": "GUTSCHRIFT", "delivery_note": "LIEFERSCHEIN", "number": "Rechnungs-Nr.",
        "cn_number": "Gutschrift-Nr.", "dn_number": "Lieferschein-Nr.", "date": "Datum", "po": "Ihre Bestellung",
        "pos": "Pos.", "desc": "Beschreibung", "qty": "Menge", "unit": "Einheit", "price": "Einzelpreis", "amount": "Gesamt",
        "net": "Nettobetrag", "vat": "zzgl. USt.", "gross": "Rechnungsbetrag", "terms": "Zahlbar innerhalb von {d} Tagen ohne Abzug.",
        "bank": "Bankverbindung", "vat_id": "USt-IdNr.", "period": "Leistungszeitraum", "customer": "Kunde",
        "related": "Bezug: Rechnung",
    },
    "en": {
        "invoice": "INVOICE", "credit_note": "CREDIT NOTE", "delivery_note": "DELIVERY NOTE", "number": "Invoice no.",
        "cn_number": "Credit note no.", "dn_number": "Delivery note no.", "date": "Date", "po": "Your PO",
        "pos": "#", "desc": "Description", "qty": "Qty", "unit": "Unit", "price": "Unit price", "amount": "Amount",
        "net": "Subtotal", "vat": "VAT", "gross": "Total due", "terms": "Payment due within {d} days.",
        "bank": "Bank details", "vat_id": "VAT ID", "period": "Service period", "customer": "Bill to",
        "related": "Re: invoice",
    },
}


# ---------------------------------------------------------------- PDF rendering
class Pdf(FPDF):
    def __init__(self, family: str, fmt=(210, 297)):
        super().__init__(format=fmt)
        self.set_auto_page_break(True, 18)
        faces = {
            "Arial": ("Arial.ttf", "Arial Bold.ttf"),
            "Georgia": ("Georgia.ttf", "Georgia Bold.ttf"),
            "Verdana": ("Verdana.ttf", "Verdana Bold.ttf"),
            "Courier": ("Courier New.ttf", "Courier New Bold.ttf"),
            "Trebuchet": ("Trebuchet MS.ttf", "Trebuchet MS Bold.ttf"),
        }
        reg, bold = faces[family]
        self.fam = "LL" + family  # avoid clashing with fpdf's built-in core font names
        self.add_font(self.fam, "", str(FONTS / reg))
        self.add_font(self.fam, "B", str(FONTS / bold))
        self.set_creation_date(datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc))
        self.add_page()

    def f(self, size, bold=False):
        self.set_font(self.fam, "B" if bold else "", size)

    def multi_cell(self, *args, **kwargs):
        kwargs.setdefault("new_x", "LMARGIN")
        kwargs.setdefault("new_y", "NEXT")
        return super().multi_cell(*args, **kwargs)


STYLES = {
    "modern": {"font": "Arial", "accent": (31, 78, 121)},
    "classic": {"font": "Georgia", "accent": (60, 60, 60)},
    "minimal": {"font": "Verdana", "accent": (120, 120, 120)},
    "bold": {"font": "Trebuchet", "accent": (176, 58, 46)},
}


def render_pdf(doc: Doc, path: Path) -> None:
    if doc.kind == "receipt":
        return render_receipt_pdf(doc, path)
    if doc.kind == "contract":
        return render_contract_pdf(doc, path)
    L = LABELS[doc.lang]
    st = STYLES[doc.style]
    v = doc.vendor
    pdf = Pdf(st["font"])
    r, g, b = st["accent"]

    # letterhead
    if doc.style == "modern":
        pdf.set_fill_color(r, g, b)
        pdf.rect(0, 0, 210, 26, "F")
        pdf.set_text_color(255, 255, 255)
        pdf.set_xy(14, 8)
        pdf.f(17, True)
        pdf.cell(0, 8, v["name"])
        pdf.set_text_color(30, 30, 30)
        pdf.set_y(30)
    elif doc.style == "classic":
        pdf.set_y(12)
        pdf.f(20, True)
        pdf.cell(0, 10, v["name"], align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.f(8.5)
        pdf.cell(0, 5, " · ".join(v["address"]) + f" · {v.get('phone', '')}", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(r, g, b)
        pdf.line(14, 30, 196, 30)
        pdf.set_y(34)
    else:
        pdf.set_y(14)
        pdf.f(15, True)
        pdf.set_text_color(r, g, b)
        pdf.cell(0, 8, v["name"], new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(30, 30, 30)
        pdf.f(8.5)
        pdf.cell(0, 5, ", ".join(v["address"]), new_x="LMARGIN", new_y="NEXT")
        pdf.set_y(32)

    # sender line + recipient
    pdf.f(7.5)
    pdf.set_text_color(110, 110, 110)
    pdf.set_x(14)
    pdf.cell(0, 4, f"{v['name']} · {', '.join(v['address'][:2])}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(30, 30, 30)
    pdf.f(10)
    pdf.set_x(14)
    pdf.multi_cell(90, 5, "\n".join([BUYER["name"], "Buchhaltung / Accounts payable", *BUYER["address"]]))

    # meta block on the right
    title = L[doc.kind] if doc.kind in ("invoice", "credit_note", "delivery_note") else L["invoice"]
    num_label = {"credit_note": L["cn_number"], "delivery_note": L["dn_number"]}.get(doc.kind, L["number"])
    meta = [(num_label, doc.number), (L["date"], de_date(doc.date) if doc.lang == "de" else en_date(doc.date))]
    if doc.po:
        meta.append((L["po"], doc.po))
    if doc.period:
        meta.append((L["period"], doc.period))
    if doc.related:
        meta.append((L["related"], doc.related))
    meta.append((L["customer"] + " " + L["vat_id"], BUYER["vat_id"]))
    y0 = 40 if doc.style != "classic" else 42
    pdf.set_xy(118, y0)
    pdf.f(16, True)
    pdf.cell(78, 8, title, align="R", new_x="LMARGIN", new_y="NEXT")
    for k, val in meta:
        pdf.set_x(118)
        pdf.f(8.5)
        pdf.cell(38, 5, k)
        pdf.f(8.5, True)
        pdf.cell(40, 5, val, align="R", new_x="LMARGIN", new_y="NEXT")

    pdf.set_y(max(pdf.get_y(), 78) + 6)

    if doc.kind == "delivery_note":
        cols = [(12, L["pos"], "L"), (110, L["desc"], "L"), (30, L["qty"], "R"), (30, L["unit"], "L")]
    else:
        cols = [(10, L["pos"], "L"), (78, L["desc"], "L"), (22, L["qty"], "R"), (16, L["unit"], "L"),
                (28, L["price"], "R"), (28, L["amount"], "R")]
    pdf.set_x(14)
    pdf.set_fill_color(235, 238, 242) if doc.style != "bold" else pdf.set_fill_color(250, 232, 228)
    pdf.f(8.5, True)
    for w, h, a in cols:
        pdf.cell(w, 7, h, align=a, fill=True)
    pdf.ln(7)
    pdf.f(9)
    for i, l in enumerate(doc.lines, 1):
        pdf.set_x(14)
        if doc.kind == "delivery_note":
            vals = [str(i), l.desc, qty_fmt(l.qty, doc.lang), l.unit]
        else:
            price = f"{l.price:,.3f}" if l.price < 1 else f"{l.price:,.2f}"
            if doc.lang == "de":
                price = price.replace(",", "X").replace(".", ",").replace("X", ".")
            vals = [str(i), l.desc, qty_fmt(l.qty, doc.lang), l.unit, price, money(l.net, doc.lang).replace(" €", "").replace("€", "")]
        for (w, _, a), val in zip(cols, vals):
            pdf.cell(w, 6.5, val, align=a)
        pdf.ln(6.5)
        pdf.set_draw_color(225, 225, 225)
        pdf.line(14, pdf.get_y(), 196, pdf.get_y())

    if doc.kind != "delivery_note":
        _, net, vat_parts, vat, gross = doc.totals()
        pdf.ln(4)
        rows = [(L["net"], money(net, doc.lang))]
        for rate, amt in sorted(vat_parts.items()):
            rows.append((f"{L['vat']} {rate}%", money(amt, doc.lang)))
        rows.append((L["gross"], money(gross, doc.lang)))
        for i, (k, val) in enumerate(rows):
            last = i == len(rows) - 1
            pdf.set_x(110)
            pdf.f(10 if last else 9, last)
            pdf.cell(52, 6.5, k)
            pdf.cell(34, 6.5, val, align="R", new_x="LMARGIN", new_y="NEXT")
        if doc.vat_note:
            pdf.ln(2)
            pdf.set_x(14)
            pdf.f(8)
            pdf.multi_cell(182, 4.5, doc.vat_note)

    pdf.ln(4)
    pdf.f(9)
    for t in doc.extra:
        pdf.set_x(14)
        pdf.multi_cell(182, 5, t)
    if doc.kind == "invoice":
        pdf.set_x(14)
        pdf.multi_cell(182, 5, L["terms"].format(d=v["payment_terms_days"]))

    # footer with bank details
    iban = doc.iban or v["iban"]
    pdf.set_auto_page_break(False)
    pdf.set_y(-36)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(14, pdf.get_y(), 196, pdf.get_y())
    pdf.ln(2)
    pdf.f(7.5)
    pdf.set_text_color(90, 90, 90)
    col1 = f"{v['name']}\n" + "\n".join(v["address"])
    col2 = f"{L['bank']}\nIBAN {fmt_iban(iban)}\nBIC {v['bic']}"
    col3 = f"{L['vat_id']} {v['vat_id']}\n{v['email']}\n{v.get('phone', '')}"
    y = pdf.get_y()
    for x, txt in ((14, col1), (78, col2), (148, col3)):
        pdf.set_xy(x, y)
        pdf.multi_cell(62, 3.8, txt)
    pdf.output(str(path))


def render_receipt_pdf(doc: Doc, path: Path) -> None:
    v = doc.vendor
    height = 120 + 6 * len(doc.lines)
    pdf = Pdf("Courier", fmt=(80, height))
    pdf.set_margins(5, 5, 5)
    pdf.set_y(6)
    pdf.f(11, True)
    pdf.multi_cell(70, 5, v["name"], align="C")
    pdf.f(7.5)
    pdf.multi_cell(70, 3.6, "\n".join(v["address"]) + (f"\nSt-Nr {v['tax_number']}" if v.get("tax_number") else ""), align="C")
    pdf.ln(2)
    pdf.cell(70, 4, "-" * 40, new_x="LMARGIN", new_y="NEXT")
    pdf.f(8)
    for l in doc.lines:
        tag = "A" if l.rate == 19 else "B"
        pdf.cell(48, 4.2, f"{l.desc[:26]}")
        pdf.cell(22, 4.2, f"{money(l.net, 'de').replace(' €', '')} {tag}", align="R", new_x="LMARGIN", new_y="NEXT")
        if l.qty != 1:
            pdf.f(7)
            pdf.cell(70, 3.6, f"  {qty_fmt(l.qty, 'de')} x {l.price:.2f}".replace(".", ","), new_x="LMARGIN", new_y="NEXT")
            pdf.f(8)
    pdf.cell(70, 4, "-" * 40, new_x="LMARGIN", new_y="NEXT")
    # receipts print gross prices; derive VAT contained
    gross_by_rate: dict[int, Decimal] = {}
    for l in doc.lines:
        gross_by_rate[l.rate] = gross_by_rate.get(l.rate, Decimal("0")) + l.net
    total = sum(gross_by_rate.values(), Decimal("0"))
    pdf.f(10, True)
    pdf.cell(40, 6, "SUMME EUR")
    pdf.cell(30, 6, money(total, "de").replace(" €", ""), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.f(7.5)
    for rate, g in sorted(gross_by_rate.items()):
        net = q2(g / (1 + D(rate) / 100))
        tag = "A" if rate == 19 else "B"
        pdf.cell(70, 3.6, f"{tag} {rate}% MwSt  Netto {money(net, 'de')}  MwSt {money(g - net, 'de')}",
                 new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    pdf.f(8)
    for t in doc.extra:
        pdf.multi_cell(70, 3.8, t, align="C")
    pdf.cell(70, 4, f"{de_date(doc.date)}  Beleg-Nr. {doc.number}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(path))


def render_contract_pdf(doc: Doc, path: Path) -> None:
    v = doc.vendor
    pdf = Pdf("Arial")
    pdf.set_y(16)
    pdf.f(16, True)
    pdf.cell(0, 8, v["name"], new_x="LMARGIN", new_y="NEXT")
    pdf.f(9)
    pdf.cell(0, 5, ", ".join(v["address"]), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)
    pdf.f(14, True)
    pdf.cell(0, 8, "Order Form - Renewal", new_x="LMARGIN", new_y="NEXT")
    pdf.f(10)
    for t in doc.extra:
        if t.startswith("## "):
            pdf.ln(3)
            pdf.f(11, True)
            pdf.multi_cell(0, 6, t[3:])
            pdf.f(10)
        else:
            pdf.multi_cell(0, 5.5, t)
    pdf.output(str(path))


# ---------------------------------------------------------------- photo / scan effects
def _font(name: str, size: int):
    try:
        return ImageFont.truetype(str(name), size)
    except OSError:
        return ImageFont.load_default(size)


def rasterize(pdf_path: Path, scale: float = 1.6) -> Image.Image:
    pdf = pdfium.PdfDocument(str(pdf_path))
    img = pdf[0].render(scale=scale).to_pil().convert("RGB")
    pdf.close()
    return img


def add_overlays(img: Image.Image, doc: Doc) -> Image.Image:
    img = img.convert("RGBA")
    W, H = img.size
    if doc.stamp:
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        fnt = _font(FONTS / "Arial Bold.ttf", int(W * 0.07))
        tw = d.textlength(doc.stamp, font=fnt)
        x, y = int(W * 0.50), int(H * 0.50)
        d.rectangle([x - 18, y - 12, x + tw + 18, y + int(W * 0.085)], outline=(200, 30, 30, 200), width=6)
        d.text((x, y), doc.stamp, font=fnt, fill=(200, 30, 30, 190))
        layer = layer.rotate(-14, center=(x + tw / 2, y), resample=Image.BICUBIC)
        img = Image.alpha_composite(img, layer)
    if doc.handwriting:
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        fnt = _font(FONTS / "Bradley Hand Bold.ttf", int(W * 0.038))
        d.text((int(W * 0.08), int(H * 0.62)), doc.handwriting, font=fnt, fill=(20, 40, 140, 230))
        img = Image.alpha_composite(img, layer.rotate(3, resample=Image.BICUBIC))
    return img.convert("RGB")


def phone_photo(page: Image.Image, seed: int) -> Image.Image:
    """Make a clean render look like a phone photo on a desk."""
    rnd = random.Random(seed)
    nprnd = np.random.default_rng(seed)
    w, h = page.size
    pad = int(max(w, h) * 0.12)
    bg_color = rnd.choice([(118, 92, 66), (92, 98, 104), (150, 128, 100)])
    canvas = Image.new("RGB", (w + 2 * pad, h + 2 * pad), bg_color)
    grain = nprnd.normal(0, 14, (canvas.size[1], canvas.size[0], 1))
    canvas = Image.fromarray(np.clip(np.asarray(canvas, dtype=np.float32) + grain, 0, 255).astype(np.uint8))
    # shadow under the paper
    shadow = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(shadow).rectangle([pad + 10, pad + 14, pad + w + 10, pad + h + 14], fill=120)
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    canvas = Image.composite(Image.new("RGB", canvas.size, (30, 25, 20)), canvas, shadow)
    canvas.paste(page, (pad, pad))
    # perspective: pull the top edge in a bit, like a hand-held shot
    W, H = canvas.size
    dx = W * rnd.uniform(0.025, 0.05)
    dy = H * rnd.uniform(0.0, 0.02)
    src = [(dx, dy), (W - dx * 0.6, 0), (W, H), (0, H - dy)]
    coeffs = _perspective_coeffs([(0, 0), (W, 0), (W, H), (0, H)], src)
    canvas = canvas.transform((W, H), Image.PERSPECTIVE, coeffs, Image.BICUBIC, fillcolor=bg_color)
    canvas = canvas.rotate(rnd.uniform(-3.5, 3.5), resample=Image.BICUBIC, expand=False, fillcolor=bg_color)
    # uneven lighting + sensor noise + slight blur
    arr = np.asarray(canvas, dtype=np.float32)
    yy, xx = np.mgrid[0:H, 0:W]
    cx, cy = W * rnd.uniform(0.3, 0.7), H * rnd.uniform(0.2, 0.5)
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / math.hypot(W, H)
    light = (1.08 - 0.55 * dist)[..., None]
    warm = np.array([1.0, 0.97, 0.9], dtype=np.float32)
    arr = arr * light * warm + nprnd.normal(0, 6, arr.shape)
    canvas = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.7))
    canvas.thumbnail((1500, 1500))
    return canvas


def scanned(page: Image.Image, seed: int) -> Image.Image:
    nprnd = np.random.default_rng(seed)
    g = page.convert("L").rotate(1.3, resample=Image.BICUBIC, expand=True, fillcolor=255)
    arr = np.asarray(g, dtype=np.float32)
    arr = arr * 0.92 + 14 + nprnd.normal(0, 9, arr.shape)
    speckle = nprnd.random(arr.shape) > 0.9993
    arr[speckle] = 40
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.5))
    img = img.convert("RGB")
    img.thumbnail((1500, 1500))
    return img


def _perspective_coeffs(dst, src):
    A, B = [], []
    for (x, y), (u, v) in zip(dst, src):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        B += [u, v]
    return np.linalg.solve(np.array(A, dtype=float), np.array(B, dtype=float)).tolist()


# ---------------------------------------------------------------- emails
def write_email(doc: Doc, path: Path) -> None:
    e = doc.email
    msg = EmailMessage()
    msg["From"] = e["from"]
    msg["To"] = e.get("to", BUYER["email"])
    msg["Subject"] = e["subject"]
    msg["Date"] = format_datetime(datetime.fromisoformat(e["date"]).replace(tzinfo=timezone(timedelta(hours=1))))
    msg["Message-ID"] = f"<{doc.key.lower()}.{RNG.randint(10**8, 10**9)}@{e['from'].split('@')[-1].rstrip('>')}>"
    msg.set_content(e["body"])
    path.write_bytes(bytes(msg))


# ---------------------------------------------------------------- the batch
def build_docs() -> list[Doc]:
    v1, v2, v3, v4, v5, v6, v7, v8 = (V[f"V00{i}"] for i in range(1, 9))
    unknown_office = {
        "name": "Office Supply Express Ltd", "address": ["Unit 4, Riverside Park", "Manchester M17 1AB", "United Kingdom"],
        "country": "GB", "vat_id": "GB 412 7781 05", "email": "invoices@officesupply-express.example", "phone": "",
        "iban": _iban("GB", "SYNT" + "40127" + "7" + "92018834"[:8]), "bic": "SYNTGB2LXXX", "payment_terms_days": 7,
    }
    hardware = {"name": "Baumarkt Kreuzberg", "address": ["Gneisenaustraße 61", "10961 Berlin"], "tax_number": "29/123/45678"}
    wholesale = {"name": "GrossMarkt Berlin-Friedrichshain", "address": ["Storkower Str. 132", "10407 Berlin"], "tax_number": "27/554/01182"}
    fraud_iban = _iban("LT", "70440" + "60012845733")

    milk_rc = "Vollmilch 3,5% (Kanne 10 L)"
    docs = [
        Doc("D01", "Rechnung_KH-24-0912.pdf", "invoice", "pdf", v1, style="modern", number="KH-24-0912", date="2026-10-14",
            po="PO-2026-101", lines=[Line("Rohkaffee Brasilien Santos NY2 17/18 (60-kg-Sack)", 300, "kg", 6.80, 7)],
            extra=["Lieferung erfolgte am 13.10.2026 (Lieferschein LS-55120)."],
            truth={"type": "invoice", "decision": "approve", "flags": []}),
        Doc("D02", "KH-24-0931_invoice.pdf", "invoice", "pdf", v1, style="modern", number="KH-24-0931", date="2026-10-21",
            po="PO-2026-101", lines=[Line("Rohkaffee Äthiopien Yirgacheffe G2", 200, "kg", 10.53, 7)],
            truth={"type": "invoice", "decision": "hold", "flags": ["PRICE_DRIFT"], "at_risk": 241.82,
                   "note": "Unit price 10.53 vs PO 9.40 (+12.0%)"}),
        Doc("D03", "IMG_4471.jpg", "invoice", "photo", v2, style="classic", number="MH-77812", date="2026-10-23",
            po="PO-2026-104", period="KW 43", lines=[Line(milk_rc, 400, "L", 1.09, 7)],
            truth={"type": "invoice", "decision": "hold", "flags": ["SHORT_DELIVERY"], "at_risk": 139.96,
                   "note": "Voice memo D31: only 280 L of 400 L arrived in KW 43"}),
        Doc("D04", "IMG_4502.jpg", "invoice", "photo", v2, style="classic", number="MH-77831", date="2026-10-30",
            po="PO-2026-104", period="KW 44", lines=[Line(milk_rc, 400, "L", 1.09, 19)],
            truth={"type": "invoice", "decision": "hold", "flags": ["VAT_RATE"], "at_risk": 52.32,
                   "note": "Milk charged at 19% instead of reduced 7%"}),
        Doc("D05", "PackWerk_RE_PW-2026-3381.pdf", "invoice", "pdf", v3, style="bold", number="PW-2026-3381", date="2026-10-16",
            po="PO-2026-102", lines=[Line("Kaffeebecher 12oz doppelwandig, bedruckt", 10000, "Stk", 0.085, 19)],
            truth={"type": "invoice", "decision": "approve", "flags": []}),
        Doc("D06", "Scan_2026-10-29.jpg", "invoice", "scan", v3, style="bold", number="PW-2026-3381", date="2026-10-16",
            po="PO-2026-102", lines=[Line("Kaffeebecher 12oz doppelwandig, bedruckt", 10000, "Stk", 0.085, 19)],
            stamp="KOPIE", handwriting="nochmal geschickt - schon bezahlt?",
            truth={"type": "invoice", "decision": "reject", "flags": ["DUPLICATE"], "at_risk": 1011.50,
                   "note": "Same invoice as D05, re-sent as scan"}),
        Doc("D07", "RGC-1022.pdf", "invoice", "pdf", v4, lang="en", style="minimal", number="RGC-1022", date="2026-10-12",
            po="PO-2026-103", lines=[Line("Colombia Supremo 17/18 green coffee, 60 kg bags", 600, "kg", 7.10, 0)],
            vat_note="VAT 0% - Intra-Community supply of goods, exempt under Art. 138 Directive 2006/112/EC. "
                     "Customer VAT ID DE318840527. Reverse charge: acquisition VAT due by the customer.",
            truth={"type": "invoice", "decision": "hold", "flags": ["SHORT_DELIVERY"], "at_risk": 426.00,
                   "note": "Delivery photo D32: 9 sacks of 60 kg (540 kg) received, 600 kg invoiced"}),
        Doc("D08", "RGC-1047.pdf", "invoice", "pdf", v4, lang="en", style="minimal", number="RGC-1047", date="2026-10-27",
            po="PO-2026-103", lines=[Line("Colombia Supremo 17/18 green coffee, 60 kg bags", 600, "kg", 7.10, 21)],
            truth={"type": "invoice", "decision": "hold", "flags": ["VAT_RATE"], "at_risk": 894.60,
                   "note": "Dutch 21% VAT charged on intra-EU B2B supply; should be 0% reverse charge"}),
        Doc("D09", "Fwd_ Rechnung Oktober.eml", "invoice", "email", v5, number="CT-2026-10", date="2026-10-31",
            period="Oktober 2026", lines=[Line("Unterhaltsreinigung 3 Filialen, Pauschale Oktober 2026", 1, "Monat", 1450.00, 19)],
            truth={"type": "invoice", "decision": "approve", "flags": []}),
        Doc("D10", "Re_ Rechnung September (Erinnerung).eml", "invoice", "email", v5, number="CT-2026-09-R", date="2026-10-28",
            period="September 2026", lines=[Line("Unterhaltsreinigung 3 Filialen, Pauschale September 2026", 1, "Monat", 1450.00, 19)],
            truth={"type": "invoice", "decision": "reject", "flags": ["DUPLICATE"], "at_risk": 1725.50,
                   "note": "Re-issue of CT-2026-09, already paid on 2026-10-05"}),
        Doc("D11", "BT-5531.pdf", "invoice", "pdf", v6, style="classic", number="BT-5531", date="2026-10-09", po="PO-2026-105",
            lines=[Line("Anfahrtspauschale", 1, "Pausch.", 45.00, 19),
                   Line("Arbeitszeit Techniker", 3.5, "Std.", 85.00, 19),
                   Line("Mahlscheiben-Set Mythos One", 2, "Set", 189.00, 19)],
            truth={"type": "invoice", "decision": "approve", "flags": []}),
        Doc("D12", "BT-5540.pdf", "invoice", "pdf", v6, style="classic", number="BT-5540", date="2026-10-28",
            lines=[Line("Anfahrtspauschale", 1, "Pausch.", 45.00, 19),
                   Line("Arbeitszeit Techniker (Entkalkung, Dichtungen)", 6, "Std.", 95.00, 19)],
            truth={"type": "invoice", "decision": "hold", "flags": ["PRICE_DRIFT"], "at_risk": 71.40,
                   "note": "Labour 95 €/h vs contract C-006 85 €/h (+11.8%)"}),
        Doc("D13", "Cloudly invoice CL-IE-88213.eml", "invoice", "email", v7, lang="en", number="CL-IE-88213", date="2026-10-01",
            period="October 2026", lines=[Line("POS Business plan (3 locations), October 2026", 1, "month", 249.00, 0)],
            truth={"type": "invoice", "decision": "approve", "flags": []}),
        Doc("D14", "IMG_4488.jpg", "invoice", "photo", v8, style="minimal", number="KB-1188", date="2026-10-16",
            period="01.-15.10.2026", lines=[Line("Kurierfahrten Berlin same-day", 14, "Fahrten", 12.50, 19)],
            truth={"type": "invoice", "decision": "approve", "flags": []}),
        Doc("D15", "Neue Bankverbindung - Rechnung KH-24-0958.eml", "invoice", "email", v1, number="KH-24-0958", date="2026-10-29",
            po="PO-2026-101", lines=[Line("Rohkaffee Brasilien Santos NY2 17/18", 300, "kg", 6.80, 7)], iban=fraud_iban,
            truth={"type": "invoice", "decision": "reject", "flags": ["BANK_DETAILS_CHANGED", "SENDER_DOMAIN_MISMATCH"],
                   "at_risk": 2182.80, "note": "Lookalike sender domain + new Lithuanian IBAN: classic payment-diversion fraud"}),
        Doc("D16", "OSE_Invoice_4471.pdf", "invoice", "pdf", unknown_office, lang="en", style="bold", number="OSE-4471", date="2026-10-25",
            lines=[Line("Toner cartridge HL-L3270 compatible", 4, "pcs", 89.00, 19),
                   Line("Thermal receipt rolls 80mm (50 pack)", 1, "pack", 95.00, 19),
                   Line("Label printer LP-420 Pro", 1, "pcs", 628.00, 19)],
            extra=["Thank you for your order! Payment due within 7 days."],
            truth={"type": "invoice", "decision": "escalate", "flags": ["UNKNOWN_VENDOR", "MISSING_PO"], "at_risk": 1284.01,
                   "note": "Vendor not in master data, no PO, above EUR 500 PO threshold"}),
        Doc("D17", "PackWerk_RE_PW-2026-3402.pdf", "invoice", "pdf", v3, style="bold", number="PW-2026-3402", date="2026-10-22",
            po="PO-2026-102", lines=[Line("Kraftpapierbeutel 250 g mit Aromaventil", 5000, "Stk", 0.21, 19)],
            truth={"type": "invoice", "decision": "approve", "flags": []}),
        Doc("D18", "PW-2026-3410.pdf", "invoice", "pdf", v3, style="bold", number="PW-2026-3410", date="2026-10-30",
            po="PO-2026-102", lines=[Line("Kaffeebecher 12oz doppelwandig, bedruckt", 12000, "Stk", 0.085, 19)],
            truth={"type": "invoice", "decision": "hold", "flags": ["QTY_EXCEEDS_PO"], "at_risk": 202.30,
                   "note": "PO 20,000 cups; 10,000 already invoiced (PW-2026-3381); 12,000 billed -> 2,000 over"}),
        Doc("D19", "KH-24-0950.pdf", "invoice", "pdf", v1, style="modern", number="KH-24-0950", date="2026-10-28",
            po="PO-2026-101", lines=[Line("Rohkaffee Äthiopien Yirgacheffe G2", 200, "kg", 9.40, 7)], net_override=D("1980.00"),
            truth={"type": "invoice", "decision": "hold", "flags": ["ARITHMETIC"], "at_risk": 107.00,
                   "note": "Line total 1,880.00 but net stated as 1,980.00"}),
        Doc("D20", "IMG_4510.jpg", "invoice", "photo", v2, style="classic", number="MH-77801", date="2026-10-16",
            po="PO-2026-104", period="KW 42", lines=[Line(milk_rc, 400, "L", 1.09, 7)],
            truth={"type": "invoice", "decision": "approve", "flags": []}),
        Doc("D21", "Quittung_Baumarkt.jpg", "receipt", "photo", hardware, number="4471-0192", date="2026-10-24",
            lines=[Line("Kabelbinder 200mm 100St", 1, "Stk", 6.49, 19), Line("Wasserfilter-Kartusche", 3, "Stk", 14.99, 19),
                   Line("Schraubendreher-Set", 1, "Stk", 12.79, 19)],
            extra=["Bezahlt mit Girocard", "Vielen Dank für Ihren Einkauf!"],
            truth={"type": "receipt", "decision": "file", "flags": [], "note": "Card-paid expense receipt under EUR 250"}),
        Doc("D22", "MH-77824_Sahne.pdf", "invoice", "pdf", v2, style="classic", number="MH-77824", date="2026-10-26",
            lines=[Line("Schlagsahne 30% (Kanne 5 L)", 40, "L", 3.20, 7)],
            truth={"type": "invoice", "decision": "approve", "flags": [], "note": "No PO needed below EUR 500"}),
        Doc("D23", "Cloudly_Order_Form_Renewal_2027.pdf", "contract", "pdf", v7, lang="en",
            extra=[
                f"Customer: {BUYER['name']}, {', '.join(BUYER['address'])} (VAT {BUYER['vat_id']})",
                "Order form no. OF-2027-0331 - Date: 20 October 2026",
                "## 1. Subscription",
                "Product: Cloudly POS Business plan, 3 locations, unlimited registers.",
                "Term: 1 January 2027 - 31 December 2027, renews automatically for 12 months unless cancelled 30 days before the end of term.",
                "## 2. Fees",
                "Monthly fee: EUR 279.00 (previous term: EUR 249.00). Billed monthly in advance. "
                "Reverse charge applies to EU business customers.",
                "## 3. Notice",
                "If you do not wish to accept the new pricing, notify billing@cloudly.io before 1 December 2026. "
                "Continued use after 1 January 2027 constitutes acceptance.",
                "",
                "Signed for Cloudly Software Ltd: Aoife Byrne, Head of Billing",
            ],
            truth={"type": "contract", "decision": "file", "flags": ["CONTRACT_PRICE_CHANGE"],
                   "note": "Renewal raises fee 249 -> 279 EUR/month (+12%) from 2027; info, not payable"}),
        Doc("D24", "Lieferschein_LS-55120.pdf", "delivery_note", "pdf", v1, style="modern", number="LS-55120", date="2026-10-13",
            po="PO-2026-101", lines=[Line("Rohkaffee Brasilien Santos NY2 17/18 (60-kg-Sack)", 300, "kg", 0, 7)],
            extra=["Ware in einwandfreiem Zustand erhalten: ______________ (Unterschrift)"],
            truth={"type": "delivery_note", "decision": "file", "flags": []}),
        Doc("D25", "Kurier_Blitz_KB-1196.pdf", "invoice", "pdf", v8, style="minimal", number="KB-1196", date="2026-10-31",
            period="16.-31.10.2026", lines=[Line("Kurierfahrten Berlin same-day", 9, "Fahrten", 12.50, 19)],
            truth={"type": "invoice", "decision": "approve", "flags": []}),
        Doc("D26", "Baristech_BT-5519.pdf", "invoice", "pdf", v6, style="classic", number="BT-5519", date="2026-10-02",
            lines=[Line("Anfahrtspauschale", 1, "Pausch.", 45.00, 19), Line("Arbeitszeit Techniker", 1.5, "Std.", 85.00, 19)],
            truth={"type": "invoice", "decision": "approve", "flags": []}),
        Doc("D27", "Gutschrift_GS-0412.pdf", "credit_note", "pdf", v1, style="modern", number="GS-0412", date="2026-10-20",
            related="KH-24-0912", lines=[Line("Gutschrift: 1 Sack beschädigt (Brasilien Santos)", 10, "kg", -6.80, 7)],
            extra=["Der Betrag wird mit offenen Rechnungen verrechnet."],
            truth={"type": "credit_note", "decision": "approve", "flags": [], "note": "Net against KH-24-0912"}),
        Doc("D28", "PW-2026-3395.pdf", "invoice", "pdf", v3, style="bold", number="PW-2026-3395", date="2026-10-19",
            lines=[Line("Deckel für Becher 12oz, schwarz", 2000, "Stk", 0.032, 19)],
            truth={"type": "invoice", "decision": "approve", "flags": [], "note": "No PO needed below EUR 500"}),
        Doc("D29", "IMG_4533.jpg", "receipt", "photo", wholesale, number="88-20419", date="2026-10-24",
            lines=[Line("Rohrzucker braun 1kg", 10, "Stk", 1.29, 7), Line("Spülmittel Profi 5L", 2, "Stk", 11.49, 19),
                   Line("Hafermilch Barista 1L", 12, "Stk", 1.99, 19), Line("Zitronen Netz 1kg", 2, "Stk", 2.79, 7)],
            extra=["Kartenzahlung VISA ****4417", "Kunden-Nr. 300-0882"],
            truth={"type": "receipt", "decision": "file", "flags": [], "note": "Card-paid, mixed 7%/19% receipt"}),
        Doc("D30", "Newsletter PackWerk Herbstaktion.eml", "newsletter", "email", v3,
            truth={"type": "other", "decision": "file", "flags": []}),
        Doc("D31", "Sprachmemo_Tom_Filiale-Mitte.wav", "receiving_note", "audio", v2,
            truth={"type": "receiving_note", "decision": "file", "flags": [],
                   "note": "Branch manager's voice memo: KW 43 milk delivery short (28 of 40 cans)"}),
        Doc("D32", "Wareneingang_RGC_13-10.jpg", "delivery_photo", "generated_photo", v4,
            truth={"type": "delivery_photo", "decision": "file", "flags": [],
                   "note": "Photo of the RGC-1022 delivery: 9 sacks (image generated with Muse Image)"}),
    ]

    # ---- email bodies
    d = {x.key: x for x in docs}

    def inline_invoice(doc: Doc) -> str:
        _, net, vat_parts, vat, gross = doc.totals()
        L = LABELS[doc.lang]
        rows = [f"{L['number']}: {doc.number}", f"{L['date']}: {de_date(doc.date) if doc.lang == 'de' else en_date(doc.date)}"]
        if doc.period:
            rows.append(f"{L['period']}: {doc.period}")
        if doc.po:
            rows.append(f"{L['po']}: {doc.po}")
        rows.append("")
        for l in doc.lines:
            rows.append(f"  {qty_fmt(l.qty, doc.lang)} {l.unit}  {l.desc}  à {money(D(l.price), doc.lang)}  = {money(l.net, doc.lang)}")
        rows.append("")
        rows.append(f"{L['net']}: {money(net, doc.lang)}")
        for r, a in vat_parts.items():
            rows.append(f"{L['vat']} {r}%: {money(a, doc.lang)}")
        rows.append(f"{L['gross']}: {money(gross, doc.lang)}")
        return "\n".join(rows)

    d["D09"].email = {
        "from": "Spree Roastery Filiale Mitte <mitte@spree-roastery.example>", "date": "2026-10-31T16:12:00",
        "subject": "Fwd: Rechnung Oktober",
        "body": "Hi, kam an die Filiale statt an die Buchhaltung, bitte bezahlen. LG Tom\n\n"
                "---------- Forwarded message ---------\n"
                f"Von: CleanTeam Berlin <{v5['email']}>\nDatum: 31.10.2026\nBetreff: Rechnung Oktober\n\n"
                "Sehr geehrte Damen und Herren,\n\nanbei unsere Rechnung für die Unterhaltsreinigung im Oktober.\n\n"
                + inline_invoice(d["D09"]) +
                f"\n\nBitte überweisen Sie den Betrag innerhalb von 14 Tagen auf IBAN {fmt_iban(v5['iban'])}.\n"
                f"USt-IdNr. {v5['vat_id']}\n\nMit freundlichen Grüßen\n{v5['contact']}\n{v5['name']}, {', '.join(v5['address'])}",
    }
    d["D10"].email = {
        "from": f"CleanTeam Berlin <{v5['email']}>", "date": "2026-10-28T09:41:00",
        "subject": "Re: Rechnung September (Erinnerung)",
        "body": "Sehr geehrte Damen und Herren,\n\nleider konnten wir zu unserer Rechnung für September noch keinen "
                "Zahlungseingang feststellen. Wir haben die Rechnung neu ausgestellt:\n\n"
                + inline_invoice(d["D10"]) +
                f"\n\nBitte überweisen Sie umgehend auf IBAN {fmt_iban(v5['iban'])}.\n\n"
                f"Mit freundlichen Grüßen\n{v5['contact']}\n{v5['name']}",
    }
    d["D13"].email = {
        "from": f"Cloudly Billing <{v7['email']}>", "date": "2026-10-01T06:02:00",
        "subject": "Your Cloudly invoice CL-IE-88213",
        "body": f"Hi Spree Roastery team,\n\nThanks for being a Cloudly customer. Here is your invoice.\n\n"
                + inline_invoice(d["D13"]) +
                f"\n\nVAT: reverse charge - customer to account for VAT (Art. 196 Directive 2006/112/EC). "
                f"Customer VAT ID {BUYER['vat_id']}. Supplier VAT ID {v7['vat_id']}.\n"
                f"Pay by bank transfer to IBAN {fmt_iban(v7['iban'])} (BIC {v7['bic']}).\n\n"
                f"Cloudly Software Ltd, {', '.join(v7['address'])}",
    }
    d["D15"].email = {
        "from": "Kaffeeimport Hansa Buchhaltung <buchhaltung@kaffeimport-hansa.com>", "date": "2026-10-29T22:57:00",
        "subject": "Neue Bankverbindung - Rechnung KH-24-0958",
        "body": "Sehr geehrte Kunden,\n\naufgrund einer Umstellung unserer Hausbank bitten wir Sie, alle Zahlungen ab sofort "
                "ausschließlich auf unser neues Konto zu leisten. Bitte aktualisieren Sie Ihre Stammdaten. "
                "Aus organisatorischen Gründen ist unsere Buchhaltung telefonisch derzeit nicht erreichbar.\n\n"
                f"Neue Bankverbindung:\nIBAN {fmt_iban(fraud_iban)}\nBIC SYNTLT2XXXX\n\n"
                + inline_invoice(d["D15"]) +
                "\n\nWir bitten um Zahlung bis spätestens 03.11.2026.\n\nMit freundlichen Grüßen\nJana Petersen\n"
                "Kaffeeimport Hansa GmbH",
    }
    d["D30"].email = {
        "from": f"PackWerk Newsletter <newsletter@{v3['domain']}>", "date": "2026-10-27T10:00:00",
        "subject": "Herbstaktion: 10% auf Kraftpapierbeutel bis 15.11.",
        "body": "Liebe Kundinnen und Kunden,\n\nnur bis zum 15. November: 10% Rabatt auf alle Kraftpapierbeutel ab 2.000 Stück. "
                "Jetzt im Shop bestellen!\n\nIhr PackWerk-Team\n\nAbmelden: https://packwerk.example/unsubscribe",
    }
    return docs


VOICE_MEMO = ("Hey, hier ist Tom aus der Filiale Mitte. Kurz wegen der Milch von der Molkerei Havelland, "
              "Kalenderwoche dreiundvierzig. Da sind nur achtundzwanzig Kannen gekommen, statt vierzig. Also "
              "zweihundertachtzig Liter statt vierhundert. Der Fahrer meinte, der Rest kommt nicht mehr. Bitte zahlt "
              "nicht die volle Rechnung. Danke dir!")
SOURCES = OUT / "sources"


def write_voice_memo(path: Path) -> None:
    """Synthetic voice memo (sample data only), 24 kHz mono 16-bit WAV. The committed one was made with ElevenLabs
    text-to-speech by make_voice_memo.py; without it, macOS text-to-speech is the fallback."""
    cached = SOURCES / "voice_memo_tom.wav"
    if not cached.exists():
        aiff = OUT / ".tmp" / "memo.aiff"
        subprocess.run(["say", "-v", "Eddy (German (Germany))", "-r", "175", "-o", str(aiff), VOICE_MEMO], check=True)
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@24000", "-c", "1", str(aiff), str(cached)], check=True)
    shutil.copy(cached, path)


def write_delivery_photo(path: Path) -> None:
    """Delivery photo generated once with Meta's Muse Image (data/samples/sources), plus a taped receiving note."""
    img = Image.open(SOURCES / "delivery_rgc_muse_image.png").convert("RGB")
    W, H = img.size
    note = Image.new("RGB", (int(W * 0.25), int(H * 0.16)), (250, 246, 222))
    d = ImageDraw.Draw(note)
    fnt = _font(FONTS / "Bradley Hand Bold.ttf", int(H * 0.03))
    for k, line in enumerate(["Wareneingang 13.10.", "RGC-1022 / Colombia", "gez. Tom"]):
        d.text((int(W * 0.012), int(H * 0.015) + k * int(H * 0.042)), line, font=fnt, fill=(25, 35, 120))
    note = note.rotate(4, expand=True, fillcolor=(0, 0, 0))
    mask = note.convert("L").point(lambda v: 255 if v > 0 else 0)
    img.paste(note, (int(W * 0.03), int(H * 0.06)), mask)
    img.thumbnail((1600, 1600))
    img.save(path, "JPEG", quality=84)


def compute_truth_amounts(doc: Doc) -> dict:
    _, net, _, vat, gross = doc.totals() if doc.lines else (0, D(0), {}, D(0), D(0))
    return {"net": float(net), "vat": float(vat), "gross": float(gross)}


def main() -> None:
    if BATCH.exists():
        shutil.rmtree(BATCH)
    BATCH.mkdir(parents=True)
    REF.mkdir(parents=True, exist_ok=True)
    tmp = OUT / ".tmp"
    tmp.mkdir(exist_ok=True)

    for name, data in (("buyer", BUYER), ("vendors", VENDORS), ("purchase_orders", PURCHASE_ORDERS),
                       ("contracts", CONTRACTS), ("invoice_history", INVOICE_HISTORY)):
        (REF / f"{name}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    docs = build_docs()
    truth = []
    for i, doc in enumerate(docs):
        target = BATCH / doc.filename
        if doc.fmt == "email":
            write_email(doc, target)
        elif doc.fmt == "audio":
            write_voice_memo(target)
        elif doc.fmt == "generated_photo":
            write_delivery_photo(target)
        elif doc.fmt == "pdf":
            render_pdf(doc, target)
        else:
            pdf_path = tmp / f"{doc.key}.pdf"
            render_pdf(doc, pdf_path)
            page = add_overlays(rasterize(pdf_path, 1.6 if doc.kind != "receipt" else 3.2), doc)
            img = phone_photo(page, seed=i) if doc.fmt == "photo" else scanned(page, seed=i)
            img.save(target, "JPEG", quality=78)
        truth.append({"key": doc.key, "filename": doc.filename, "format": doc.fmt, **doc.truth,
                      "amounts": compute_truth_amounts(doc)})
    shutil.rmtree(tmp)

    (BATCH / "manifest.json").write_text(json.dumps({
        "batch": "sample", "description": "SYNTHETIC October batch for Spree Roastery GmbH (demo data)",
        "documents": [{"key": d.key, "filename": d.filename} for d in docs],
    }, indent=2, ensure_ascii=False) + "\n")
    (OUT / "ground_truth.json").write_text(json.dumps({
        "note": "Planted anomalies for evaluation only. Never shown to the agent.", "documents": truth,
    }, indent=2, ensure_ascii=False) + "\n")
    flagged = [t for t in truth if t["flags"] and t["decision"] != "file"]
    print(f"wrote {len(docs)} documents, {len(flagged)} with planted anomalies, "
          f"EUR at risk {sum(t.get('at_risk', 0) for t in truth):,.2f}")


if __name__ == "__main__":
    main()
