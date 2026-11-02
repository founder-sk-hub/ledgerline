import type { ReactNode } from "react";
import { FileText, Image as ImageIcon, Mail, Lock, Cloud, Mic, Laptop } from "lucide-react";
import type { Provider } from "../api";

export const eur = (n: number | null | undefined, digits = 2) =>
  n == null || Number.isNaN(n)
    ? "–"
    : new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR", minimumFractionDigits: digits, maximumFractionDigits: digits }).format(n);

export const usd = (n: number) => `$${n < 1 ? n.toFixed(4) : n.toFixed(2)}`;
export const int = (n: number) => new Intl.NumberFormat("en-US").format(n);
export const secs = (ms: number) => (ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`);

export const STATUS: Record<string, { label: string; cls: string; dot: string }> = {
  approve: { label: "Approve", cls: "bg-emerald-50 text-approve ring-emerald-200", dot: "bg-approve" },
  hold: { label: "Hold", cls: "bg-amber-50 text-hold ring-amber-200", dot: "bg-hold" },
  reject: { label: "Reject", cls: "bg-red-50 text-reject ring-red-200", dot: "bg-reject" },
  escalate: { label: "Needs human", cls: "bg-violet-50 text-escalate ring-violet-200", dot: "bg-escalate" },
  file: { label: "Filed", cls: "bg-slate-100 text-file ring-slate-200", dot: "bg-file" },
};

export const FLAG_LABEL: Record<string, string> = {
  DUPLICATE: "Duplicate",
  PRICE_DRIFT: "Price drift",
  QTY_EXCEEDS_PO: "Over PO quantity",
  SHORT_DELIVERY: "Short delivery",
  MISSING_PO: "Missing PO",
  VAT_RATE: "Wrong VAT rate",
  VAT_ARITHMETIC: "VAT math",
  ARITHMETIC: "Math error",
  BANK_DETAILS_CHANGED: "Bank details changed",
  SENDER_DOMAIN_MISMATCH: "Lookalike sender",
  UNKNOWN_VENDOR: "Unknown vendor",
  CONTRACT_PRICE_CHANGE: "Contract price change",
  OTHER: "Other",
};

/** "Muse Spark", "Muse Glimmer", ... from a provider label such as "Muse Glimmer · on this machine (Ollama)". */
export const modelName = (p?: Provider | null) => (p?.label ?? "the model").split(" · ")[0];

export function StatusChip({ status, size = "sm" }: { status: string | null; size?: "sm" | "md" }) {
  if (!status) return null;
  const s = STATUS[status] ?? STATUS.file;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full ring-1 ring-inset font-medium ${s.cls} ${
        size === "md" ? "px-2.5 py-1 text-xs" : "px-2 py-0.5 text-[11px]"
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  );
}

export function FlagChip({ code, amount }: { code: string; amount?: number }) {
  const info = code === "CONTRACT_PRICE_CHANGE";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium ${
        info ? "bg-sky-50 text-sky-800" : "bg-orange-50 text-orange-800"
      }`}
    >
      {FLAG_LABEL[code] ?? code}
      {amount ? <span className="tabular opacity-70">· {eur(amount, 0)}</span> : null}
    </span>
  );
}

export function ProviderBadge({ provider, compact }: { provider?: Provider | null; compact?: boolean }) {
  if (!provider) return null;
  const open = provider.open_weights;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium text-white ${
        open ? "bg-open" : "bg-meta"
      }`}
      title={`${provider.label} · ${provider.model}`}
    >
      {provider.local ? <Laptop size={12} /> : open ? <Lock size={12} /> : <Cloud size={12} />}
      {compact ? provider.badge : provider.label}
    </span>
  );
}

export function KindIcon({ kind, size = 14 }: { kind: string; size?: number }) {
  if (kind === "email") return <Mail size={size} />;
  if (kind === "audio") return <Mic size={size} />;
  if (kind === "image") return <ImageIcon size={size} />;
  return <FileText size={size} />;
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-xl border border-line bg-white ${className}`}>{children}</div>;
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "gold" | "brand" }) {
  return (
    <Card className="p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-muted">{label}</div>
      <div className={`mt-1 text-2xl font-semibold tabular ${tone === "gold" ? "text-amber-700" : tone === "brand" ? "text-brand" : ""}`}>
        {value}
      </div>
      {sub ? <div className="mt-0.5 text-xs text-muted">{sub}</div> : null}
    </Card>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-xl border border-dashed border-line bg-white/60 p-10 text-center text-sm text-muted">{children}</div>;
}

export function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <svg width="30" height="30" viewBox="0 0 32 32" aria-hidden>
        <rect width="32" height="32" rx="8" fill="#0f3d3a" />
        <path d="M8 11h16M8 16h10M8 21h7" stroke="#a7f3d0" strokeWidth="2.4" strokeLinecap="round" />
        <path d="M19 20.5l2.5 2.5 4.5-5" stroke="#f2b33d" strokeWidth="2.4" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <div className="leading-tight">
        <div className="text-[15px] font-semibold tracking-tight">Ledgerline</div>
        <div className="text-[11px] text-muted">invoice & delivery review</div>
      </div>
    </div>
  );
}
