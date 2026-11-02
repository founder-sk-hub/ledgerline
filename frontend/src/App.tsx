import { useEffect, useState } from "react";
import { History, PlayCircle } from "lucide-react";
import { api, useRun, type Config, type RunSummary } from "./api";
import { Logo, ProviderBadge } from "./components/ui";
import Start from "./screens/Start";
import LiveRun from "./screens/LiveRun";
import Approvals from "./screens/Approvals";
import Audit from "./screens/Audit";
import Metrics from "./screens/Metrics";

export type Tab = "run" | "approvals" | "audit" | "metrics";
const TABS: { key: Tab; label: string }[] = [
  { key: "run", label: "Live run" },
  { key: "approvals", label: "Approval queue" },
  { key: "audit", label: "Audit trail" },
  { key: "metrics", label: "Metrics" },
];

function parseHash(): { runId: string | null; tab: Tab; doc: string | null } {
  const [, runPart, id, tab, doc] = window.location.hash.split("/");
  if (runPart === "run" && id) return { runId: id, tab: (tab as Tab) || "run", doc: doc || null };
  return { runId: null, tab: "run", doc: null };
}

export function go(runId: string | null, tab: Tab = "run", doc?: string) {
  window.location.hash = runId ? `#/run/${runId}/${tab}${doc ? `/${doc}` : ""}` : "#/";
}

export default function App() {
  const [route, setRoute] = useState(parseHash);
  const [config, setConfig] = useState<Config | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const { state, events, error, reload } = useRun(route.runId);

  useEffect(() => {
    const on = () => setRoute(parseHash());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  useEffect(() => {
    api.config().then(setConfig).catch(() => setConfig(null));
    api.runs().then(setRuns).catch(() => setRuns([]));
  }, [route.runId, state?.run.status]);

  const pending = state?.approval_items.filter((i) => i.decision === "pending").length ?? 0;

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-line bg-paper/90 backdrop-blur">
        <div className="mx-auto flex max-w-[1500px] items-center gap-6 px-4 py-3 sm:px-6">
          <button onClick={() => go(null)} className="shrink-0 text-left">
            <Logo />
          </button>
          {route.runId ? (
            <nav className="flex min-w-0 gap-1 overflow-x-auto">
              {TABS.map((t) => (
                <button
                  key={t.key}
                  onClick={() => go(route.runId, t.key)}
                  className={`whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                    route.tab === t.key ? "bg-brand text-white" : "text-muted hover:bg-white hover:text-ink"
                  }`}
                >
                  {t.label}
                  {t.key === "approvals" && pending > 0 && state?.run.status === "awaiting_approval" ? (
                    <span className="ml-1.5 rounded-full bg-gold px-1.5 text-[11px] font-semibold text-ink">{pending}</span>
                  ) : null}
                </button>
              ))}
            </nav>
          ) : (
            <div className="hidden text-sm text-muted md:block">
              Reads every invoice, checks it against your books, and stops for your approval before money moves.
            </div>
          )}
          <div className="ml-auto flex items-center gap-2">
            {state?.run.provider ? <ProviderBadge provider={state.run.provider} compact /> : null}
            {runs.length > 0 && (
              <select
                className="hidden max-w-[220px] rounded-lg border border-line bg-white px-2 py-1.5 text-xs text-muted lg:block"
                value={route.runId ?? ""}
                onChange={(e) => go(e.target.value || null)}
              >
                <option value="">Recent runs…</option>
                {runs.map((r) => (
                  <option key={r.run_id} value={r.run_id}>
                    {new Date(r.created_at * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })} ·{" "}
                    {r.mode} · {r.provider?.badge ?? ""} · {r.status}
                  </option>
                ))}
              </select>
            )}
            {route.runId && (
              <button
                onClick={() => go(null)}
                className="inline-flex items-center gap-1.5 rounded-lg bg-white px-3 py-1.5 text-sm font-medium ring-1 ring-line hover:bg-paper"
              >
                <PlayCircle size={15} /> New run
              </button>
            )}
          </div>
        </div>
        {state?.run.replay && (
          <div className="border-t border-line bg-[#eef6f4] px-4 py-1.5 text-center text-xs text-brand-2 sm:px-6">
            <History size={12} className="mr-1 inline" />
            Replay of a real run recorded {new Date(state.run.replay.recorded_at).toLocaleString()} ·{" "}
            {state.run.replay.speed}× speed · every model call, latency and cost shown is from the recording. You are the approver.
          </div>
        )}
      </header>

      <main className="mx-auto max-w-[1500px] px-4 py-6 sm:px-6">
        {!route.runId && <Start config={config} runs={runs} />}
        {route.runId && !state && (
          <div className="py-24 text-center text-sm text-muted">{error ? `Could not load this run: ${error}` : "Loading run…"}</div>
        )}
        {route.runId && state && route.tab === "run" && <LiveRun state={state} events={events} />}
        {route.runId && state && route.tab === "approvals" && <Approvals state={state} reload={reload} />}
        {route.runId && state && route.tab === "audit" && <Audit state={state} docId={route.doc} />}
        {route.runId && state && route.tab === "metrics" && <Metrics state={state} runs={runs} />}
      </main>
      <footer className="mx-auto max-w-[1500px] px-4 pb-8 text-xs text-muted sm:px-6">
        All AI in Ledgerline runs on Meta models: Muse Spark 1.3 (Meta Model API) and Muse Spark Open (open weights). Built with Muse Spark Open. Demo data is synthetic.
      </footer>
    </div>
  );
}
