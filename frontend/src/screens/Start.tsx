import { useEffect, useRef, useState } from "react";
import { ArrowRight, Cloud, History, Lock, Upload, Zap } from "lucide-react";
import { api, pageUrl, type Config, type Doc, type RunSummary } from "../api";
import { go } from "../App";
import { Card, KindIcon, ProviderBadge, eur, usd } from "../components/ui";

export default function Start({ config, runs }: { config: Config | null; runs: RunSummary[] }) {
  const [batch, setBatch] = useState<{ batch_id: string; documents: Doc[] } | null>(null);
  const [provider, setProvider] = useState<"meta" | "private">("meta");
  const [mode, setMode] = useState<"replay" | "live">("replay");
  const [speed, setSpeed] = useState(4);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.batch("sample").then(setBatch).catch(() => setBatch(null));
  }, []);
  useEffect(() => {
    if (config?.live_enabled && config.replays.length === 0) setMode("live");
  }, [config]);

  const prov = config?.providers.find((p) => p.key === provider);
  const replay = config?.replays.find((r) => r.provider?.key === provider) ?? null;
  const liveReady = !!config?.live_enabled && !!prov?.available;
  const canStart = mode === "replay" ? !!replay : liveReady;

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const r = await api.start(
        mode === "replay"
          ? { mode, provider, replay_id: replay?.id, speed }
          : { mode, provider, batch_id: batch?.batch_id ?? "sample" },
      );
      go(r.run_id, "run");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function onFiles(files: FileList | null) {
    if (!files?.length) return;
    setError(null);
    try {
      setBatch(await api.upload(Array.from(files)));
      setMode("live");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_400px]">
      <section>
        <h1 className="max-w-3xl text-3xl font-semibold tracking-tight sm:text-4xl">
          A month of messy invoices in. A verified payment batch out, <span className="text-brand-2">waiting for your OK.</span>
        </h1>
        <p className="mt-3 max-w-3xl text-[15px] leading-relaxed text-muted">
          Ledgerline reads PDFs, phone photos and emails, checks every document against your vendor master, purchase orders,
          contracts, VAT rules and payment history, and catches duplicates, price drift, wrong VAT and payment-diversion fraud. A
          second Muse Spark pass verifies every decision against the original document. Then it drafts the SEPA batch and vendor
          emails and stops: nothing moves without a human.
        </p>

        <Card className="mt-6">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
            <div>
              <div className="text-sm font-semibold">
                {batch?.batch_id === "sample" ? "Sample batch · Spree Roastery GmbH, Berlin · October" : `Uploaded batch ${batch?.batch_id ?? ""}`}
              </div>
              <div className="text-xs text-muted">
                {batch ? `${batch.documents.length} documents` : "…"}
                {batch?.batch_id === "sample" && " · synthetic: invented vendors, IBANs and planted anomalies"}
              </div>
            </div>
            {config?.live_enabled && (
              <>
                <input ref={fileInput} type="file" multiple hidden accept=".pdf,.jpg,.jpeg,.png,.webp,.eml,.txt" onChange={(e) => onFiles(e.target.files)} />
                <button
                  onClick={() => fileInput.current?.click()}
                  className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium ring-1 ring-line hover:bg-paper"
                >
                  <Upload size={14} /> Upload your own
                </button>
              </>
            )}
          </div>
          <div className="grid max-h-[520px] grid-cols-3 gap-3 overflow-y-auto p-4 scroll-thin sm:grid-cols-4 md:grid-cols-5 xl:grid-cols-6">
            {batch?.documents.map((d) => <Thumb key={d.doc_id} d={d} />)}
          </div>
        </Card>
      </section>

      <aside className="space-y-4 lg:sticky lg:top-24 lg:self-start">
        <Card className="p-4">
          <div className="text-sm font-semibold">Engine</div>
          <div className="mt-2 grid gap-2">
            {config?.providers.map((p) => (
              <button
                key={p.key}
                onClick={() => setProvider(p.key)}
                className={`rounded-lg p-3 text-left ring-1 transition ${
                  provider === p.key ? "bg-[#f1f7f6] ring-2 ring-brand" : "ring-line hover:bg-paper"
                }`}
              >
                <div className="flex items-center gap-2 text-sm font-medium">
                  {p.open_weights ? <Lock size={14} className="text-open" /> : <Cloud size={14} className="text-meta" />}
                  {p.open_weights ? "Private mode" : "Standard"}
                  <span className="ml-auto font-mono text-[11px] text-muted">{p.badge}</span>
                </div>
                <div className="mt-1 text-xs text-muted">
                  {p.open_weights
                    ? "Muse Spark Open, Meta's open-weight model, served by Baseten. Same agent; can point at your own deployment."
                    : "Muse Spark 1.3 on Meta Model API: multimodal reading, tool calling, structured output."}
                </div>
              </button>
            ))}
          </div>

          <div className="mt-4 text-sm font-semibold">Source</div>
          <div className="mt-2 grid grid-cols-2 gap-2">
            <button
              onClick={() => setMode("replay")}
              className={`rounded-lg px-3 py-2 text-left text-sm ring-1 ${mode === "replay" ? "bg-[#f1f7f6] ring-2 ring-brand" : "ring-line"}`}
            >
              <History size={14} className="mb-1" />
              Replay
              <div className="text-[11px] text-muted">recorded real run, no key</div>
            </button>
            <button
              onClick={() => setMode("live")}
              disabled={!config?.live_enabled}
              className={`rounded-lg px-3 py-2 text-left text-sm ring-1 disabled:opacity-40 ${
                mode === "live" ? "bg-[#f1f7f6] ring-2 ring-brand" : "ring-line"
              }`}
            >
              <Zap size={14} className="mb-1" />
              Live
              <div className="text-[11px] text-muted">{config?.live_enabled ? "calls the model now" : "needs your API key"}</div>
            </button>
          </div>

          {mode === "replay" && (
            <div className="mt-3 rounded-lg bg-paper p-3 text-xs text-muted">
              {replay ? (
                <>
                  Recorded {new Date(replay.recorded_at).toLocaleString()} with <span className="font-mono">{replay.provider?.model}</span>:{" "}
                  {replay.stats.llm_calls} model calls, {usd(replay.stats.cost_usd)}, {Math.round(replay.stats.wall_seconds)}s,{" "}
                  {eur(replay.stats.eur_at_risk)} at risk caught.
                  <div className="mt-2 flex items-center gap-2">
                    Speed
                    {[1, 4, 10].map((s) => (
                      <button
                        key={s}
                        onClick={() => setSpeed(s)}
                        className={`rounded px-2 py-0.5 ${speed === s ? "bg-brand text-white" : "bg-white ring-1 ring-line"}`}
                      >
                        {s}×
                      </button>
                    ))}
                  </div>
                </>
              ) : (
                <>No recorded run for this engine yet. {config?.live_enabled ? "Start a live run and record it." : ""}</>
              )}
            </div>
          )}
          {mode === "live" && config && (
            <div className="mt-3 rounded-lg bg-paper p-3 text-xs text-muted">
              {prov?.available ? (
                <>
                  Calls <span className="font-mono">{prov.model}</span> at {new URL(prov.base_url).host}. Budget guard: {usd(config.spent_usd)} of{" "}
                  {usd(config.budget_usd)} used.
                </>
              ) : (
                <>No API key for this engine. Add it to <span className="font-mono">.env</span> (see README).</>
              )}
            </div>
          )}

          {error && <div className="mt-3 rounded-lg bg-red-50 p-2 text-xs text-reject">{error}</div>}
          <button
            onClick={start}
            disabled={!canStart || busy}
            className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-brand px-4 py-2.5 text-sm font-semibold text-white hover:bg-brand-2 disabled:opacity-40"
          >
            {mode === "replay" ? "Replay the run" : "Run the agent"} <ArrowRight size={16} />
          </button>
        </Card>

        {runs.length > 0 && (
          <Card className="p-4">
            <div className="text-sm font-semibold">Recent runs</div>
            <div className="mt-2 divide-y divide-line">
              {runs.slice(0, 6).map((r) => (
                <button key={r.run_id} onClick={() => go(r.run_id, "run")} className="flex w-full items-center gap-2 py-2 text-left text-xs hover:bg-paper">
                  <ProviderBadge provider={r.provider} compact />
                  <span className="text-muted">{r.mode}</span>
                  <span className="ml-auto tabular">{eur(r.metrics.eur_at_risk, 0)} caught</span>
                  <span className="w-28 text-right text-muted">{r.status.replace("_", " ")}</span>
                </button>
              ))}
            </div>
          </Card>
        )}
      </aside>
    </div>
  );
}

function Thumb({ d }: { d: Doc }) {
  return (
    <div className="group">
      <div className="aspect-[3/4] overflow-hidden rounded-lg bg-paper ring-1 ring-line">
        {d.kind === "email" ? (
          <div className="flex h-full flex-col gap-1 p-2 text-[10px] leading-snug text-muted">
            <KindIcon kind="email" size={16} />
            <div className="line-clamp-2 font-medium text-ink">{d.meta.subject}</div>
            <div className="line-clamp-2">{d.meta.from}</div>
          </div>
        ) : (
          <img src={pageUrl(d.doc_id, 1)} alt={d.filename} loading="lazy" className="h-full w-full object-cover object-top transition group-hover:scale-[1.03]" />
        )}
      </div>
      <div className="mt-1 flex items-center gap-1 truncate text-[11px] text-muted" title={d.filename}>
        <KindIcon kind={d.kind} size={11} />
        <span className="truncate">{d.filename}</span>
      </div>
    </div>
  );
}
