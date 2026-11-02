"""Runtime configuration, read from environment / .env (never committed)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DATA = ROOT / "data"
SAMPLES = DATA / "samples"
REPLAYS = DATA / "replays"
RUNTIME = DATA / "runtime"
DB_PATH = Path(os.getenv("LEDGERLINE_DB", DATA / "ledgerline.db"))
FRONTEND_DIST = ROOT / "frontend" / "dist"

for p in (RUNTIME, RUNTIME / "uploads", RUNTIME / "pages", RUNTIME / "exports"):
    p.mkdir(parents=True, exist_ok=True)


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


# Token prices in USD per 1M tokens (dev.meta.ai/docs/pricing-rate-limits, baseten.co/library/muse-spark-open)
PRICES = {
    "muse-spark-1.3": {"input": 1.25, "cached": 0.15, "output": 4.25},
    "muse-spark-1.2": {"input": 1.25, "cached": 0.15, "output": 4.25},
    "muse-spark-1.1": {"input": 1.25, "cached": 0.15, "output": 4.25},
    "muse-wonder-1.0": {"input": 4.00, "cached": 0.20, "output": 20.00},
    "meta-models/muse-spark-open": {"input": 1.25, "cached": 0.15, "output": 4.25},
}
DEFAULT_PRICE = {"input": 1.25, "cached": 0.15, "output": 4.25}


@dataclass(frozen=True)
class ProviderConfig:
    key: str  # "meta" | "private"
    label: str
    badge: str
    base_url: str
    model: str
    api_key: str
    developer_role: str  # role used for instructions
    structured: str  # "json_schema" | "tool"
    reasoning_effort: bool  # whether to send reasoning_effort
    open_weights: bool

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def public(self) -> dict:
        return {
            "key": self.key, "label": self.label, "badge": self.badge, "model": self.model,
            "base_url": self.base_url, "available": self.available, "open_weights": self.open_weights,
        }


def providers() -> dict[str, ProviderConfig]:
    meta_model = _env("META_MODEL", "muse-spark-1.3")
    private_model = _env("PRIVATE_MODEL", "meta-models/muse-spark-open")
    return {
        "meta": ProviderConfig(
            key="meta",
            label="Muse Spark · Meta Model API",
            badge=meta_model,
            base_url=_env("META_BASE_URL", "https://api.meta.ai/v1"),
            model=meta_model,
            api_key=_env("MODEL_API_KEY"),
            developer_role="developer",
            structured="json_schema",
            reasoning_effort=True,
            open_weights=False,
        ),
        "private": ProviderConfig(
            key="private",
            label="Muse Spark Open · open weights (Baseten)",
            badge=private_model.split("/")[-1],
            base_url=_env("PRIVATE_BASE_URL", "https://inference.baseten.co/v1"),
            model=private_model,
            api_key=_env("BASETEN_API_KEY") or _env("PRIVATE_API_KEY"),
            developer_role=_env("PRIVATE_INSTRUCTION_ROLE", "system"),
            structured=_env("PRIVATE_STRUCTURED", "tool"),
            reasoning_effort=_env("PRIVATE_REASONING_EFFORT", "0") == "1",
            open_weights=True,
        ),
    }


MODE = _env("LEDGERLINE_MODE", "replay")  # replay | live
MAX_CONCURRENCY = int(_env("LEDGERLINE_CONCURRENCY", "6"))
# Local spend guard: live runs are refused once recorded spend reaches this many USD.
BUDGET_USD = float(_env("LEDGERLINE_BUDGET_USD", "40"))

# Reasoning effort per agent role (Meta accepts minimal|low|medium|high|xhigh|max)
EFFORT = {
    "planner": _env("EFFORT_PLANNER", "low"),
    "intake": _env("EFFORT_INTAKE", "low"),
    "investigator": _env("EFFORT_INVESTIGATOR", "low"),
    "verifier": _env("EFFORT_VERIFIER", "medium"),
    "drafter": _env("EFFORT_DRAFTER", "low"),
}

# Business policy (would be per-tenant settings in production)
POLICY = {
    "po_required_above_eur": 500.0,
    "receipt_no_vendor_limit_eur": 250.0,
    "price_tolerance_pct": 2.0,
    "duplicate_window_days": 60,
    "verify_min_confidence": 0.75,
    "manual_minutes_per_document": 8.0,  # assumption for the time-saved metric, shown in the UI
    "review_minutes_per_flag": 1.5,
}
