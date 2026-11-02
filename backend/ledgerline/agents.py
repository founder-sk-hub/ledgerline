"""The Ledgerline agent: plan -> intake -> investigate -> verify -> draft -> STOP for human approval.

Every model call, tool call and decision is emitted as an event; the audit trail and the
UI are both built from those events.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from datetime import date, timedelta
from typing import Any, Awaitable, Callable

from .config import BUDGET_USD, EFFORT, POLICY
from .db import DB
from .documents import asr_wav, model_content, page_images
from .events import Bus
from .providers import MetaMedia, Provider, ProviderError, structured_request, structured_result
from .tools import (DRAFTER_TOOLS, EVIDENCE_TYPES, FLAG_CODES, INFO_CODES, INVESTIGATOR_TOOLS, PAYABLE, Books, check_goods_receipt,
                    check_vat,
                    combine_at_risk, compare_to_po, detect_duplicate, doc_gross, lookup_vendor, match_vendor, num,
                    parse_date, r2)


class AgentError(RuntimeError):
    pass


class BudgetExceeded(AgentError):
    pass


# ---------------------------------------------------------------- schemas
BBOX = {"type": "array", "items": {"type": "integer"}, "description": "[x_min, y_min, x_max, y_max] on a 0-1000 grid"}
EVIDENCE = {"type": "object", "properties": {
    "field": {"type": "string"}, "page": {"type": "integer"}, "quote": {"type": "string"}, "bbox": BBOX},
    "required": ["field", "page", "quote"]}

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "doc_type": {"type": "string", "enum": ["invoice", "credit_note", "receipt", "contract", "delivery_note",
                                                "reminder", "receiving_note", "delivery_photo", "other"]},
        "language": {"type": "string"},
        "vendor_name": {"type": "string"}, "vendor_address": {"type": "string"},
        "vendor_country": {"type": "string", "description": "ISO 3166-1 alpha-2"},
        "vendor_vat_id": {"type": "string"}, "vendor_email": {"type": "string"}, "sender_email": {"type": "string"},
        "iban": {"type": "string"}, "bic": {"type": "string"},
        "buyer_name": {"type": "string"}, "buyer_vat_id": {"type": "string"},
        "invoice_number": {"type": "string"}, "issue_date": {"type": "string"}, "due_date": {"type": "string"},
        "service_period": {"type": "string"}, "po_number": {"type": "string"},
        "related_invoice_number": {"type": "string"}, "currency": {"type": "string"},
        "lines": {"type": "array", "items": {"type": "object", "properties": {
            "description": {"type": "string"}, "quantity": {"type": "number"}, "unit": {"type": "string"},
            "unit_price": {"type": "number"}, "net_amount": {"type": "number"}, "vat_rate": {"type": "number"},
            "vat_category": {"type": "string", "enum": ["food", "goods", "services", "digital_services", "other"]}},
            "required": ["description", "quantity", "unit_price", "net_amount", "vat_rate", "vat_category"]}},
        "prices_include_vat": {"type": "boolean"},
        "net_total": {"type": "number"}, "vat_total": {"type": "number"}, "gross_total": {"type": "number"},
        "vat_breakdown": {"type": "array", "items": {"type": "object", "properties": {
            "rate": {"type": "number"}, "net": {"type": "number"}, "vat": {"type": "number"}},
            "required": ["rate", "net", "vat"]}},
        "vat_note": {"type": "string"},
        "payment_status": {"type": "string", "enum": ["unpaid", "paid", "unknown"]},
        "notes": {"type": "string"},
        "contract_terms": {"type": "array", "items": {"type": "object", "properties": {
            "term": {"type": "string"}, "value": {"type": "string"}}, "required": ["term", "value"]}},
        "reference": {"type": "string"},
        "received_items": {"type": "array", "items": {"type": "object", "properties": {
            "description": {"type": "string"}, "quantity": {"type": "number"}, "unit": {"type": "string"}},
            "required": ["description", "quantity", "unit"]}},
        "count_target": {"type": "string"},
        "unit_size": {"type": "number"},
        "counted_items": {"type": "integer"},
        "evidence": {"type": "array", "items": EVIDENCE},
        "confidence": {"type": "number"},
        "uncertain_fields": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["doc_type", "vendor_name", "invoice_number", "issue_date", "lines", "net_total", "vat_total",
                 "gross_total", "notes", "evidence", "confidence"],
}

PLAN_SCHEMA = {"type": "object", "properties": {
    "summary": {"type": "string"},
    "steps": {"type": "array", "items": {"type": "object", "properties": {
        "title": {"type": "string"}, "detail": {"type": "string"}}, "required": ["title", "detail"]}},
    "watchlist": {"type": "array", "items": {"type": "object", "properties": {
        "filename": {"type": "string"}, "reason": {"type": "string"}}, "required": ["filename", "reason"]}},
}, "required": ["summary", "steps", "watchlist"]}

VERIFY_SCHEMA = {"type": "object", "properties": {
    "verdict": {"type": "string", "enum": ["confirmed", "disputed"]},
    "overall_confidence": {"type": "number"},
    "claims": {"type": "array", "items": {"type": "object", "properties": {
        "claim": {"type": "string"}, "supported": {"type": "boolean"}, "page": {"type": "integer"},
        "quote": {"type": "string"}, "bbox": BBOX, "confidence": {"type": "number"}},
        "required": ["claim", "supported", "page", "quote", "confidence"]}},
    "notes": {"type": "string"},
}, "required": ["verdict", "overall_confidence", "claims", "notes"]}

REREAD_SCHEMA = {"type": "object", "properties": {
    "answer": {"type": "string"}, "quote": {"type": "string"}, "page": {"type": "integer"}, "bbox": BBOX,
    "confidence": {"type": "number"}}, "required": ["answer", "quote", "page", "confidence"]}


# ---------------------------------------------------------------- prompts
def _company(books: Books) -> str:
    b = books.buyer
    return f"{b['name']} ({', '.join(b['address'])}; VAT ID {b['vat_id']})"


def planner_prompt(books: Books) -> str:
    return f"""You are the planning agent of Ledgerline, the accounts-payable back office of {_company(books)}.
You receive only the manifest of an incoming batch (file names, types, email senders and subjects).
Write the execution plan for this batch. The workflow is fixed: read every document, investigate each one against
the vendor master, purchase orders, contracts, VAT rules and payment history, have every decision independently
verified against the source document, draft the payment batch and vendor emails, then STOP for human approval -
nothing is paid or sent without a human.
Make the steps specific to this batch (counts, formats, languages). In `watchlist`, name the files that deserve
extra scrutiny from manifest cues alone (possible re-sends or duplicates, bank-detail changes, reminders, unknown
senders, forwarded mail, non-invoices) and say why. Be concise."""


def intake_prompt(books: Books) -> str:
    return f"""You read incoming accounts-payable documents for {_company(books)}.
Extract exactly what the document says. Do not fix errors and do not invent values; downstream checks rely on
seeing the document as printed. Use "" for absent text fields.
- doc_type: invoice | credit_note | receipt (till/card receipt) | contract (incl. order forms, renewals, price
  notices) | delivery_note (the supplier's paper) | reminder (payment reminder with no invoice data) |
  receiving_note (our own staff reporting what actually arrived, e.g. a transcribed voice memo) | delivery_photo
  (a photo our staff took of delivered goods) | other (newsletters, marketing).
  An email that contains a complete invoice inline is an invoice.
- Numbers as plain decimals (German "1.234,56" -> 1234.56; "0,085" -> 0.085). vat_rate in percent (19, not 0.19).
  Dates as YYYY-MM-DD. Credit notes: keep the sign as printed.
- lines: one per billed line, net_amount = the line total as printed. Receipts print prices incl. VAT:
  set prices_include_vat=true and copy the printed amounts.
- vat_category per line: food (food itself: roasted/green coffee beans, dairy milk, cream, sugar, fruit, bread),
  goods (everything else physical, incl. cups, packaging, parts, plant-based drinks), services (labour, cleaning,
  maintenance, transport/courier), digital_services (software, SaaS), other.
- vendor_* = the issuer of the document, never {books.buyer['name']}. iban/bic = the account this document asks to
  be paid to (body or footer). sender_email = the From address for emails.
- notes: what a careful bookkeeper would notice - stamps (KOPIE/COPY), handwriting, requests to change bank
  details, urgency or pressure, re-issued numbers, unusual payment instructions. Empty if nothing.
- contract_terms (contracts/order forms): key terms as {{term, value}}; value is the plain number for prices.
- evidence: for invoice_number, issue_date, vendor_name, po_number, iban, every line, net_total, vat_total,
  gross_total and anything in notes: the 1-based page, the exact printed text, and bbox [x_min, y_min, x_max, y_max]
  on a normalized 0-1000 grid of that page image ((0,0) = top-left). For email text use page 0 and no bbox.
- receiving_note: vendor_*, service_period (e.g. "KW 43" for calendar week 43) and reference (invoice, PO or
  delivery mentioned); received_items = what actually arrived, converted to the invoice unit when the speaker
  gives it (e.g. "280 Liter" -> 280, "L"). Transcripts can contain recognition errors; read them sensibly.
- delivery_photo: count_target = a short noun phrase naming one physical unit to count (e.g. "jute coffee sack",
  "milk can"); unit_size = quantity per unit printed on the packaging (60 for "60 KG"), else 0; counted_items =
  your own count; reference / vendor_* / issue_date from any label or note in the photo.
- Fields that do not apply: "" for text, 0 for numbers, [] for lists.
- confidence 0-1 for the whole extraction; uncertain_fields lists fields that were hard to read."""


def investigator_prompt(books: Books) -> str:
    return f"""You are the investigation agent of Ledgerline, the accounts-payable agent of {_company(books)}.
You review ONE document and decide what happens to it. Money only moves after a human approves your work.

Deterministic tools compute the facts - trust their arithmetic, do not redo it. You decide which checks are
relevant and what the findings mean:
- lookup_vendor: vendor master match, bank details (IBAN) and sender-domain checks.
- compare_to_po: PO / contract prices and quantities; PO policy (PO required above {POLICY['po_required_above_eur']:.0f}
  EUR unless a contract covers the vendor). For contracts it compares new terms with the existing agreement.
- check_vat: VAT rules (DE 7% food / 19% standard; intra-EU B2B 0% with reverse charge) and invoice arithmetic.
- check_goods_receipt: three-way match of invoiced quantities against what our staff recorded as received
  (delivery photos counted by SAM 3.1, transcribed voice memos).
- detect_duplicate: paid history and earlier documents in this batch.
- reread_document: ask the original document a focused question when the extraction looks wrong or unclear.
- submit_decision: your final answer, exactly once.

Policy:
- Payables (invoice, credit_note, reminder): run lookup_vendor, detect_duplicate, compare_to_po, check_vat and
  check_goods_receipt. Call independent tools in parallel.
- receiving_note / delivery_photo: our own goods-receipt evidence. Run check_goods_receipt to see which invoice it
  belongs to, then decision "file". Describe the link exactly as the tool reports it (e.g. "same vendor and
  delivery week"); never claim the document mentions an invoice number it doesn't contain.
- receipt: small card-paid receipts are filed (decision "file") after check_vat confirms the arithmetic.
- contract / delivery_note / other: decision "file". For contracts run lookup_vendor and compare_to_po and keep
  CONTRACT_PRICE_CHANGE when prices change.
- Decisions: approve (pay as-is in the next batch) | hold (do not pay until the vendor corrects something; we will
  email them) | reject (must never be paid: duplicate or suspected fraud) | escalate (a human must decide: unknown
  vendor, missing PO, conflicting evidence, low confidence) | file (nothing to pay).
- Signs of payment-diversion fraud (changed bank details, lookalike sender domain, pressure, "not reachable by
  phone"): reject, and never use bank details from the document.
- Keep a flag only when the evidence supports it; you may dismiss a tool finding if you explain why in the rationale.
- Flag codes: {", ".join(FLAG_CODES)}.
- rationale: 2-4 plain sentences a bookkeeper understands, with the concrete numbers."""


def verifier_prompt(books: Books) -> str:
    return f"""You are the independent verification agent of Ledgerline ({_company(books)}).
Another agent proposed a decision about the attached document. Check its claims against the ORIGINAL document
(the image or email text), not against the extraction - the extraction may be wrong.
Write one claim per material fact: vendor, invoice number, amounts, PO number, IBAN, VAT rate, and every flag.
For each claim: supported true/false, the exact quote from the document, the 1-based page (0 for email text), a
bbox [x_min, y_min, x_max, y_max] on a normalized 0-1000 grid of that page image, and your confidence 0-1.
Facts from the company's own systems (PO prices, vendor-master IBAN, payment history) and findings computed from
OTHER documents (photo counts by SAM 3.1, transcribed voice memos) are given to you as true; you verify the side
of each claim that this document shows.
verdict = "disputed" if any material claim is not supported by the document or the decision does not follow from
the evidence; otherwise "confirmed". overall_confidence reflects how sure you are about the decision."""


def drafter_prompt(books: Books) -> str:
    return f"""You are the drafting agent of Ledgerline ({_company(books)}). Every document has been reviewed and
independently verified. Prepare the work for the human approver - you cannot pay or send anything yourself.
1. draft_payment with the doc_ids of every document whose final status is "approve" (credit notes included; they
   net against the same vendor).
2. draft_email for each vendor that must act. hold: ask for a corrected invoice or credit note, citing the exact
   numbers and amounts. reject as duplicate: say politely that it is a duplicate / already paid and give the
   original. suspected fraud: write to the vendor's KNOWN contact from the vendor master (never to the suspicious
   sender), describe the suspicious message and ask them to confirm their bank details by phone. Group all issues
   for one vendor into one email. Write in the vendor's language (German "Sie" for German vendors) like an
   experienced bookkeeper: no internal jargon such as "at risk", flags or doc ids. Sign as
   "Buchhaltung, {books.buyer['name']}". No emails for escalations, filed documents or approved invoices.
3. request_approval with a short summary IN ENGLISH for the approver: what will be paid, what is held and why,
   the EUR at risk that was caught, and what needs a human decision.
Use only the numbers given to you."""


# ---------------------------------------------------------------- run context
class Run:
    def __init__(self, run_id: str, db: DB, bus: Bus, provider: Provider, books: Books, docs: list[dict],
                 media: MetaMedia | None = None):
        self.run_id, self.db, self.bus, self.p, self.books, self.docs = run_id, db, bus, provider, books, docs
        self.media = media if provider.cfg.media else None  # private engines never send media to Meta
        self.transcripts: dict[str, str] = {}
        self.by_id = {d["doc_id"]: d for d in docs}
        self.issues: dict[str, list[dict]] = {d["doc_id"]: [] for d in docs}
        self.decisions: dict[str, dict] = {}
        self.final: dict[str, dict] = {}
        self.payment_batch: dict | None = None
        self.emails: list[dict] = []
        self.cost = 0.0

    # -------------------------------------------------------- plumbing
    def emit(self, type_: str, payload: dict | None = None, agent: str | None = None, doc_id: str | None = None):
        return self.bus.emit(self.run_id, type_, payload, agent=agent, doc_id=doc_id)

    async def llm(self, agent: str, doc_id: str | None, purpose: str, messages: list[dict], *, effort: str | None = None,
                  **kw):
        if self.db.total_spend() >= BUDGET_USD:
            raise BudgetExceeded(f"local budget guard reached ({BUDGET_USD:.2f} USD); raise LEDGERLINE_BUDGET_USD")
        base = {"agent": agent, "purpose": purpose, "provider": self.p.cfg.key, "model": self.p.cfg.model}
        try:
            res = await self.p.chat(messages, effort=effort, **kw)
        except ProviderError as e:
            self.emit("llm.call", {**base, "ok": False, "error": str(e)[:500]}, agent, doc_id)
            raise
        self.cost += res.cost_usd
        self.db.add_spend(self.run_id, self.p.cfg.key, self.p.cfg.model, res.cost_usd)
        self.emit("llm.call", {**base, "ok": True, "latency_ms": res.latency_ms, **res.usage,
                               "cost_usd": round(res.cost_usd, 6), "response_id": res.response_id,
                               "effort": effort if self.p.cfg.reasoning_effort else None}, agent, doc_id)
        return res

    def media_call(self, doc_id: str, purpose: str, res) -> None:
        self.cost += res.cost_usd
        self.db.add_spend(self.run_id, "meta", res.model, res.cost_usd)
        self.emit("llm.call", {"agent": "intake", "purpose": purpose, "provider": "meta", "model": res.model, "ok": True,
                               "latency_ms": res.latency_ms, "input_tokens": 0, "output_tokens": 0, "cached_tokens": 0,
                               "reasoning_tokens": 0, "cost_usd": round(res.cost_usd, 6), "response_id": ""},
                  "intake", doc_id)

    def doc_content(self, doc: dict, pages: list[int] | None = None) -> list[dict]:
        parts = model_content(doc, pages)
        if doc["kind"] == "audio":
            text = self.transcripts.get(doc["doc_id"], "(not transcribed)")
            parts.insert(0, {"type": "text", "text": f"<voice_memo filename=\"{doc['filename']}\" "
                                                     f"transcribed_by=\"Muse Voice Transcribe\">\n{text}\n</voice_memo>"})
        return parts

    async def structured(self, agent: str, doc_id: str | None, purpose: str, system: str, content: list | str,
                         name: str, schema: dict, effort: str | None, max_tokens: int = 6000) -> dict:
        messages = [self.p.instructions(system), {"role": "user", "content": content}]
        for attempt in range(2):
            res = await self.llm(agent, doc_id, purpose, messages, effort=effort, max_tokens=max_tokens,
                                 **structured_request(self.p, name, schema))
            try:
                return structured_result(res, name)
            except (ValueError, json.JSONDecodeError) as e:
                if attempt:
                    raise AgentError(f"{name}: unparseable model output ({e})") from e
                messages += [{"role": "assistant", "content": res.text or ""},
                             {"role": "user", "content": "That was not valid JSON for the schema. Reply with JSON only."}]
        raise AgentError("unreachable")

    async def tool_loop(self, agent: str, doc_id: str | None, system: str, user: list | str, tools: list[dict],
                        handlers: dict[str, Callable[[dict], Any]], terminal: str, *, effort: str | None,
                        max_turns: int = 8) -> dict:
        messages: list[dict] = [self.p.instructions(system), {"role": "user", "content": user}]
        for turn in range(max_turns):
            if turn == max_turns - 2:  # tool_choice can only be "auto" on Meta Model API, so ask in words
                messages.append({"role": "user", "content": f"You are out of steps. Call {terminal} now with your "
                                                            "best judgement; escalate if unsure."})
            res = await self.llm(agent, doc_id, "decide next step" if turn else "start", messages, tools=tools,
                                 tool_choice="auto", effort=effort, max_tokens=4096)
            if res.text.strip():
                self.emit("agent.message", {"text": res.text.strip()[:1200]}, agent, doc_id)
            calls = res.tool_calls
            if not calls:
                messages += [{"role": "assistant", "content": res.text or ""},
                             {"role": "user", "content": f"Continue with the tools; finish by calling {terminal}."}]
                continue
            messages.append({"role": "assistant", "content": res.text or None, "tool_calls": [
                {"id": c.id, "type": "function", "function": {"name": c.function.name,
                                                              "arguments": c.function.arguments or "{}"}}
                for c in calls]})

            async def run_one(c) -> tuple[Any, dict]:
                try:
                    args = json.loads(c.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                name = c.function.name
                self.emit("tool.called", {"tool": name, "args": args, "call_id": c.id}, agent, doc_id)
                handler = handlers.get(name)
                try:
                    if handler is None:
                        raise AgentError(f"unknown tool {name}")
                    out = handler(args)
                    result = await out if inspect.isawaitable(out) else out
                except (AgentError, KeyError, ValueError, TypeError, ProviderError) as e:
                    result = {"error": str(e)}
                self.emit("tool.result", {"tool": name, "call_id": c.id, "result": result,
                                          "summary": summarize(name, result)}, agent, doc_id)
                return c, result

            results = await asyncio.gather(*(run_one(c) for c in calls))
            done = None
            for c, result in results:
                messages.append({"role": "tool", "tool_call_id": c.id, "content": json.dumps(result, default=str)})
                if c.function.name == terminal and "error" not in result:
                    done = result
            if done is not None:
                return done
        raise AgentError(f"{agent} did not call {terminal} within {max_turns} turns")

    # -------------------------------------------------------- stages
    async def plan(self) -> None:
        manifest = []
        for d in self.docs:
            row = {"file": d["filename"], "type": d["kind"], "pages": d["meta"].get("pages", 0)}
            if d["kind"] == "email":
                row.update({"from": d["meta"].get("from"), "subject": d["meta"].get("subject")})
            manifest.append(row)
        try:
            plan = await self.structured("planner", None, "plan batch", planner_prompt(self.books),
                                         "Batch manifest:\n" + json.dumps(manifest, ensure_ascii=False, indent=1),
                                         "batch_plan", PLAN_SCHEMA, EFFORT["planner"], max_tokens=3000)
        except (AgentError, ProviderError) as e:
            plan = {"summary": "Default plan (planner unavailable).", "steps": [], "watchlist": [], "error": str(e)}
        self.emit("plan.created", plan, "planner")

    async def intake(self, doc: dict) -> None:
        did = doc["doc_id"]
        try:
            if doc["kind"] == "audio":
                await self.transcribe(doc)
            content = [{"type": "text", "text": f"Document file: {doc['filename']}"}] + self.doc_content(doc)
            ex = await self.structured("intake", did, "read document", intake_prompt(self.books), content,
                                       "extraction", EXTRACTION_SCHEMA, EFFORT["intake"], max_tokens=8000)
            ex.setdefault("lines", [])
            if did in self.transcripts:
                ex["transcript"] = self.transcripts[did]
            if ex.get("doc_type") == "delivery_photo" and ex.get("count_target"):
                ex["counted"] = await self.count_objects(doc, ex)
            self.books.extractions[did] = ex
            self.emit("doc.extracted", {"extraction": ex}, "intake", did)
        except (AgentError, ProviderError) as e:
            self.emit("doc.failed", {"stage": "intake", "error": str(e)[:500]}, "intake", did)

    async def transcribe(self, doc: dict) -> None:
        if not self.media:
            raise AgentError("voice memos are transcribed by Muse Voice Transcribe on Meta Model API, which private "
                             "mode does not call; a human must listen to this one")
        names = [v["name"] for v in self.books.vendors] + [self.books.buyer["name"]]
        keywords = sorted({k for n in names for k in (n, re.sub(r"\s+(GmbH|eG|UG|B\.V\.|Ltd)\.?$", "", n)) if len(k) <= 30})
        res = await self.media.transcribe(asr_wav(doc), languages=["German", "English"], keywords=keywords)
        self.media_call(doc["doc_id"], "transcribe voice memo", res)
        text = res.data.get("transcript", "")
        self.transcripts[doc["doc_id"]] = text
        self.emit("media.transcribed", {"model": res.model, "transcript": text, "turns": res.data.get("turns", []),
                                        "audio_ms": res.data.get("audioDurationMs"), "latency_ms": res.latency_ms},
                  "intake", doc["doc_id"])

    async def count_objects(self, doc: dict, ex: dict) -> dict:
        """Muse Spark decides WHAT to count; SAM 3.1 finds every instance (box + mask)."""
        phrase = str(ex["count_target"])[:60]
        if not self.media:
            return {"object": phrase, "count": int(ex.get("counted_items") or 0), "method": None, "boxes": []}
        page = page_images(doc)[0]
        res = await self.media.segment(page.read_bytes(), phrase)
        self.media_call(doc["doc_id"], f"segment + count '{phrase}'", res)
        counted = {"object": phrase, "count": res.data["count"], "boxes": res.data["boxes"], "method": res.model,
                   "model_estimate": int(ex.get("counted_items") or 0)}
        self.emit("media.segmented", {**counted, "latency_ms": res.latency_ms}, "intake", doc["doc_id"])
        return counted

    async def investigate(self, doc: dict) -> None:
        did = doc["doc_id"]
        ex = self.books.extractions.get(did)
        if ex is None:
            self.decisions[did] = {"decision": "escalate", "flags": [], "at_risk_eur": 0.0, "confidence": 0.0,
                                   "rationale": "The document could not be read automatically; a human must review it."}
            self.emit("decision.proposed", self.decisions[did], "system", did)
            return

        def tool(fn):
            accepted = set(inspect.signature(fn).parameters) - {"books", "doc_id"}

            def h(args: dict) -> dict:
                out = fn(self.books, did, **{k: v for k, v in args.items() if k in accepted and v})
                self.issues[did].extend(out.get("issues", []))
                return out
            return h

        async def reread(args: dict) -> dict:
            page = args.get("page")
            content = [{"type": "text", "text": f"Question about {doc['filename']}: {args.get('question')}"}]
            content += self.doc_content(doc, pages=[page] if page else None)
            return await self.structured("intake", did, f"re-read: {str(args.get('question'))[:80]}",
                                         "Answer the question from the document only. Quote the exact text and give "
                                         "the page and a bbox [x_min, y_min, x_max, y_max] on a 0-1000 grid.",
                                         content, "reread", REREAD_SCHEMA, "low", max_tokens=2000)

        def submit(args: dict) -> dict:
            if args.get("decision") not in ("approve", "hold", "reject", "escalate", "file"):
                return {"error": "decision must be one of approve|hold|reject|escalate|file"}
            return self._record_decision(did, args)

        ex_view = {k: v for k, v in ex.items() if k not in ("evidence", "counted")}
        if ex.get("counted"):
            ex_view["counted_by_sam"] = {k: ex["counted"][k] for k in ("object", "count", "method")}
        user = (f"doc_id: {did}\nfile: {doc['filename']} ({doc['kind']})\n"
                + (f"email from: {doc['meta'].get('from')}\nsubject: {doc['meta'].get('subject')}\n"
                   if doc["kind"] == "email" else "")
                + "Extraction (as read from the document):\n" + json.dumps(ex_view, ensure_ascii=False, indent=1))
        handlers = {"lookup_vendor": tool(lookup_vendor), "compare_to_po": tool(compare_to_po),
                    "check_vat": tool(check_vat), "detect_duplicate": tool(detect_duplicate),
                    "check_goods_receipt": tool(check_goods_receipt),
                    "reread_document": reread, "submit_decision": submit}
        try:
            await self.tool_loop("investigator", did, investigator_prompt(self.books), user, INVESTIGATOR_TOOLS,
                                 handlers, "submit_decision", effort=EFFORT["investigator"])
        except (AgentError, ProviderError) as e:
            self.decisions[did] = {"decision": "escalate", "flags": [], "at_risk_eur": 0.0, "confidence": 0.0,
                                   "rationale": f"Automatic review failed ({e}); a human must review this document."}
            self.emit("decision.proposed", self.decisions[did], "system", did)

    def _record_decision(self, did: str, args: dict) -> dict:
        ex = self.books.extractions[did]
        gross = doc_gross(ex)
        tool_issues: dict[str, dict] = {}
        for i in self.issues[did]:
            tool_issues.setdefault(i["code"], i)
        kept, seen = [], set()
        for f in args.get("flags") or []:
            code = f.get("code", "OTHER")
            if code in seen:
                continue
            seen.add(code)
            if code in tool_issues:
                kept.append({**tool_issues[code], "agent_note": f.get("message", ""), "source": "tool"})
            else:
                kept.append({"code": code, "severity": "info" if code in INFO_CODES else "warning",
                             "message": f.get("message", ""), "at_risk_eur": 0.0, "details": {}, "source": "agent"})
        dismissed = [i for c, i in tool_issues.items() if c not in seen and i["severity"] != "info"]
        decision = {"decision": args["decision"], "flags": kept, "dismissed": dismissed,
                    "at_risk_eur": combine_at_risk(kept, gross) if args["decision"] != "approve" else 0.0,
                    "gross": gross, "rationale": args.get("rationale", ""),
                    "confidence": float(args.get("confidence") or 0)}
        self.decisions[did] = decision
        self.emit("decision.proposed", decision, "investigator", did)
        return {"recorded": True, "decision": args["decision"]}

    async def verify(self, doc: dict) -> None:
        did = doc["doc_id"]
        dec = self.decisions[did]
        ex = self.books.extractions.get(did)
        if ex is None or (dec["decision"] == "file" and ex.get("doc_type") == "other"):
            final = {"verdict": "skipped", "claims": [], "overall_confidence": dec["confidence"],
                     "notes": "Nothing to verify.", "final_status": dec["decision"], "escalated": False}
            self.final[did] = {**dec, **final}
            self.emit("decision.verified", final, "verifier", did)
            return
        v, _ = match_vendor(self.books, ex, doc)
        facts = {"vendor_master": {k: v[k] for k in ("vendor_id", "name", "iban", "domain")} if v else None,
                 "tool_findings": [{"code": i["code"], "message": i["message"]} for i in self.issues[did]]}
        if ex.get("doc_type") in EVIDENCE_TYPES:
            facts["goods_receipt_link"] = check_goods_receipt(self.books, did).get("applies_to")
        key_fields = {k: ex.get(k) for k in ("doc_type", "vendor_name", "invoice_number", "issue_date", "po_number",
                                              "iban", "net_total", "vat_total", "gross_total", "notes")}
        brief = (f"PROPOSED DECISION: {dec['decision']}\nRationale: {dec['rationale']}\n"
                 f"Flags: {json.dumps([{'code': f['code'], 'message': f['message']} for f in dec['flags']], ensure_ascii=False)}\n"
                 f"Key fields as extracted: {json.dumps(key_fields, ensure_ascii=False)}\n"
                 f"Company systems (true): {json.dumps(facts, ensure_ascii=False, default=str)}")
        if ex.get("counted"):
            brief += f"\nSAM 3.1 segmentation of this photo (true): {ex['counted']['count']} x '{ex['counted']['object']}'"
        content = self.doc_content(doc) + [{"type": "text", "text": brief}]
        try:
            ver = await self.structured("verifier", did, "verify decision", verifier_prompt(self.books), content,
                                        "verification", VERIFY_SCHEMA, EFFORT["verifier"], max_tokens=6000)
        except (AgentError, ProviderError) as e:
            ver = {"verdict": "disputed", "overall_confidence": 0.0, "claims": [], "notes": f"Verifier failed: {e}"}
        conf = float(ver.get("overall_confidence") or 0)
        unsupported = [c for c in ver.get("claims", []) if not c.get("supported")]
        escalate = ver.get("verdict") == "disputed" or conf < POLICY["verify_min_confidence"]
        reason = ""
        if escalate:
            reason = (f"Verifier {ver.get('verdict')} (confidence {conf:.2f})"
                      + (f"; unsupported: {unsupported[0]['claim']}" if unsupported else ""))
        final = {**ver, "final_status": "escalate" if escalate and dec["decision"] != "escalate" else dec["decision"],
                 "escalated": bool(escalate and dec["decision"] != "escalate"), "reason": reason}
        self.final[did] = {**dec, **final}
        self.emit("decision.verified", final, "verifier", did)

    async def review(self, doc: dict) -> None:
        await self.investigate(doc)
        await self.verify(doc)

    # -------------------------------------------------------- drafting
    def _payment_items(self, doc_ids: list[str], execution_date: str | None) -> dict:
        items: dict[str, dict] = {}
        skipped = []
        for did in doc_ids:
            f = self.final.get(did)
            ex = self.books.extractions.get(did)
            if not f or not ex or f["final_status"] != "approve":
                skipped.append({"doc_id": did, "reason": f"final status is {f['final_status'] if f else 'unknown'}"})
                continue
            v, _ = match_vendor(self.books, ex, self.by_id.get(did))
            if not v:
                skipped.append({"doc_id": did, "reason": "vendor not in vendor master"})
                continue
            amount = -doc_gross(ex) if ex.get("doc_type") == "credit_note" else doc_gross(ex)
            it = items.setdefault(v["vendor_id"], {"vendor_id": v["vendor_id"], "vendor_name": v["name"],
                                                   "iban": v["iban"], "bic": v["bic"], "amount": 0.0, "doc_ids": [],
                                                   "references": [], "due_date": None})
            it["amount"] = r2(it["amount"] + amount)
            it["doc_ids"].append(did)
            it["references"].append(ex.get("invoice_number") or did)
            issued = parse_date(ex.get("issue_date"))
            if issued and ex.get("doc_type") != "credit_note":
                due = (issued + timedelta(days=v["payment_terms_days"])).isoformat()
                it["due_date"] = min(filter(None, [it["due_date"], due]))
        rows = []
        for it in items.values():
            if it["amount"] <= 0:
                skipped.append({"doc_id": ",".join(it["doc_ids"]), "reason": "credits exceed invoices for vendor"})
                continue
            it["reference"] = ("RE " + ", ".join(it.pop("references")))[:140]
            rows.append(it)
        exec_date = execution_date or _next_business_day(date.today()).isoformat()
        batch = {"execution_date": exec_date, "debtor": {"name": self.books.buyer["name"],
                                                         "iban": self.books.buyer["iban"]},
                 "items": rows, "total": r2(sum(r["amount"] for r in rows)), "skipped": skipped}
        return batch

    async def draft(self) -> None:
        rows = []
        for d in self.docs:
            did, f, ex = d["doc_id"], self.final.get(d["doc_id"]), self.books.extractions.get(d["doc_id"])
            if not f:
                continue
            v, _ = match_vendor(self.books, ex or {}, d) if ex else (None, "")
            rows.append({"doc_id": did, "file": d["filename"], "type": (ex or {}).get("doc_type"),
                         "vendor_id": v["vendor_id"] if v else None,
                         "vendor": v["name"] if v else (ex or {}).get("vendor_name"),
                         "vendor_language": v["language"] if v else None, "vendor_contact": v["contact"] if v else None,
                         "invoice_number": (ex or {}).get("invoice_number"), "gross": doc_gross(ex or {}),
                         "final_status": f["final_status"], "at_risk_eur": f.get("at_risk_eur", 0),
                         "flags": [{"code": x["code"], "message": x["message"]} for x in f.get("flags", [])],
                         "rationale": f.get("rationale"), "escalation_reason": f.get("reason") or None})

        def h_payment(args: dict) -> dict:
            batch = self._payment_items(args.get("doc_ids") or [], args.get("execution_date"))
            self.payment_batch = batch
            self.emit("draft.payment_batch", batch, "drafter")
            return {"items": len(batch["items"]), "total": batch["total"], "skipped": batch["skipped"]}

        def h_email(args: dict) -> dict:
            v = self.books.vendor(args.get("vendor_id"))
            if not v:
                return {"error": f"vendor_id {args.get('vendor_id')} is not in the vendor master; emails go only to "
                                 "known vendor contacts"}
            email = {"email_id": f"E{len(self.emails) + 1:02d}", "vendor_id": v["vendor_id"], "to": v["email"],
                     "to_name": f"{v['contact']}, {v['name']}", "subject": args.get("subject", ""),
                     "body": args.get("body", ""), "language": args.get("language", v["language"]),
                     "doc_ids": args.get("doc_ids") or [], "purpose": args.get("purpose", "")}
            self.emails.append(email)
            self.emit("draft.email", email, "drafter")
            return {"drafted": email["email_id"], "to": email["to"]}

        def h_request(args: dict) -> dict:
            if self.payment_batch is None:
                return {"error": "call draft_payment first"}
            return {"summary": args.get("summary", "")}

        user = ("Final status of every document in this batch:\n" + json.dumps(rows, ensure_ascii=False, indent=1)
                + f"\nToday is {date.today().isoformat()}.")
        summary = ""
        try:
            res = await self.tool_loop("drafter", None, drafter_prompt(self.books), user, DRAFTER_TOOLS,
                                       {"draft_payment": h_payment, "draft_email": h_email,
                                        "request_approval": h_request}, "request_approval",
                                       effort=EFFORT["drafter"], max_turns=10)
            summary = res.get("summary", "")
        except (AgentError, ProviderError) as e:
            summary = f"Drafting agent stopped early ({e}). Payment batch drafted from approved documents."
        if self.payment_batch is None:  # safety net: never leave the approver without a batch
            approved = [d for d, f in self.final.items() if f["final_status"] == "approve"]
            h_payment({"doc_ids": approved})
        self.emit("approval.requested", {"summary": summary, "payment_total": self.payment_batch["total"],
                                         "payments": len(self.payment_batch["items"]), "emails": len(self.emails)},
                  "drafter")

    # -------------------------------------------------------- orchestration
    async def execute(self) -> None:
        self.emit("run.started", {"provider": self.p.cfg.public(), "docs": [
            {"doc_id": d["doc_id"], "filename": d["filename"], "kind": d["kind"], "pages": d["meta"].get("pages", 0),
             "meta": d["meta"]} for d in self.docs]}, "system")
        try:
            self.emit("stage.started", {"stage": "plan"}, "system")
            await self.plan()
            self.emit("stage.started", {"stage": "intake"}, "system")
            await asyncio.gather(*(self.intake(d) for d in self.docs))
            self.emit("stage.started", {"stage": "review"}, "system")
            await asyncio.gather(*(self.review(d) for d in self.docs))
            self.emit("stage.started", {"stage": "draft"}, "system")
            await self.draft()
            self.emit("run.awaiting_approval", {"cost_usd": round(self.cost, 4)}, "system")
        except Exception as e:  # surfaced in the UI; the audit log keeps everything up to here
            self.emit("run.failed", {"error": f"{type(e).__name__}: {e}"}, "system")
            raise


def _next_business_day(d: date) -> date:
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def summarize(tool: str, result: dict) -> str:
    if "error" in result:
        return f"error: {result['error']}"[:200]
    codes = [i["code"] for i in result.get("issues", [])]
    flag = (" · " + ", ".join(codes)) if codes else " · no issues"
    if tool == "lookup_vendor":
        if not result.get("matched"):
            return "vendor not in master" + flag
        v = result["vendor"]
        return f"{v['vendor_id']} {v['name']} ({result['match_method']}) · IBAN {result.get('iban_check')}" + flag
    if tool == "compare_to_po":
        ref = result.get("po_number") or ", ".join(result.get("contracts") or []) or "no PO/contract"
        return f"{ref}" + flag
    if tool == "check_vat":
        return f"{len(result.get('rate_checks', []))} line rates checked" + flag
    if tool == "detect_duplicate":
        return f"{len(result.get('matches', []))} candidate match(es)" + flag
    if tool == "check_goods_receipt":
        ev = result.get("evidence") or []
        return (f"{len(ev)} receiving record(s)" if ev else (result.get("note") or "no evidence")[:90]) + flag
    if tool == "reread_document":
        return f"\"{str(result.get('answer'))[:120]}\""
    if tool == "submit_decision":
        return f"decision recorded: {result.get('decision')}"
    if tool == "draft_payment":
        return f"{result.get('items')} payments, total {result.get('total'):,.2f} EUR"
    if tool == "draft_email":
        return f"email {result.get('drafted')} to {result.get('to')}"
    return "ok"
