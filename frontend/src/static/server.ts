/** In-memory stand-in for the FastAPI backend in the static demo build (replay mode only). */
import type { Config, Doc, RunEvent, RunState, RunSummary } from "../api";
import { approvalItems, buildExecution, evaluate, fold, type RunMeta } from "./engine";

type Any = any; // eslint-disable-line @typescript-eslint/no-explicit-any
type Demo = {
  config: Config;
  documents: Doc[];
  email_texts: Record<string, string>;
  files: Record<string, string>;
  ground_truth: Any[];
  replays: Record<string, { name: string; batch_id: string; provider: Any; recorded_at: string; git_commit?: string;
    stats: Any; events: { t: number; type: string; agent: string | null; doc_id: string | null; payload: Any }[] }>;
};

const ROOT = `${import.meta.env.BASE_URL}static/`;
let demo: Promise<Demo> | null = null;
const load = () => (demo ??= fetch(`${ROOT}demo.json`).then((r) => r.json()));

const runs = new Map<string, { meta: RunMeta; events: RunEvent[]; subs: Set<(e: RunEvent) => void> }>();
const exports = new Map<string, string>();

function emit(runId: string, type: string, payload: Any, agent: string | null = null, doc_id: string | null = null) {
  const r = runs.get(runId)!;
  const ev: RunEvent = { run_id: runId, seq: r.events.length + 1, ts: Date.now() / 1000, type, agent, doc_id, payload };
  r.events.push(ev);
  r.subs.forEach((s) => s(ev));
}

async function state(runId: string): Promise<RunState> {
  const r = runs.get(runId);
  if (!r) throw new Error("run not found (the browser demo keeps runs in memory; start a new one)");
  const d = await load();
  const st = fold(r.meta, r.events);
  st.approval_items = st.approval ? approvalItems(st) : [];
  st.evaluation = ["awaiting_approval", "completed"].includes(st.run.status) ? evaluate(st, d.ground_truth) : null;
  return st;
}

export const staticApi = {
  config: async () => (await load()).config,
  batch: async (_id: string) => ({ batch_id: "sample", documents: (await load()).documents }),
  runs: async (): Promise<RunSummary[]> => {
    const out: RunSummary[] = [];
    for (const [id, r] of [...runs.entries()].reverse()) {
      const st = await state(id);
      out.push({ ...r.meta, status: st.run.status, provider: st.run.provider ?? null,
        metrics: { documents: st.metrics.documents, processed: st.metrics.processed, eur_at_risk: st.metrics.eur_at_risk,
          cost_usd: st.metrics.cost_usd } } as RunSummary);
    }
    return out;
  },
  run: state,
  start: async (body: { mode: string; provider: string; replay_id?: string; speed?: number }) => {
    if (body.mode !== "replay") throw new Error("This browser demo only replays recorded runs. Run it locally for live mode.");
    const d = await load();
    const rid = body.replay_id ?? Object.keys(d.replays).find((k) => d.replays[k].provider?.key === body.provider);
    const data = rid ? d.replays[rid] : undefined;
    if (!data) throw new Error("No recorded run for this engine.");
    const runId = Math.random().toString(16).slice(2, 14);
    runs.set(runId, { meta: { run_id: runId, batch_id: data.batch_id, mode: "replay", provider: data.provider?.key ?? body.provider,
      created_at: Date.now() / 1000, replay_of: rid! }, events: [], subs: new Set() });
    const speed = Math.max(body.speed ?? 4, 0.1);
    let prev = 0, i = 0;
    const next = () => {
      if (i >= data.events.length) return;
      const e = data.events[i++];
      const gap = Math.min(Math.max((e.t - prev) / speed, 0), 1.5);
      prev = e.t;
      setTimeout(() => {
        const payload = e.type === "run.started" ? { ...e.payload, replay: { id: data.name, recorded_at: data.recorded_at, speed,
          git_commit: data.git_commit, wall_seconds: data.stats?.wall_seconds } } : e.payload;
        emit(runId, e.type, payload, e.agent, e.doc_id);
        next();
      }, gap * 1000);
    };
    next();
    return { run_id: runId };
  },
  approve: async (runId: string, item: string, decision: "approved" | "rejected", note = "") => {
    const st = await state(runId);
    if (st.run.status !== "awaiting_approval") throw new Error(`run is ${st.run.status}`);
    emit(runId, "approval.decided", { item, decision, note, actor: "human approver" }, "human");
    return { ok: true };
  },
  execute: async (runId: string) => {
    const st = await state(runId);
    if (st.approval_items.some((i) => i.decision === "pending")) throw new Error("some items still need a decision");
    const { result, xml } = buildExecution(st, runId);
    if (xml) exports.set(`${runId}/pain001.xml`, URL.createObjectURL(new Blob([xml], { type: "application/xml" })));
    emit(runId, "run.executed", result, "human");
    return result;
  },
  record: async () => {
    throw new Error("Recording needs the local app in live mode.");
  },
  subscribe: (runId: string, cb: (e: RunEvent) => void) => {
    const r = runs.get(runId);
    if (!r) return () => {};
    r.events.forEach(cb);
    r.subs.add(cb);
    return () => r.subs.delete(cb);
  },
  pageUrl: (docId: string, n: number) => `${ROOT}pages/${docId}/p${n}.jpg`,
  fileUrl: (docId: string) => demoFiles.get(docId) ?? "#",
  exportUrl: (runId: string, name: string) => exports.get(`${runId}/${name}`) ?? "#",
  docText: async (docId: string) => ({ text: (await load()).email_texts[docId] ?? "" }),
};

const demoFiles = new Map<string, string>();
load().then((d) => Object.entries(d.files).forEach(([id, path]) => demoFiles.set(id, `${ROOT}${path}`)));
