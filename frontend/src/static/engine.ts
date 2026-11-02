/**
 * In-browser port of backend/ledgerline/{state,execution}.py for the static demo build
 * (VITE_STATIC=1). Replays recorded runs, folds events, scores the benchmark, runs the
 * approval gate and writes the SEPA file, all client-side. Keep in sync with the Python.
 */
import type { ApprovalItem, RunEvent, RunState } from "../api";

const OPEN = new Set(["hold", "reject", "escalate"]);
const POLICY = { manual_minutes_per_document: 8.0, review_minutes_per_flag: 1.5 };
const SLIM_STEPS = new Set([
  "llm.call", "tool.called", "tool.result", "agent.message", "doc.extracted", "decision.proposed",
  "decision.verified", "doc.failed", "media.transcribed", "media.segmented",
]);

type Any = any; // eslint-disable-line @typescript-eslint/no-explicit-any
const r2 = (x: number) => Math.round((x + Number.EPSILON) * 100) / 100;
const mean = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / xs.length;

export type RunMeta = { run_id: string; batch_id: string; mode: string; provider: string; created_at: number; replay_of: string | null };

export function fold(run: RunMeta, events: RunEvent[]): RunState {
  const st: Any = {
    run: { ...run, status: "running", error: null, started_at: null, ended_at: null },
    stage: null, stages: [], plan: null, docs: {}, order: [], payment_batch: null, emails: [], approval: null,
    approvals: {}, executed: null, system: [], last_seq: 0,
  };
  const llm: Any[] = [];
  for (const ev of events) {
    const t = ev.type, p = ev.payload, did = ev.doc_id;
    st.last_seq = ev.seq;
    const doc = did ? st.docs[did] : null;
    if (t === "run.started") {
      st.run.started_at = ev.ts;
      st.run.provider = p.provider;
      if (p.replay) st.run.replay = p.replay;
      for (const d of p.docs) {
        st.docs[d.doc_id] = { ...d, status: "queued", extraction: null, decision: null, verification: null,
          final_status: null, at_risk_eur: 0, steps: [] };
        st.order.push(d.doc_id);
      }
    } else if (t === "stage.started") {
      st.stage = p.stage;
      st.stages.push({ stage: p.stage, ts: ev.ts });
      for (const d of Object.values(st.docs) as Any[]) {
        if (p.stage === "intake") d.status = "reading";
        if (p.stage === "review" && d.status === "extracted") d.status = "investigating";
      }
    } else if (t === "plan.created") st.plan = p;
    else if (t === "doc.extracted" && doc) { doc.extraction = p.extraction; doc.status = "extracted"; }
    else if (t === "doc.failed" && doc) { doc.status = "failed"; doc.error = p.error; }
    else if (t === "decision.proposed" && doc) { doc.decision = p; doc.status = "verifying"; }
    else if (t === "decision.verified" && doc) {
      doc.verification = p;
      doc.final_status = p.final_status;
      doc.at_risk_eur = p.final_status !== "approve" ? doc.decision?.at_risk_eur ?? 0 : 0;
      doc.status = "done";
    } else if (t === "draft.payment_batch") st.payment_batch = p;
    else if (t === "draft.email") st.emails = [...st.emails.filter((e: Any) => e.email_id !== p.email_id), p];
    else if (t === "approval.requested") st.approval = { ...p, ts: ev.ts };
    else if (t === "run.awaiting_approval") { st.run.status = "awaiting_approval"; st.run.ended_at = ev.ts; }
    else if (t === "approval.decided") st.approvals[p.item] = p;
    else if (t === "run.executed") { st.executed = p; st.run.status = "completed"; }
    else if (t === "run.failed") { st.run.status = "failed"; st.run.error = p.error; st.run.ended_at = ev.ts; }

    if (t === "llm.call") llm.push({ ...p, ts: ev.ts, doc_id: did });
    const step = { seq: ev.seq, ts: ev.ts, type: t, agent: ev.agent, payload: slim(t, p) };
    if (doc && SLIM_STEPS.has(t)) doc.steps.push(step);
    else if (!did && ["llm.call", "tool.called", "tool.result", "agent.message"].includes(t)) st.system.push(step);
  }
  st.docs = st.order.map((d: string) => st.docs[d]);
  delete st.order;
  st.metrics = metrics(st, llm);
  return st as RunState;
}

function slim(t: string, p: Any) {
  if (t !== "doc.extracted") return p;
  const ex = p.extraction;
  return { doc_type: ex.doc_type, vendor_name: ex.vendor_name, invoice_number: ex.invoice_number, gross_total: ex.gross_total };
}

function metrics(st: Any, calls: Any[]) {
  const docs = st.docs as Any[];
  const done = docs.filter((d) => d.final_status);
  const flagged = done.filter((d) => OPEN.has(d.final_status));
  const by_status: Record<string, number> = {}, by_type: Record<string, number> = {}, flags: Record<string, number> = {};
  for (const d of done) {
    by_status[d.final_status] = (by_status[d.final_status] ?? 0) + 1;
    const typ = d.extraction?.doc_type ?? "unreadable";
    by_type[typ] = (by_type[typ] ?? 0) + 1;
    for (const f of d.decision?.flags ?? []) flags[f.code] = (flags[f.code] ?? 0) + 1;
  }
  const ok = calls.filter((c) => c.ok);
  const lat = ok.map((c) => c.latency_ms as number);
  const by_agent: Record<string, Any> = {};
  for (const c of ok) {
    const a = (by_agent[c.agent] ??= { calls: 0, cost_usd: 0, latency_ms: 0 });
    a.calls += 1; a.cost_usd += c.cost_usd; a.latency_ms += c.latency_ms;
  }
  for (const a of Object.values(by_agent)) {
    a.avg_latency_ms = Math.trunc(a.latency_ms / Math.max(a.calls, 1));
    delete a.latency_ms;
    a.cost_usd = Math.round(a.cost_usd * 1e4) / 1e4;
  }
  let wall = (st.run.ended_at ?? (st.stages.length ? st.stages[st.stages.length - 1].ts : 0)) - (st.run.started_at ?? 0);
  if (st.run.replay?.wall_seconds) wall = st.run.replay.wall_seconds;
  const manual = docs.length * POLICY.manual_minutes_per_document;
  const review = flagged.length * POLICY.review_minutes_per_flag + 0.1 * done.length;
  const verified = done.map((d) => d.verification).filter((v) => v && v.verdict !== "skipped");
  const pay = st.payment_batch ?? {};
  const sorted = [...lat].sort((a, b) => a - b);
  const sum = (k: string) => ok.reduce((s, c) => s + (c[k] ?? 0), 0);
  return {
    documents: docs.length, processed: done.length, by_status, by_type, flags, flagged_documents: flagged.length,
    eur_at_risk: r2(flagged.reduce((s, d) => s + d.at_risk_eur, 0)),
    eur_payment_batch: pay.total ?? 0, payments: (pay.items ?? []).length, emails: st.emails.length,
    llm_calls: calls.length, llm_errors: calls.length - ok.length,
    input_tokens: sum("input_tokens"), output_tokens: sum("output_tokens"), reasoning_tokens: sum("reasoning_tokens"),
    cost_usd: Math.round(sum("cost_usd") * 1e4) / 1e4,
    avg_latency_ms: lat.length ? Math.trunc(mean(lat)) : 0,
    p95_latency_ms: lat.length ? Math.trunc(sorted[Math.trunc(0.95 * (lat.length - 1))]) : 0,
    by_agent, models: [...new Set(ok.map((c) => c.model as string))].sort(),
    wall_seconds: Math.round(Math.max(wall, 0) * 10) / 10,
    manual_minutes: manual, human_review_minutes: Math.round(review * 10) / 10,
    minutes_saved: Math.round(Math.max(manual - review, 0) * 10) / 10, assumptions: POLICY,
    verified: verified.length, verifier_confirmed: verified.filter((v) => v.verdict === "confirmed").length,
    verifier_escalations: done.filter((d) => d.verification?.escalated).length,
    avg_verifier_confidence: verified.length ? Math.round(mean(verified.map((v) => Number(v.overall_confidence) || 0)) * 1000) / 1000 : null,
  };
}

export function evaluate(st: RunState, truthDocs: Any[]): RunState["evaluation"] {
  if (st.run.batch_id !== "sample") return null;
  const truth: Record<string, Any> = Object.fromEntries(truthDocs.map((t) => [t.filename, t]));
  let tp = 0, fp = 0, fn = 0, ok = 0;
  const rows: Any[] = [];
  for (const d of st.docs) {
    const t = truth[d.filename];
    if (!t || !d.final_status) continue;
    const expected = new Set<string>(t.flags);
    const got = new Set<string>((d.decision?.flags ?? []).map((f) => f.code));
    if (got.has("VAT_ARITHMETIC") && expected.has("ARITHMETIC")) { got.delete("VAT_ARITHMETIC"); got.add("ARITHMETIC"); }
    tp += [...expected].filter((x) => got.has(x)).length;
    fp += [...got].filter((x) => !expected.has(x)).length;
    fn += [...expected].filter((x) => !got.has(x)).length;
    const decision_ok = d.final_status === t.decision || (OPEN.has(t.decision) && OPEN.has(d.final_status));
    ok += decision_ok ? 1 : 0;
    rows.push({ filename: d.filename, expected_flags: [...expected].sort(), flags: [...got].sort(),
      expected_decision: t.decision, decision: d.final_status, decision_ok });
  }
  const present = new Set(rows.map((r) => r.filename));
  const round3 = (x: number) => Math.round(x * 1000) / 1000;
  return {
    documents: rows.length,
    flag_precision: tp + fp ? round3(tp / (tp + fp)) : null,
    flag_recall: tp + fn ? round3(tp / (tp + fn)) : null,
    decision_accuracy: rows.length ? round3(ok / rows.length) : null,
    anomalous_documents: truthDocs.filter((t) => present.has(t.filename) && t.flags.length && OPEN.has(t.decision)).length,
    anomalous_documents_stopped: rows.filter((r) => OPEN.has(r.expected_decision) && OPEN.has(r.decision)).length,
    eur_at_risk_planted: r2(truthDocs.filter((t) => present.has(t.filename)).reduce((s, t) => s + (t.at_risk ?? 0), 0)),
    rows,
  };
}

export function approvalItems(st: RunState): ApprovalItem[] {
  const items: ApprovalItem[] = [];
  for (const it of st.payment_batch?.items ?? []) items.push({ item: `pay:${it.vendor_id}`, kind: "payment", decision: "pending", payload: it });
  for (const e of st.emails) items.push({ item: `email:${e.email_id}`, kind: "email", decision: "pending", payload: e });
  for (const d of st.docs) {
    if (d.final_status === "escalate")
      items.push({ item: `doc:${d.doc_id}`, kind: "escalation", decision: "pending", payload: {
        doc_id: d.doc_id, filename: d.filename, decision: d.decision, verification: d.verification, extraction: d.extraction } });
  }
  for (const i of items) i.decision = st.approvals[i.item]?.decision ?? "pending";
  return items;
}

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

export function buildExecution(st: RunState, runId: string) {
  const payments: Any[] = [];
  for (const i of approvalItems(st)) {
    if (i.decision !== "approved") continue;
    if (i.kind === "payment") payments.push({ ...i.payload, approved_by: "human approver" });
    // Exception review never adds extracted bank details to the payment export.
  }
  const emails = approvalItems(st).filter((i) => i.kind === "email" && i.decision === "approved")
    .map((i) => ({ email_id: i.payload.email_id, to: i.payload.to, subject: i.payload.subject }));
  const total = r2(payments.reduce((s, p) => s + p.amount, 0));
  const xml = payments.length ? sepaXml(runId, st.payment_batch?.debtor ?? { name: "", iban: "" }, st.payment_batch?.execution_date ?? "", payments) : null;
  return {
    result: { payments, total, sepa_file: xml ? "pain001.xml" : null, emails_queued: emails,
      note: "Nothing was transmitted: in this browser demo the SEPA file is generated locally for download." },
    xml,
  };
}

function sepaXml(runId: string, debtor: { name: string; iban: string }, date: string, payments: Any[]) {
  const now = new Date().toISOString().slice(0, 19);
  const msgId = `LL-${runId.slice(0, 12)}-${Math.floor(Date.now() / 1000)}`;
  const total = r2(payments.reduce((s, p) => s + p.amount, 0)).toFixed(2);
  const tx = payments.map((p, i) => `      <CdtTrfTxInf>
        <PmtId><EndToEndId>${esc(msgId)}-${String(i + 1).padStart(3, "0")}</EndToEndId></PmtId>
        <Amt><InstdAmt Ccy="EUR">${p.amount.toFixed(2)}</InstdAmt></Amt>
        ${p.bic ? `<CdtrAgt><FinInstnId><BICFI>${esc(p.bic)}</BICFI></FinInstnId></CdtrAgt>` : ""}
        <Cdtr><Nm>${esc(String(p.vendor_name).slice(0, 70))}</Nm></Cdtr>
        <CdtrAcct><Id><IBAN>${esc(p.iban)}</IBAN></Id></CdtrAcct>
        <RmtInf><Ustrd>${esc(String(p.reference).slice(0, 140))}</Ustrd></RmtInf>
      </CdtTrfTxInf>`).join("\n");
  return `<?xml version="1.0" encoding="UTF-8"?>
<!-- Generated by Ledgerline from a human-approved batch. SYNTHETIC demo data - do not upload to a bank. -->
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.09">
  <CstmrCdtTrfInitn>
    <GrpHdr>
      <MsgId>${esc(msgId)}</MsgId><CreDtTm>${now}</CreDtTm>
      <NbOfTxs>${payments.length}</NbOfTxs><CtrlSum>${total}</CtrlSum>
      <InitgPty><Nm>${esc(debtor.name)}</Nm></InitgPty>
    </GrpHdr>
    <PmtInf>
      <PmtInfId>${esc(msgId)}-1</PmtInfId><PmtMtd>TRF</PmtMtd>
      <NbOfTxs>${payments.length}</NbOfTxs><CtrlSum>${total}</CtrlSum>
      <PmtTpInf><SvcLvl><Cd>SEPA</Cd></SvcLvl></PmtTpInf>
      <ReqdExctnDt><Dt>${esc(date)}</Dt></ReqdExctnDt>
      <Dbtr><Nm>${esc(debtor.name)}</Nm></Dbtr>
      <DbtrAcct><Id><IBAN>${esc(debtor.iban)}</IBAN></Id></DbtrAcct>
      <DbtrAgt><FinInstnId><Othr><Id>NOTPROVIDED</Id></Othr></FinInstnId></DbtrAgt>
      <ChrgBr>SLEV</ChrgBr>
${tx}
    </PmtInf>
  </CstmrCdtTrfInitn>
</Document>
`;
}
