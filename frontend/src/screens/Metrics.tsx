import type { RunState, RunSummary } from "../api";
import { go } from "../App";
import { Card, Empty, FLAG_LABEL, ProviderBadge, STATUS, Stat, eur, int, secs, usd } from "../components/ui";

export default function Metrics({ state, runs }: { state: RunState; runs: RunSummary[] }) {
  const m = state.metrics;
  const ev = state.evaluation;
  if (!m.processed) return <Empty>Metrics appear as documents are decided.</Empty>;
  const flagMax = Math.max(1, ...Object.values(m.flags));
  const statusOrder = ["approve", "hold", "reject", "escalate", "file"];

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat
          label="Time saved"
          value={`${Math.round(m.minutes_saved)} min`}
          sub={`vs ${Math.round(m.manual_minutes)} min manual; ${m.human_review_minutes} min human review`}
          tone="brand"
        />
        <Stat label="EUR at risk caught" value={eur(m.eur_at_risk, 0)} sub={`${m.flagged_documents} of ${m.documents} documents stopped`} tone="gold" />
        <Stat label="Agent wall time" value={`${Math.round(m.wall_seconds)}s`} sub={`${m.documents} documents, end to end`} />
        <Stat label="Model cost" value={usd(m.cost_usd)} sub={`${usd(m.cost_usd / Math.max(m.documents, 1))} per document`} />
        <Stat label="Latency" value={secs(m.avg_latency_ms)} sub={`avg per call · p95 ${secs(m.p95_latency_ms)}`} />
        <Stat
          label="Verified"
          value={`${m.verifier_confirmed}/${m.verified}`}
          sub={`${m.verifier_escalations} escalated by verifier · avg conf. ${m.avg_verifier_confidence != null ? Math.round(m.avg_verifier_confidence * 100) + "%" : "–"}`}
        />
      </div>

      {m.models.length > 0 && (
        <Card className="flex flex-wrap items-center gap-2 p-4">
          <div className="mr-2 text-sm font-semibold">Meta models used in this run</div>
          {m.models.map((x) => (
            <span key={x} className="rounded-full bg-[#eef3ff] px-2.5 py-1 font-mono text-xs text-meta">
              {x}
            </span>
          ))}
        </Card>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        <Card className="p-4">
          <div className="text-sm font-semibold">What it caught</div>
          <div className="mt-3 space-y-2">
            {Object.entries(m.flags)
              .sort((a, b) => b[1] - a[1])
              .map(([code, n]) => (
                <div key={code} className="flex items-center gap-3 text-sm">
                  <div className="w-44 shrink-0 truncate text-xs">{FLAG_LABEL[code] ?? code}</div>
                  <div className="h-5 flex-1 rounded bg-paper">
                    <div className="h-5 rounded bg-gold/80" style={{ width: `${(n / flagMax) * 100}%` }} />
                  </div>
                  <div className="w-6 text-right text-xs tabular">{n}</div>
                </div>
              ))}
            {Object.keys(m.flags).length === 0 && <div className="text-sm text-muted">No anomalies flagged.</div>}
          </div>
        </Card>
        <Card className="p-4">
          <div className="text-sm font-semibold">Decisions</div>
          <div className="mt-3 flex h-8 overflow-hidden rounded-lg">
            {statusOrder
              .filter((s) => m.by_status[s])
              .map((s) => (
                <div key={s} className={`${STATUS[s].dot} flex items-center justify-center text-[11px] font-medium text-white`} style={{ flex: m.by_status[s] }}>
                  {m.by_status[s]}
                </div>
              ))}
          </div>
          <div className="mt-2 flex flex-wrap gap-3 text-xs text-muted">
            {statusOrder
              .filter((s) => m.by_status[s])
              .map((s) => (
                <span key={s} className="inline-flex items-center gap-1">
                  <span className={`h-2 w-2 rounded-full ${STATUS[s].dot}`} /> {STATUS[s].label} {m.by_status[s]}
                </span>
              ))}
          </div>
          <div className="mt-4 text-sm font-semibold">Document types read</div>
          <div className="mt-2 flex flex-wrap gap-2 text-xs">
            {Object.entries(m.by_type).map(([t, n]) => (
              <span key={t} className="rounded-md bg-paper px-2 py-1">
                {t.replace("_", " ")} <span className="font-semibold tabular">{n}</span>
              </span>
            ))}
          </div>
        </Card>
      </div>

      {ev && (
        <Card className="p-4">
          <div className="flex flex-wrap items-baseline gap-2">
            <div className="text-sm font-semibold">Accuracy on the synthetic benchmark</div>
            <div className="text-xs text-muted">
              Scored after the run against the planted anomalies in data/samples/ground_truth.json (never shown to the agent).
            </div>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Anomalous docs stopped" value={`${ev.anomalous_documents_stopped}/${ev.anomalous_documents}`} />
            <Stat label="Flag recall" value={pct(ev.flag_recall)} />
            <Stat label="Flag precision" value={pct(ev.flag_precision)} />
            <Stat label="Decision accuracy" value={pct(ev.decision_accuracy)} />
          </div>
          <details className="mt-3">
            <summary className="cursor-pointer text-xs font-medium text-brand-2">Per-document comparison</summary>
            <table className="mt-2 w-full text-xs">
              <thead className="text-left text-muted">
                <tr className="border-b border-line">
                  <th className="py-1.5 font-medium">Document</th>
                  <th className="py-1.5 font-medium">Expected</th>
                  <th className="py-1.5 font-medium">Agent</th>
                  <th className="py-1.5 font-medium">Decision</th>
                </tr>
              </thead>
              <tbody>
                {ev.rows.map((r) => {
                  const ok = r.decision_ok && r.flags.join() === r.expected_flags.join();
                  return (
                    <tr key={r.filename} className={`border-b border-line/60 ${ok ? "" : "bg-amber-50/60"}`}>
                      <td className="py-1.5 pr-2">{r.filename}</td>
                      <td className="py-1.5 pr-2">{r.expected_flags.join(", ") || "–"}</td>
                      <td className="py-1.5 pr-2">{r.flags.join(", ") || "–"}</td>
                      <td className="py-1.5">
                        {r.decision} {r.decision_ok ? "✓" : `(expected ${r.expected_decision})`}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </details>
        </Card>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        <Card className="p-4">
          <div className="text-sm font-semibold">Model usage by agent</div>
          <table className="mt-2 w-full text-sm">
            <thead className="text-left text-xs text-muted">
              <tr className="border-b border-line">
                <th className="py-1.5 font-medium">Agent</th>
                <th className="py-1.5 text-right font-medium">Calls</th>
                <th className="py-1.5 text-right font-medium">Avg latency</th>
                <th className="py-1.5 text-right font-medium">Cost</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(m.by_agent).map(([a, s]) => (
                <tr key={a} className="border-b border-line/60">
                  <td className="py-1.5 capitalize">{a}</td>
                  <td className="py-1.5 text-right tabular">{s.calls}</td>
                  <td className="py-1.5 text-right tabular">{secs(s.avg_latency_ms)}</td>
                  <td className="py-1.5 text-right tabular">{usd(s.cost_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-2 text-xs text-muted">
            {int(m.input_tokens)} input · {int(m.output_tokens)} output ({int(m.reasoning_tokens)} reasoning) tokens · {m.llm_errors} errors
          </div>
          <div className="mt-2 text-[11px] text-muted">
            Time saved assumes {m.assumptions.manual_minutes_per_document} min of manual processing per document and{" "}
            {m.assumptions.review_minutes_per_flag} min of human review per stopped document (configurable).
          </div>
        </Card>
        <Card className="p-4">
          <div className="text-sm font-semibold">Standard vs. private mode</div>
          <div className="text-xs text-muted">Same agent, same batch. Muse Spark on Meta Model API vs. Muse Spark Open (open weights).</div>
          <table className="mt-2 w-full text-xs">
            <thead className="text-left text-muted">
              <tr className="border-b border-line">
                <th className="py-1.5 font-medium">Run</th>
                <th className="py-1.5 font-medium">Engine</th>
                <th className="py-1.5 text-right font-medium">Docs</th>
                <th className="py-1.5 text-right font-medium">At risk caught</th>
                <th className="py-1.5 text-right font-medium">Cost</th>
              </tr>
            </thead>
            <tbody>
              {runs
                .filter((r) => r.metrics.processed > 0)
                .slice(0, 8)
                .map((r) => (
                  <tr key={r.run_id} className={`border-b border-line/60 ${r.run_id === state.run.run_id ? "bg-[#eef6f4]" : ""}`}>
                    <td className="py-1.5">
                      <button onClick={() => go(r.run_id, "metrics")} className="font-mono text-brand-2 hover:underline">
                        {r.run_id.slice(0, 6)}
                      </button>{" "}
                      <span className="text-muted">{r.mode}</span>
                    </td>
                    <td className="py-1.5">
                      <ProviderBadge provider={r.provider} compact />
                    </td>
                    <td className="py-1.5 text-right tabular">{r.metrics.processed}</td>
                    <td className="py-1.5 text-right tabular">{eur(r.metrics.eur_at_risk, 0)}</td>
                    <td className="py-1.5 text-right tabular">{usd(r.metrics.cost_usd)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </Card>
      </div>
    </div>
  );
}

const pct = (x: number | null) => (x == null ? "–" : `${Math.round(x * 100)}%`);
