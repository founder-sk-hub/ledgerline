import { useMemo, useState } from "react";
import { AlertTriangle, ArrowRight, Bot, CheckCircle2, ClipboardList, Cpu, Eye, FileSearch, Mic, ScanSearch, ShieldCheck, Wrench } from "lucide-react";
import type { RunDoc, RunEvent, RunState } from "../api";
import { go } from "../App";
import { Card, FlagChip, KindIcon, Stat, StatusChip, eur, int, secs, usd } from "../components/ui";

const STAGES = [
  { key: "plan", label: "Plan", icon: ClipboardList },
  { key: "intake", label: "Read documents", icon: FileSearch },
  { key: "review", label: "Investigate + verify", icon: ShieldCheck },
  { key: "draft", label: "Draft batch + emails", icon: Bot },
  { key: "approval", label: "Human approval", icon: CheckCircle2 },
];

export default function LiveRun({ state, events }: { state: RunState; events: RunEvent[] }) {
  const m = state.metrics;
  const read = state.docs.filter((d) => d.extraction || d.status === "failed").length;
  const decided = state.docs.filter((d) => d.final_status).length;
  const stageIdx =
    state.run.status === "awaiting_approval" || state.run.status === "completed"
      ? 4
      : STAGES.findIndex((s) => s.key === state.stage);
  const running = state.run.status === "running";

  return (
    <div className="space-y-5">
      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          {STAGES.map((s, i) => {
            const done = i < stageIdx || state.run.status === "completed";
            const active = i === stageIdx && state.run.status !== "completed";
            return (
              <div key={s.key} className="flex items-center gap-2">
                <div
                  className={`flex h-8 w-8 items-center justify-center rounded-full ${
                    done ? "bg-brand text-white" : active ? "bg-gold text-ink" : "bg-paper text-muted ring-1 ring-line"
                  }`}
                >
                  <s.icon size={15} className={active && running ? "pulse-dot" : ""} />
                </div>
                <div className={`text-sm ${active ? "font-semibold" : done ? "" : "text-muted"}`}>{s.label}</div>
                {i < STAGES.length - 1 && <div className="hidden h-px w-8 bg-line xl:block" />}
              </div>
            );
          })}
          <div className="ml-auto text-xs text-muted">
            {running ? <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-gold pulse-dot" /> running</span> : state.run.status.replace("_", " ")}
          </div>
        </div>
        {state.run.status === "awaiting_approval" && (
          <div className="slide-in mt-4 flex flex-wrap items-center gap-3 rounded-lg bg-[#fff8e8] p-3 ring-1 ring-amber-200">
            <AlertTriangle size={18} className="text-hold" />
            <div className="text-sm">
              <span className="font-semibold">The agent stopped for your approval.</span> {state.approval_items.length} items to decide:{" "}
              {m.payments} payments ({eur(m.eur_payment_batch)}), {m.emails} vendor emails,{" "}
              {state.approval_items.filter((i) => i.kind === "escalation").length} escalations. Nothing has been paid or sent.
            </div>
            <button onClick={() => go(state.run.run_id, "approvals")} className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-brand px-3 py-1.5 text-sm font-semibold text-white">
              Review <ArrowRight size={14} />
            </button>
          </div>
        )}
        {state.run.status === "failed" && <div className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-reject">Run failed: {state.run.error}</div>}
      </Card>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="Documents read" value={`${read}/${state.docs.length}`} sub={`${decided} decided`} />
        <Stat label="EUR at risk caught" value={eur(m.eur_at_risk, 0)} sub={`${m.flagged_documents} held, rejected or escalated`} tone="gold" />
        <Stat label="Payment batch" value={eur(m.eur_payment_batch, 0)} sub={`${m.payments} payments drafted`} />
        <Stat label="Model calls" value={int(m.llm_calls)} sub={`${int(m.input_tokens + m.output_tokens)} tokens`} />
        <Stat label="Model cost" value={usd(m.cost_usd)} sub={m.processed ? `${usd(m.cost_usd / Math.max(m.processed, 1))} per document` : "–"} />
        <Stat label="Avg latency" value={secs(m.avg_latency_ms)} sub={`p95 ${secs(m.p95_latency_ms)}`} />
      </div>

      {state.plan && <PlanCard plan={state.plan} />}

      <div className="grid gap-5 xl:grid-cols-[1fr_460px]">
        <div>
          <div className="mb-2 text-sm font-semibold">Documents</div>
          <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 2xl:grid-cols-3">
            {state.docs.map((d) => (
              <DocCard key={d.doc_id} d={d} runId={state.run.run_id} />
            ))}
          </div>
        </div>
        <Timeline events={events} state={state} />
      </div>
    </div>
  );
}

function PlanCard({ plan }: { plan: NonNullable<RunState["plan"]> }) {
  const [open, setOpen] = useState(false);
  return (
    <Card className="p-4">
      <div className="flex items-start gap-3">
        <ClipboardList size={18} className="mt-0.5 text-brand" />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold">Agent plan</div>
          <div className="text-sm text-muted">{plan.summary}</div>
          {plan.watchlist.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {plan.watchlist.slice(0, open ? 99 : 5).map((w) => (
                <span key={w.filename} className="rounded-md bg-amber-50 px-2 py-0.5 text-[11px] text-amber-900" title={w.reason}>
                  <Eye size={10} className="mr-1 inline" />
                  {w.filename}
                </span>
              ))}
            </div>
          )}
          {open && (
            <ol className="mt-3 space-y-1.5 text-sm">
              {plan.steps.map((s, i) => (
                <li key={i}>
                  <span className="font-medium">{i + 1}. {s.title}</span> <span className="text-muted">{s.detail}</span>
                </li>
              ))}
              {plan.watchlist.map((w) => (
                <li key={w.filename} className="text-xs text-muted">
                  <span className="font-mono">{w.filename}</span>: {w.reason}
                </li>
              ))}
            </ol>
          )}
        </div>
        <button onClick={() => setOpen(!open)} className="text-xs font-medium text-brand-2">
          {open ? "less" : "full plan"}
        </button>
      </div>
    </Card>
  );
}

function DocCard({ d, runId }: { d: RunDoc; runId: string }) {
  const ex = d.extraction;
  const working = !d.final_status && d.status !== "queued" && d.status !== "failed";
  return (
    <button
      onClick={() => go(runId, "audit", d.doc_id)}
      className={`slide-in rounded-xl border bg-white p-3 text-left transition hover:shadow-sm ${
        d.final_status && d.final_status !== "approve" && d.final_status !== "file" ? "border-amber-200" : "border-line"
      }`}
    >
      <div className="flex items-center gap-2">
        <span className="text-muted"><KindIcon kind={d.kind} /></span>
        <span className="truncate text-xs font-medium" title={d.filename}>{d.filename}</span>
        <span className="ml-auto shrink-0">
          {d.final_status ? (
            <StatusChip status={d.final_status} />
          ) : (
            <span className="text-[11px] text-muted">{working ? <span className="pulse-dot">{d.status}…</span> : d.status}</span>
          )}
        </span>
      </div>
      {ex ? (
        <div className="mt-1.5 flex items-baseline justify-between gap-2 text-xs">
          <span className="truncate text-muted">
            {ex.vendor_name} · <span className="font-mono">{ex.invoice_number}</span>
          </span>
          <span className="tabular font-medium">{ex.gross_total ? eur(ex.gross_total) : ex.doc_type}</span>
        </div>
      ) : (
        <div className="mt-2 h-3 w-2/3 rounded bg-paper" />
      )}
      {d.decision && d.decision.flags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {d.decision.flags.map((f) => (
            <FlagChip key={f.code} code={f.code} />
          ))}
          {d.at_risk_eur > 0 && <span className="ml-auto text-[11px] font-semibold tabular text-amber-700">{eur(d.at_risk_eur)}</span>}
        </div>
      )}
      {d.verification?.escalated && <div className="mt-1.5 text-[11px] text-escalate">Verifier escalated: {d.verification.reason}</div>}
    </button>
  );
}

const FILTERS = [
  { key: "all", label: "All" },
  { key: "model", label: "Model calls" },
  { key: "tools", label: "Tools" },
  { key: "decisions", label: "Decisions" },
] as const;

function Timeline({ events, state }: { events: RunEvent[]; state: RunState }) {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["key"]>("all");
  const names = useMemo(() => Object.fromEntries(state.docs.map((d) => [d.doc_id, d.filename])), [state.docs]);
  const shown = events
    .filter((e) => e.type !== "tool.called" && e.type !== "run.started")
    .filter((e) =>
      filter === "all"
        ? true
        : filter === "model"
          ? e.type === "llm.call"
          : filter === "tools"
            ? e.type === "tool.result"
            : e.type.startsWith("decision") || e.type.startsWith("draft") || e.type.startsWith("approval"),
    )
    .slice(-400)
    .reverse();
  return (
    <Card className="flex max-h-[calc(100vh-140px)] flex-col xl:sticky xl:top-24">
      <div className="flex items-center gap-2 border-b border-line px-4 py-3">
        <div className="text-sm font-semibold">Agent timeline</div>
        <div className="ml-auto flex gap-1">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={`rounded-md px-2 py-0.5 text-[11px] ${filter === f.key ? "bg-brand text-white" : "text-muted hover:bg-paper"}`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>
      <div className="flex-1 space-y-1 overflow-y-auto p-3 scroll-thin">
        {shown.length === 0 && <div className="p-6 text-center text-xs text-muted">Waiting for the first step…</div>}
        {shown.map((e) => (
          <TimelineRow key={e.seq} e={e} doc={e.doc_id ? names[e.doc_id] : undefined} provider={state.run.provider} />
        ))}
      </div>
    </Card>
  );
}

function TimelineRow({ e, doc, provider }: { e: RunEvent; doc?: string; provider?: RunState["run"]["provider"] }) {
  const p = e.payload;
  const time = new Date(e.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  let icon = <Cpu size={13} />;
  let body: React.ReactNode = e.type;
  let tone = "";
  switch (e.type) {
    case "llm.call":
      icon = <Cpu size={13} className={provider?.open_weights ? "text-open" : "text-meta"} />;
      body = p.ok ? (
        <>
          <span className={`mr-1 rounded px-1 font-mono text-[10px] text-white ${provider?.open_weights ? "bg-open" : "bg-meta"}`}>{p.model}</span>
          <span className="font-medium">{p.agent}</span> · {p.purpose}
          <span className="ml-1 text-muted tabular">
            · {secs(p.latency_ms)} · {int(p.input_tokens)}→{int(p.output_tokens)} tok · {usd(p.cost_usd)}
          </span>
        </>
      ) : (
        <span className="text-reject">model error ({p.agent}): {p.error}</span>
      );
      break;
    case "media.transcribed":
      icon = <Mic size={13} className="text-meta" />;
      body = (
        <>
          <span className="mr-1 rounded bg-meta px-1 font-mono text-[10px] text-white">{p.model}</span>
          heard {Math.round((p.audio_ms ?? 0) / 1000)} s of audio: <span className="italic text-muted">“{String(p.transcript).slice(0, 160)}…”</span>
        </>
      );
      break;
    case "media.segmented":
      tone = "bg-sky-50/70";
      icon = <ScanSearch size={13} className="text-meta" />;
      body = (
        <>
          <span className="mr-1 rounded bg-meta px-1 font-mono text-[10px] text-white">{p.method}</span>
          segmented and counted <span className="font-semibold">{p.count} × “{p.object}”</span>
          {p.model_estimate ? <span className="text-muted"> (the reading model's own estimate: {p.model_estimate})</span> : null}
        </>
      );
      break;
    case "tool.result":
      icon = <Wrench size={13} className="text-brand-2" />;
      body = (
        <>
          <span className="font-mono text-[11px] font-medium">{p.tool}</span> <span className="text-muted">→ {p.summary}</span>
        </>
      );
      break;
    case "agent.message":
      icon = <Bot size={13} />;
      body = <span className="italic text-muted">“{String(p.text).slice(0, 220)}”</span>;
      break;
    case "doc.extracted":
      icon = <FileSearch size={13} className="text-brand" />;
      body = (
        <>
          Read <span className="font-medium">{p.extraction.doc_type}</span> from {p.extraction.vendor_name}{" "}
          {p.extraction.gross_total ? <span className="tabular">· {eur(p.extraction.gross_total)}</span> : null}
          <span className="text-muted"> · confidence {Math.round((p.extraction.confidence ?? 0) * 100)}%</span>
        </>
      );
      break;
    case "decision.proposed":
      tone = p.decision === "approve" || p.decision === "file" ? "" : "bg-amber-50/60";
      icon = <ShieldCheck size={13} />;
      body = (
        <span className="inline-flex flex-wrap items-center gap-1">
          Decision <StatusChip status={p.decision} />
          {p.flags.map((f: { code: string }) => (
            <FlagChip key={f.code} code={f.code} />
          ))}
          {p.at_risk_eur > 0 && <span className="font-semibold text-amber-700 tabular">{eur(p.at_risk_eur)} at risk</span>}
        </span>
      );
      break;
    case "decision.verified":
      icon = <CheckCircle2 size={13} className={p.escalated ? "text-escalate" : "text-approve"} />;
      body = p.escalated ? (
        <span className="text-escalate">Second pass escalated to a human: {p.reason}</span>
      ) : p.verdict === "skipped" ? (
        <span className="text-muted">No second pass needed ({p.notes || "nothing to check"})</span>
      ) : p.verdict === "disputed" ? (
        <span className="text-escalate">Second pass disputed it; already with a human</span>
      ) : (
        <>
          Second pass confirmed it against the source ({p.claims?.length ?? 0} claims, confidence {Math.round((p.overall_confidence ?? 0) * 100)}%)
        </>
      );
      break;
    case "plan.created":
      icon = <ClipboardList size={13} />;
      body = <>Plan ready · {p.steps?.length ?? 0} steps · {p.watchlist?.length ?? 0} files on the watchlist</>;
      break;
    case "stage.started":
      return (
        <div className="py-1.5 text-center text-[11px] font-semibold uppercase tracking-wider text-muted">
          — {STAGES.find((s) => s.key === p.stage)?.label ?? p.stage} —
        </div>
      );
    case "draft.payment_batch":
      icon = <Bot size={13} />;
      body = <>Drafted payment batch: {p.items.length} payments, {eur(p.total)}</>;
      break;
    case "draft.email":
      icon = <Bot size={13} />;
      body = <>Drafted email to {p.to_name}: “{p.subject}”</>;
      break;
    case "approval.requested":
      tone = "bg-[#fff8e8]";
      icon = <AlertTriangle size={13} className="text-hold" />;
      body = <span className="font-medium">Stopped for human approval.</span>;
      break;
    case "approval.decided":
      icon = <CheckCircle2 size={13} />;
      body = <>Human {p.decision} {p.item}</>;
      break;
    case "run.executed":
      icon = <CheckCircle2 size={13} className="text-approve" />;
      body = <>Executed: SEPA file with {p.payments.length} payments ({eur(p.total)}), {p.emails_queued.length} emails in outbox</>;
      break;
    case "doc.failed":
      tone = "bg-red-50";
      body = <span className="text-reject">Could not read: {p.error}</span>;
      break;
    case "run.awaiting_approval":
    case "run.failed":
      return null;
  }
  return (
    <div className={`slide-in flex gap-2 rounded-md px-2 py-1.5 text-xs leading-relaxed ${tone}`}>
      <span className="mt-0.5 shrink-0 text-muted">{icon}</span>
      <div className="min-w-0 flex-1">
        {doc && <div className="truncate text-[10px] text-muted">{doc}</div>}
        <div className="break-words">{body}</div>
      </div>
      <span className="shrink-0 font-mono text-[10px] text-muted">{time}</span>
    </div>
  );
}
