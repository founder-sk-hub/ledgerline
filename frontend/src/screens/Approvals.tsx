import { useState } from "react";
import { Check, ChevronDown, Download, Mail, ShieldAlert, X } from "lucide-react";
import { api, exportUrl, type ApprovalItem, type Email, type PaymentItem, type RunState } from "../api";
import { go } from "../App";
import { Card, Empty, FlagChip, eur } from "../components/ui";

export default function Approvals({ state, reload }: { state: RunState; reload: () => Promise<unknown> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const runId = state.run.run_id;
  const items = state.approval_items;
  const locked = state.run.status !== "awaiting_approval";

  if (!state.approval) {
    return <Empty>The agent hasn't reached the approval gate yet. Drafts appear here after review; unresolved documents remain exceptions.</Empty>;
  }

  const decide = async (item: string, decision: "approved" | "rejected") => {
    setError(null);
    try {
      await api.approve(runId, item, decision);
      await reload();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const decideAll = async (kind: ApprovalItem["kind"]) => {
    setBusy(true);
    setError(null);
    try {
      for (const i of items.filter((x) => x.kind === kind && x.decision === "pending")) await api.approve(runId, i.item, "approved");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      await reload();
      setBusy(false);
    }
  };
  const execute = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.execute(runId);
      await reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const payments = items.filter((i) => i.kind === "payment");
  const emails = items.filter((i) => i.kind === "email");
  const escalations = items.filter((i) => i.kind === "escalation");
  const pending = items.filter((i) => i.decision === "pending").length;
  const approvedTotal = payments.filter((p) => p.decision === "approved").reduce((s, p) => s + (p.payload as PaymentItem).amount, 0);

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="min-w-0 space-y-5">
        <Card className="p-4">
          <div className="text-xs font-medium uppercase tracking-wide text-muted">Batch ready for review</div>
          <p className="mt-1 text-sm leading-relaxed">
            {payments.length} proposed payments totalling {eur(state.payment_batch?.total ?? 0)}, {emails.length} email drafts,
            and {escalations.length} exceptions. {eur(state.metrics.eur_at_risk)} flagged as at risk.
            Exceptions stay outside the payment export.
          </p>
          <details className="mt-2 text-xs text-muted">
            <summary className="cursor-pointer">Original model summary · may contain mistakes</summary>
            <p className="mt-2 whitespace-pre-line">{state.approval.summary}</p>
          </details>
        </Card>

        <Section
          title={`Payment batch · ${payments.length} payments · ${eur(state.payment_batch?.total ?? 0)}`}
          subtitle={`SEPA credit transfer from ${state.payment_batch?.debtor.name}, execution ${state.payment_batch?.execution_date}. Always paid to the IBAN in your vendor master, never to one printed on a document.`}
          action={!locked && payments.some((p) => p.decision === "pending") ? <BulkButton onClick={() => decideAll("payment")} busy={busy} label="Approve all payments" /> : null}
        >
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted">
                <tr className="border-b border-line">
                  <th className="py-2 pr-3 font-medium">Vendor</th>
                  <th className="py-2 pr-3 font-medium">Reference</th>
                  <th className="py-2 pr-3 font-medium">IBAN (vendor master)</th>
                  <th className="py-2 pr-3 font-medium">Due</th>
                  <th className="py-2 pr-3 text-right font-medium">Amount</th>
                  <th className="py-2 text-right font-medium">Decision</th>
                </tr>
              </thead>
              <tbody>
                {payments.map((i) => {
                  const p = i.payload as PaymentItem;
                  return (
                    <tr key={i.item} className="border-b border-line/70 last:border-0">
                      <td className="py-2 pr-3 font-medium">{p.vendor_name}</td>
                      <td className="py-2 pr-3 text-xs">
                        {p.doc_ids.map((d, k) => (
                          <button key={d} onClick={() => go(runId, "audit", d)} className="mr-1 font-mono text-brand-2 hover:underline">
                            {p.reference.replace(/^RE /, "").split(", ")[k] ?? d}
                          </button>
                        ))}
                      </td>
                      <td className="py-2 pr-3 font-mono text-xs text-muted">{p.iban}</td>
                      <td className="py-2 pr-3 text-xs">{p.due_date ?? "–"}</td>
                      <td className="py-2 pr-3 text-right tabular font-medium">{eur(p.amount)}</td>
                      <td className="py-2 text-right">
                        <Decide item={i} locked={locked} onDecide={decide} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {(state.payment_batch?.skipped.length ?? 0) > 0 && (
            <div className="mt-2 text-xs text-muted">Not in batch: {state.payment_batch!.skipped.map((s) => s.reason).join("; ")}</div>
          )}
        </Section>

        <Section
          title={`Vendor emails · ${emails.length} drafts`}
          subtitle="Written by the drafting agent in the vendor's language, addressed to the known contact from the vendor master. Approved emails go to an outbox; nothing is sent automatically."
          action={!locked && emails.some((p) => p.decision === "pending") ? <BulkButton onClick={() => decideAll("email")} busy={busy} label="Approve all emails" /> : null}
        >
          <div className="space-y-2">
            {emails.length === 0 && <div className="text-sm text-muted">No emails needed.</div>}
            {emails.map((i) => (
              <EmailCard key={i.item} item={i} locked={locked} onDecide={decide} runId={runId} />
            ))}
          </div>
        </Section>

        <Section
          title={`Needs a human decision · ${escalations.length}`}
          subtitle="Record your review here. Exceptions are excluded from this export; resolve them outside Ledgerline."
        >
          <div className="space-y-2">
            {escalations.length === 0 && <div className="text-sm text-muted">Nothing escalated.</div>}
            {escalations.map((i) => {
              const p = i.payload;
              return (
                <div key={i.item} className="rounded-lg border border-violet-200 bg-violet-50/40 p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <ShieldAlert size={16} className="text-escalate" />
                    <button onClick={() => go(runId, "audit", p.doc_id)} className="text-sm font-medium hover:underline">
                      {p.filename}
                    </button>
                    <span className="text-xs text-muted">
                      {p.extraction?.vendor_name} · {eur(p.extraction?.gross_total)}
                    </span>
                    <span className="ml-auto">
                      <Decide item={i} locked={locked} onDecide={decide} approveLabel="Mark reviewed" rejectLabel="Keep on hold" />
                    </span>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {(p.decision?.flags ?? []).map((f: { code: string; at_risk_eur: number }) => (
                      <FlagChip key={f.code} code={f.code} amount={f.at_risk_eur} />
                    ))}
                  </div>
                  <p className="mt-2 text-sm text-muted">{p.verification?.reason || p.decision?.rationale}</p>
                </div>
              );
            })}
          </div>
        </Section>
      </div>

      <aside className="space-y-4 xl:sticky xl:top-24 xl:self-start">
        <Card className="p-4">
          <div className="text-sm font-semibold">Create export</div>
          {state.executed ? (
            <div className="mt-2 space-y-3 text-sm">
              <div className="rounded-lg bg-emerald-50 p-3 text-approve">
                Export created. {state.executed.payments.length} payment instructions, {eur(state.executed.total)}. Nothing sent.
              </div>
              {state.executed.sepa_file && (
                <a
                  href={exportUrl(runId, state.executed.sepa_file)}
                  download="ledgerline-pain001.xml"
                  className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-brand px-3 py-2 text-sm font-semibold text-white"
                >
                  <Download size={15} /> SEPA file (pain.001)
                </a>
              )}
              <div className="text-xs text-muted">
                {state.executed.emails_queued.length} emails placed in the outbox. {state.executed.note}
              </div>
            </div>
          ) : (
            <>
              <div className="mt-1 text-xs text-muted">
                {pending > 0 ? `${pending} item(s) still need your decision.` : "All items decided."} Approved payments so far:{" "}
                <span className="tabular font-medium text-ink">{eur(approvedTotal)}</span>
              </div>
              {error && <div className="mt-2 rounded bg-red-50 p-2 text-xs text-reject">{error}</div>}
              <button
                onClick={execute}
                disabled={pending > 0 || busy || locked}
                className="mt-3 w-full rounded-lg bg-brand px-3 py-2 text-sm font-semibold text-white disabled:opacity-40"
              >
                Create SEPA file + outbox
              </button>
              <div className="mt-2 text-[11px] text-muted">
                Execution is deterministic code, not the model: it only uses what you approved. Uploading to the bank stays with you.
              </div>
            </>
          )}
        </Card>
        <Card className="p-4 text-xs text-muted">
          <div className="mb-1 text-sm font-semibold text-ink">Held or rejected by the agent</div>
          {state.docs
            .filter((d) => d.final_status === "hold" || d.final_status === "reject")
            .map((d) => (
              <button key={d.doc_id} onClick={() => go(runId, "audit", d.doc_id)} className="flex w-full items-center gap-2 py-1 text-left hover:text-ink">
                <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${d.final_status === "reject" ? "bg-reject" : "bg-hold"}`} />
                <span className="truncate">{d.filename}</span>
                <span className="ml-auto tabular text-amber-700">{eur(d.at_risk_eur, 0)}</span>
              </button>
            ))}
        </Card>
      </aside>
    </div>
  );
}

function Section({ title, subtitle, action, children }: { title: string; subtitle: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <Card className="p-4">
      <div className="mb-3 flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold">{title}</div>
          <div className="text-xs text-muted">{subtitle}</div>
        </div>
        {action}
      </div>
      {children}
    </Card>
  );
}

function BulkButton({ onClick, busy, label }: { onClick: () => void; busy: boolean; label: string }) {
  return (
    <button onClick={onClick} disabled={busy} className="rounded-lg bg-white px-3 py-1.5 text-xs font-semibold ring-1 ring-line hover:bg-paper disabled:opacity-40">
      {label}
    </button>
  );
}

function Decide({
  item,
  locked,
  onDecide,
  approveLabel = "Approve",
  rejectLabel = "Reject",
}: {
  item: ApprovalItem;
  locked: boolean;
  onDecide: (item: string, d: "approved" | "rejected") => void;
  approveLabel?: string;
  rejectLabel?: string;
}) {
  if (item.decision !== "pending" || locked)
    return (
      <span className={`text-xs font-medium ${item.decision === "approved" ? "text-approve" : item.decision === "rejected" ? "text-reject" : "text-muted"}`}>
        {item.decision === "approved" ? <Check size={13} className="mr-0.5 inline" /> : item.decision === "rejected" ? <X size={13} className="mr-0.5 inline" /> : null}
        {item.kind === "escalation" && item.decision !== "pending"
          ? item.decision === "approved" ? "reviewed · excluded from export" : "on hold · excluded from export"
          : item.decision}
      </span>
    );
  return (
    <span className="inline-flex gap-1">
      <button onClick={() => onDecide(item.item, "approved")} className="rounded-md bg-emerald-600 px-2 py-1 text-xs font-medium text-white hover:bg-emerald-700">
        {approveLabel}
      </button>
      <button onClick={() => onDecide(item.item, "rejected")} className="rounded-md bg-white px-2 py-1 text-xs font-medium text-reject ring-1 ring-red-200 hover:bg-red-50">
        {rejectLabel}
      </button>
    </span>
  );
}

function EmailCard({ item, locked, onDecide, runId }: { item: ApprovalItem; locked: boolean; onDecide: (i: string, d: "approved" | "rejected") => void; runId: string }) {
  const e = item.payload as Email;
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-line">
      <div className="flex flex-wrap items-center gap-2 p-3">
        <Mail size={15} className="text-muted" />
        <button onClick={() => setOpen(!open)} className="min-w-0 flex-1 text-left">
          <div className="truncate text-sm font-medium">{e.subject}</div>
          <div className="truncate text-xs text-muted">
            to {e.to_name} &lt;{e.to}&gt; · {e.language.toUpperCase()} · {e.purpose}
          </div>
        </button>
        <ChevronDown size={15} className={`text-muted transition ${open ? "rotate-180" : ""}`} />
        <Decide item={item} locked={locked} onDecide={onDecide} />
      </div>
      {open && (
        <div className="border-t border-line bg-paper/60 p-3">
          <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">{e.body}</pre>
          <div className="mt-2 text-xs text-muted">
            About:{" "}
            {e.doc_ids.map((d) => (
              <button key={d} onClick={() => go(runId, "audit", d)} className="mr-2 font-mono text-brand-2 hover:underline">
                {d}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
