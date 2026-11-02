import { useEffect, useMemo, useState } from "react";
import { Bot, CheckCircle2, ChevronRight, Cpu, Download, FileSearch, ShieldCheck, Wrench, XCircle } from "lucide-react";
import { pageUrl, type RunDoc, type RunState, type Step } from "../api";
import { go } from "../App";
import { Card, Empty, FlagChip, KindIcon, StatusChip, eur, int, secs, usd } from "../components/ui";

const FILTERS = ["all", "stopped", "approve", "file"] as const;

export default function Audit({ state, docId }: { state: RunState; docId: string | null }) {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("all");
  const docs = state.docs.filter((d) =>
    filter === "all" ? true : filter === "stopped" ? ["hold", "reject", "escalate"].includes(d.final_status ?? "") : d.final_status === filter,
  );
  const selected = state.docs.find((d) => d.doc_id === docId) ?? docs[0] ?? state.docs[0];

  return (
    <div className="grid gap-5 lg:grid-cols-[280px_1fr]">
      <Card className="flex max-h-[calc(100vh-130px)] flex-col lg:sticky lg:top-24">
        <div className="flex gap-1 border-b border-line p-2">
          {FILTERS.map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`flex-1 rounded-md px-2 py-1 text-[11px] font-medium capitalize ${filter === f ? "bg-brand text-white" : "text-muted hover:bg-paper"}`}
            >
              {f === "approve" ? "approved" : f === "file" ? "filed" : f}
            </button>
          ))}
        </div>
        <div className="flex-1 overflow-y-auto p-1.5 scroll-thin">
          {docs.map((d) => (
            <button
              key={d.doc_id}
              onClick={() => go(state.run.run_id, "audit", d.doc_id)}
              className={`flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-xs ${selected?.doc_id === d.doc_id ? "bg-[#eef6f4]" : "hover:bg-paper"}`}
            >
              <span className="text-muted"><KindIcon kind={d.kind} size={12} /></span>
              <span className="min-w-0 flex-1 truncate">{d.filename}</span>
              {d.final_status && <span className={`h-2 w-2 shrink-0 rounded-full ${dot(d.final_status)}`} />}
            </button>
          ))}
        </div>
      </Card>
      {selected ? <DocAudit key={selected.doc_id} d={selected} state={state} /> : <Empty>No documents.</Empty>}
    </div>
  );
}

const dot = (s: string) =>
  ({ approve: "bg-approve", hold: "bg-hold", reject: "bg-reject", escalate: "bg-escalate", file: "bg-file" })[s] ?? "bg-line";

type Box = { bbox: number[]; label: string; ok: boolean; page: number };

function DocAudit({ d, state }: { d: RunDoc; state: RunState }) {
  const [page, setPage] = useState(1);
  const [hover, setHover] = useState<number | null>(null);
  const [emailText, setEmailText] = useState<string | null>(null);
  const ex = d.extraction;
  const dec = d.decision;
  const ver = d.verification;

  useEffect(() => {
    if (d.kind === "email") fetch(`/api/docs/${d.doc_id}/text`).then((r) => r.json()).then((j) => setEmailText(j.text));
  }, [d.doc_id, d.kind]);

  const boxes: Box[] = useMemo(() => {
    const claims = (ver?.claims ?? []).filter((c) => c.bbox?.length === 4 && c.page >= 1);
    return claims.map((c) => ({ bbox: c.bbox!, label: c.claim, ok: c.supported, page: c.page }));
  }, [ver]);
  const pageBoxes = boxes.map((b, i) => ({ ...b, i })).filter((b) => b.page === page);
  const cost = d.steps.filter((s) => s.type === "llm.call" && s.payload.ok).reduce((a, s) => a + s.payload.cost_usd, 0);

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <Card className="self-start overflow-hidden xl:sticky xl:top-24 xl:max-h-[calc(100vh-120px)] xl:overflow-y-auto scroll-thin">
        <div className="flex items-center gap-2 border-b border-line px-4 py-2.5">
          <KindIcon kind={d.kind} />
          <div className="min-w-0 flex-1 truncate text-sm font-medium">{d.filename}</div>
          {d.pages > 1 &&
            Array.from({ length: d.pages }, (_, i) => (
              <button key={i} onClick={() => setPage(i + 1)} className={`rounded px-2 text-xs ${page === i + 1 ? "bg-brand text-white" : "ring-1 ring-line"}`}>
                {i + 1}
              </button>
            ))}
          <a href={`/api/docs/${d.doc_id}/file`} className="text-muted hover:text-ink" title="Original file">
            <Download size={15} />
          </a>
        </div>
        {d.kind === "email" && (
          <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap p-4 font-mono text-xs leading-relaxed scroll-thin">{emailText ?? "…"}</pre>
        )}
        {d.pages > 0 && (
          <div className="relative bg-paper">
            <img src={pageUrl(d.doc_id, page)} alt={d.filename} className="block w-full" />
            {pageBoxes.map((b) => (
              <div
                key={b.i}
                className={`absolute rounded-sm border-2 transition ${b.ok ? "border-emerald-500 bg-emerald-400/10" : "border-red-500 bg-red-400/15"} ${
                  hover === b.i ? "ring-4 ring-amber-300/70" : ""
                }`}
                style={{
                  left: `${clamp(b.bbox[0]) / 10}%`,
                  top: `${clamp(b.bbox[1]) / 10}%`,
                  width: `${Math.max(clamp(b.bbox[2]) - clamp(b.bbox[0]), 4) / 10}%`,
                  height: `${Math.max(clamp(b.bbox[3]) - clamp(b.bbox[1]), 4) / 10}%`,
                }}
                title={b.label}
              />
            ))}
          </div>
        )}
        {boxes.length > 0 && (
          <div className="border-t border-line px-4 py-2 text-[11px] text-muted">
            Boxes: evidence located by the verifier (Muse Spark grounding, 0–1000 grid). Green = supported, red = not supported.
          </div>
        )}
      </Card>

      <div className="space-y-4">
        <Card className="p-4">
          <div className="flex flex-wrap items-center gap-2">
            <div className="text-base font-semibold">Why did it do that?</div>
            <StatusChip status={d.final_status} size="md" />
            {d.at_risk_eur > 0 && <span className="text-sm font-semibold text-amber-700 tabular">{eur(d.at_risk_eur)} at risk</span>}
            <span className="ml-auto text-xs text-muted tabular">
              {d.steps.filter((s) => s.type === "llm.call").length} model calls · {usd(cost)}
            </span>
          </div>
          {dec ? (
            <>
              <p className="mt-2 text-sm leading-relaxed">{dec.rationale}</p>
              {dec.flags.length > 0 && (
                <div className="mt-3 space-y-2">
                  {dec.flags.map((f) => (
                    <div key={f.code} className="rounded-lg bg-paper p-2.5">
                      <div className="flex items-center gap-2">
                        <FlagChip code={f.code} />
                        {f.at_risk_eur > 0 && <span className="text-xs font-semibold text-amber-700 tabular">{eur(f.at_risk_eur)}</span>}
                        <span className="ml-auto text-[10px] uppercase tracking-wide text-muted">{f.source === "tool" ? "computed by tool" : "raised by agent"}</span>
                      </div>
                      <div className="mt-1 text-xs">{f.message}</div>
                      {f.agent_note && f.agent_note !== f.message && <div className="mt-0.5 text-xs italic text-muted">Agent: {f.agent_note}</div>}
                    </div>
                  ))}
                </div>
              )}
              {(dec.dismissed?.length ?? 0) > 0 && (
                <div className="mt-2 text-xs text-muted">
                  Tool findings the agent dismissed: {dec.dismissed!.map((f) => `${f.code} (${f.message})`).join("; ")}
                </div>
              )}
            </>
          ) : (
            <p className="mt-2 text-sm text-muted">{d.error ?? "Not decided yet."}</p>
          )}
        </Card>

        {ver && ver.verdict !== "skipped" && (
          <Card className="p-4">
            <div className="flex items-center gap-2">
              <ShieldCheck size={16} className={ver.escalated ? "text-escalate" : "text-approve"} />
              <div className="text-sm font-semibold">Independent verification</div>
              <span className="text-xs text-muted">
                {ver.verdict} · confidence {Math.round(ver.overall_confidence * 100)}%
              </span>
            </div>
            {ver.escalated && <div className="mt-2 rounded-md bg-violet-50 p-2 text-xs text-escalate">Escalated to a human: {ver.reason}</div>}
            <div className="mt-2 divide-y divide-line">
              {ver.claims.map((c, i) => (
                <div
                  key={i}
                  onMouseEnter={() => {
                    setHover(boxes.findIndex((b) => b.label === c.claim));
                    if (c.page >= 1) setPage(c.page);
                  }}
                  onMouseLeave={() => setHover(null)}
                  className="flex gap-2 py-2 text-xs"
                >
                  {c.supported ? <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-approve" /> : <XCircle size={14} className="mt-0.5 shrink-0 text-reject" />}
                  <div className="min-w-0 flex-1">
                    <div>{c.claim}</div>
                    {c.quote && (
                      <div className="mt-0.5 truncate font-mono text-[11px] text-muted" title={c.quote}>
                        “{c.quote}” {c.page ? `· p.${c.page}` : "· email"}
                      </div>
                    )}
                  </div>
                  <span className="shrink-0 tabular text-muted">{Math.round(c.confidence * 100)}%</span>
                </div>
              ))}
            </div>
            {ver.notes && <div className="mt-1 text-xs text-muted">{ver.notes}</div>}
          </Card>
        )}

        {ex && <ExtractionCard d={d} />}

        <Card className="p-4">
          <div className="mb-2 text-sm font-semibold">Step-by-step audit trail</div>
          <ol className="space-y-1">
            {d.steps.map((s) => (
              <StepRow key={s.seq} s={s} provider={state.run.provider} />
            ))}
          </ol>
        </Card>
      </div>
    </div>
  );
}

const clamp = (n: number) => Math.min(Math.max(n, 0), 1000);

function ExtractionCard({ d }: { d: RunDoc }) {
  const ex = d.extraction!;
  const rows: [string, string | undefined][] = [
    ["Type", ex.doc_type],
    ["Vendor", `${ex.vendor_name}${ex.vendor_country ? ` (${ex.vendor_country})` : ""}`],
    ["VAT ID", ex.vendor_vat_id],
    ["Number", ex.invoice_number],
    ["Date", ex.issue_date],
    ["PO", ex.po_number],
    ["Period", ex.service_period],
    ["IBAN", ex.iban],
  ];
  return (
    <Card className="p-4">
      <div className="mb-2 flex items-center gap-2">
        <FileSearch size={15} className="text-brand" />
        <div className="text-sm font-semibold">What Muse Spark read</div>
        <span className="text-xs text-muted">confidence {Math.round((ex.confidence ?? 0) * 100)}%</span>
      </div>
      <dl className="grid grid-cols-[90px_1fr] gap-x-3 gap-y-1 text-xs">
        {rows
          .filter(([, v]) => v)
          .map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-muted">{k}</dt>
              <dd className="break-all font-mono">{v}</dd>
            </div>
          ))}
      </dl>
      {ex.lines.length > 0 && (
        <table className="mt-3 w-full text-xs">
          <thead className="text-left text-muted">
            <tr>
              <th className="py-1 font-medium">Line</th>
              <th className="py-1 text-right font-medium">Qty</th>
              <th className="py-1 text-right font-medium">Price</th>
              <th className="py-1 text-right font-medium">VAT</th>
              <th className="py-1 text-right font-medium">Net</th>
            </tr>
          </thead>
          <tbody>
            {ex.lines.map((l, i) => (
              <tr key={i} className="border-t border-line/70">
                <td className="py-1 pr-2">{l.description}</td>
                <td className="py-1 text-right tabular">{l.quantity}</td>
                <td className="py-1 text-right tabular">{l.unit_price}</td>
                <td className="py-1 text-right tabular">{l.vat_rate}%</td>
                <td className="py-1 text-right tabular">{eur(l.net_amount)}</td>
              </tr>
            ))}
            <tr className="border-t border-line font-medium">
              <td className="py-1" colSpan={4}>
                Net {eur(ex.net_total)} · VAT {eur(ex.vat_total)} · Total
              </td>
              <td className="py-1 text-right tabular">{eur(ex.gross_total)}</td>
            </tr>
          </tbody>
        </table>
      )}
      {ex.notes && <div className="mt-2 rounded-md bg-amber-50 p-2 text-xs text-amber-900">Noticed: {ex.notes}</div>}
    </Card>
  );
}

function StepRow({ s, provider }: { s: Step; provider?: RunState["run"]["provider"] }) {
  const [open, setOpen] = useState(false);
  const p = s.payload;
  let icon = <Cpu size={13} />;
  let text: React.ReactNode = s.type;
  let detail: unknown = null;
  if (s.type === "llm.call") {
    icon = <Cpu size={13} className={provider?.open_weights ? "text-open" : "text-meta"} />;
    text = p.ok ? (
      <>
        <span className="font-medium">{p.agent}</span> → <span className="font-mono">{p.model}</span>: {p.purpose}{" "}
        <span className="text-muted tabular">
          ({secs(p.latency_ms)}, {int(p.input_tokens)} in / {int(p.output_tokens)} out{p.reasoning_tokens ? `, ${int(p.reasoning_tokens)} reasoning` : ""}, {usd(p.cost_usd)})
        </span>
      </>
    ) : (
      <span className="text-reject">model error: {p.error}</span>
    );
    detail = p.response_id ? { response_id: p.response_id, effort: p.effort } : null;
  } else if (s.type === "tool.called") {
    icon = <ChevronRight size={13} />;
    text = (
      <>
        calls <span className="font-mono">{p.tool}</span>
        <span className="text-muted">({Object.entries(p.args ?? {}).filter(([k]) => k !== "doc_id").map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ")})</span>
      </>
    );
  } else if (s.type === "tool.result") {
    icon = <Wrench size={13} className="text-brand-2" />;
    text = (
      <>
        <span className="font-mono">{p.tool}</span> → {p.summary}
      </>
    );
    detail = p.result;
  } else if (s.type === "agent.message") {
    icon = <Bot size={13} />;
    text = <span className="italic text-muted">“{p.text}”</span>;
  } else if (s.type === "doc.extracted") {
    icon = <FileSearch size={13} />;
    text = <>extracted {p.doc_type} {p.invoice_number} from {p.vendor_name}</>;
  } else if (s.type === "decision.proposed") {
    icon = <ShieldCheck size={13} />;
    text = (
      <>
        investigator decided <span className="font-medium">{p.decision}</span> (confidence {Math.round(p.confidence * 100)}%)
      </>
    );
  } else if (s.type === "decision.verified") {
    icon = <CheckCircle2 size={13} />;
    text = <>verifier: {p.verdict}{p.escalated ? ` → escalated (${p.reason})` : ""}</>;
  }
  return (
    <li className="text-xs">
      <button onClick={() => detail && setOpen(!open)} className={`flex w-full gap-2 rounded px-1.5 py-1 text-left ${detail ? "hover:bg-paper" : "cursor-default"}`}>
        <span className="mt-0.5 shrink-0 text-muted">{icon}</span>
        <span className="min-w-0 flex-1 break-words">{text}</span>
        <span className="shrink-0 font-mono text-[10px] text-muted">{new Date(s.ts * 1000).toLocaleTimeString()}</span>
      </button>
      {open && detail ? (
        <pre className="ml-6 mt-1 max-h-72 overflow-auto rounded-md bg-ink p-2 font-mono text-[10.5px] leading-relaxed text-emerald-100 scroll-thin">
          {JSON.stringify(detail, null, 2)}
        </pre>
      ) : null}
    </li>
  );
}
