import { useEffect, useRef, useState } from "react";
import { staticApi } from "./static/server";

export type Provider = {
  key: "meta" | "private" | "local";
  label: string;
  badge: string;
  model: string;
  base_url: string;
  available: boolean;
  open_weights: boolean;
  local?: boolean;
  media?: boolean;
};

export type Replay = {
  id: string;
  name: string;
  recorded_at: string;
  batch_id: string;
  git_commit?: string;
  provider?: Provider;
  stats: { llm_calls: number; cost_usd: number; wall_seconds: number; eur_at_risk: number; documents: number };
};

export type Config = {
  mode: "replay" | "live";
  live_enabled: boolean;
  providers: Provider[];
  replays: Replay[];
  budget_usd: number;
  spent_usd: number;
  buyer: { name: string; address: string[]; vat_id: string };
};

export type DocMeta = { size?: number; pages?: number; from?: string; subject?: string; date?: string; duration_s?: number };
export type Doc = { doc_id: string; idx: number; filename: string; kind: string; meta: DocMeta };

export type Evidence = { field: string; page: number; quote: string; bbox?: number[] };
export type Line = {
  description: string;
  quantity: number;
  unit?: string;
  unit_price: number;
  net_amount: number;
  vat_rate: number;
  vat_category: string;
};
export type Extraction = {
  doc_type: string;
  vendor_name: string;
  vendor_country?: string;
  vendor_vat_id?: string;
  iban?: string;
  invoice_number: string;
  issue_date: string;
  service_period?: string;
  po_number?: string;
  currency?: string;
  lines: Line[];
  net_total: number;
  vat_total: number;
  gross_total: number;
  vat_note?: string;
  notes: string;
  evidence: Evidence[];
  confidence: number;
  uncertain_fields?: string[];
  transcript?: string;
  reference?: string;
  received_items?: { description: string; quantity: number; unit: string }[];
  counted?: { object: string; count: number; boxes: number[][]; method: string | null; model_estimate?: number };
};
export type Flag = {
  code: string;
  severity: string;
  message: string;
  at_risk_eur: number;
  agent_note?: string;
  source?: string;
  details?: Record<string, unknown>;
};
export type Decision = {
  decision: string;
  flags: Flag[];
  dismissed?: Flag[];
  at_risk_eur: number;
  gross?: number;
  rationale: string;
  confidence: number;
};
export type Claim = { claim: string; supported: boolean; page: number; quote: string; bbox?: number[]; confidence: number };
export type Verification = {
  verdict: string;
  overall_confidence: number;
  claims: Claim[];
  notes: string;
  final_status: string;
  escalated: boolean;
  reason?: string;
};
export type Step = { seq: number; ts: number; type: string; agent: string | null; payload: any };
export type RunDoc = {
  doc_id: string;
  filename: string;
  kind: string;
  pages: number;
  meta: DocMeta;
  status: string;
  extraction: Extraction | null;
  decision: Decision | null;
  verification: Verification | null;
  final_status: string | null;
  at_risk_eur: number;
  steps: Step[];
  error?: string;
};
export type PaymentItem = {
  vendor_id: string;
  vendor_name: string;
  iban: string;
  bic: string;
  amount: number;
  doc_ids: string[];
  reference: string;
  due_date: string | null;
};
export type Email = {
  email_id: string;
  vendor_id: string;
  to: string;
  to_name: string;
  subject: string;
  body: string;
  language: string;
  doc_ids: string[];
  purpose: string;
};
export type ApprovalItem = { item: string; kind: "payment" | "email" | "escalation"; decision: string; payload: any };
export type Metrics = {
  documents: number;
  processed: number;
  by_status: Record<string, number>;
  by_type: Record<string, number>;
  flags: Record<string, number>;
  flagged_documents: number;
  eur_at_risk: number;
  eur_payment_batch: number;
  payments: number;
  emails: number;
  llm_calls: number;
  llm_errors: number;
  input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  cost_usd: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
  by_agent: Record<string, { calls: number; cost_usd: number; avg_latency_ms: number }>;
  models: string[];
  wall_seconds: number;
  manual_minutes: number;
  human_review_minutes: number;
  minutes_saved: number;
  assumptions: { manual_minutes_per_document: number; review_minutes_per_flag: number };
  verified: number;
  verifier_confirmed: number;
  verifier_escalations: number;
  avg_verifier_confidence: number | null;
};
export type Evaluation = {
  documents: number;
  flag_precision: number | null;
  flag_recall: number | null;
  decision_accuracy: number | null;
  anomalous_documents: number;
  anomalous_documents_stopped: number;
  eur_at_risk_planted: number;
  rows: {
    filename: string;
    expected_flags: string[];
    flags: string[];
    expected_decision: string;
    decision: string;
    decision_ok: boolean;
  }[];
};
export type RunState = {
  run: {
    run_id: string;
    batch_id: string;
    mode: string;
    status: string;
    error: string | null;
    started_at: number | null;
    ended_at: number | null;
    provider?: Provider;
    replay?: { id: string; recorded_at: string; speed: number; git_commit?: string; wall_seconds?: number };
  };
  stage: string | null;
  stages: { stage: string; ts: number }[];
  plan: { summary: string; steps: { title: string; detail: string }[]; watchlist: { filename: string; reason: string }[] } | null;
  docs: RunDoc[];
  payment_batch: {
    execution_date: string;
    debtor: { name: string; iban: string };
    items: PaymentItem[];
    total: number;
    skipped: { doc_id: string; reason: string }[];
  } | null;
  emails: Email[];
  approval: { summary: string; payment_total: number; payments: number; emails: number; ts: number } | null;
  approvals: Record<string, { item: string; decision: string; actor: string; note: string }>;
  executed: {
    payments: PaymentItem[];
    total: number;
    sepa_file: string | null;
    emails_queued: { email_id: string; to: string; subject: string }[];
    note: string;
  } | null;
  system: Step[];
  metrics: Metrics;
  approval_items: ApprovalItem[];
  evaluation: Evaluation | null;
  last_seq: number;
};
export type RunEvent = {
  run_id: string;
  seq: number;
  ts: number;
  type: string;
  agent: string | null;
  doc_id: string | null;
  payload: any;
};
export type RunSummary = {
  run_id: string;
  created_at: number;
  batch_id: string;
  provider: Provider | null;
  mode: string;
  status: string;
  replay_of: string | null;
  metrics: { documents: number; processed: number; eur_at_risk: number; cost_usd: number };
};

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init);
  if (!r.ok) {
    let msg = `${r.status}`;
    try {
      msg = (await r.json()).detail ?? msg;
    } catch {
      /* not json */
    }
    throw new Error(msg);
  }
  return r.json();
}

const post = <T,>(path: string, body?: unknown) =>
  req<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });

export const STATIC = import.meta.env.VITE_STATIC === "1";

const httpApi = {
  config: () => req<Config>("/api/config"),
  batch: (id: string) => req<{ batch_id: string; documents: Doc[] }>(`/api/batches/${id}`),
  upload: (files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return req<{ batch_id: string; documents: Doc[] }>("/api/batches", { method: "POST", body: fd });
  },
  start: (body: { mode: string; provider: string; batch_id?: string; replay_id?: string; speed?: number }) =>
    post<{ run_id: string }>("/api/runs", body),
  runs: () => req<RunSummary[]>("/api/runs"),
  run: (id: string) => req<RunState>(`/api/runs/${id}`),
  approve: (id: string, item: string, decision: "approved" | "rejected", note = "") =>
    post(`/api/runs/${id}/approvals`, { item, decision, note }),
  execute: (id: string) => post<RunState["executed"]>(`/api/runs/${id}/execute`),
  record: (id: string, name: string) => post(`/api/runs/${id}/record`, { name }),
  docText: (id: string) => req<{ text: string }>(`/api/docs/${id}/text`),
};

export const api: typeof httpApi = STATIC ? (staticApi as unknown as typeof httpApi) : httpApi;

export const pageUrl = (docId: string, n: number) => (STATIC ? staticApi.pageUrl(docId, n) : `/api/docs/${docId}/pages/${n}`);
export const fileUrl = (docId: string) => (STATIC ? staticApi.fileUrl(docId) : `/api/docs/${docId}/file`);
export const exportUrl = (runId: string, name: string) => (STATIC ? staticApi.exportUrl(runId, name) : `/api/runs/${runId}/exports/${name}`);

/** Folded run state + live event stream (SSE), refetching the fold at most every 350 ms. */
export function useRun(runId: string | null) {
  const [state, setState] = useState<RunState | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    if (!runId) return;
    let alive = true;
    setState(null);
    setEvents([]);
    setError(null);
    const refresh = () => {
      if (timer.current) return;
      timer.current = window.setTimeout(async () => {
        timer.current = null;
        try {
          const s = await api.run(runId);
          if (alive) setState(s);
        } catch {
          /* transient */
        }
      }, 350);
    };
    api
      .run(runId)
      .then((s) => alive && setState(s))
      .catch((e: Error) => alive && setError(e.message));
    const onEvent = (ev: RunEvent) => {
      setEvents((prev) => (prev.length && prev[prev.length - 1].seq >= ev.seq ? prev : [...prev, ev]));
      refresh();
    };
    if (STATIC) {
      const unsub = staticApi.subscribe(runId, onEvent);
      return () => {
        alive = false;
        unsub();
        if (timer.current) window.clearTimeout(timer.current);
        timer.current = null;
      };
    }
    const es = new EventSource(`/api/runs/${runId}/events`);
    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) es.close();
    };
    es.onmessage = (m) => {
      const ev = JSON.parse(m.data) as RunEvent;
      if (ev.type === "ping") return;
      setEvents((prev) => (prev.length && prev[prev.length - 1].seq >= ev.seq ? prev : [...prev, ev]));
      refresh();
    };
    return () => {
      alive = false;
      es.close();
      if (timer.current) window.clearTimeout(timer.current);
      timer.current = null;
    };
  }, [runId]);

  const reload = async () => runId && setState(await api.run(runId));
  return { state, events, error, reload };
}
