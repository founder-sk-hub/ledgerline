"""Fill the README results block from the recorded replays (so every number there comes from a real run).

    .venv/bin/python backend/scripts/readme_results.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ledgerline.config import REPLAYS, ROOT  # noqa: E402
from ledgerline.state import evaluate, fold  # noqa: E402


def row(data: dict) -> str:
    events = [{**e, "run_id": "r", "seq": i + 1, "ts": 1_000_000 + e["t"]} for i, e in enumerate(data["events"])]
    st = fold({"run_id": "r", "batch_id": data["batch_id"], "mode": "replay", "provider": "", "created_at": 0}, events)
    st["run"]["status"] = "awaiting_approval"
    m, ev = st["metrics"], evaluate(st) or {}
    prov = data.get("provider") or {}
    pct = lambda x: "–" if x is None else f"{x * 100:.0f}%"  # noqa: E731
    return (f"| {prov.get('label', '?')} (`{prov.get('model', '?')}`) | {m['documents']} | "
            f"{ev.get('anomalous_documents_stopped', '–')}/{ev.get('anomalous_documents', '–')} | "
            f"{pct(ev.get('flag_recall'))} | {pct(ev.get('flag_precision'))} | {pct(ev.get('decision_accuracy'))} | "
            f"EUR {m['eur_at_risk']:,.2f} | {m['wall_seconds'] / 60:.1f} min | ${m['cost_usd']:.2f} | "
            f"{data['recorded_at'][:10]} |")


def main() -> None:
    files = sorted(REPLAYS.glob("*.json"))
    rows = [row(json.loads(p.read_text())) for p in files]
    if not rows:
        sys.exit("no replays recorded yet")
    block = "\n".join([
        "<!-- RESULTS:START -->",
        "### Results on the synthetic benchmark (recorded live runs, replayable in the app)",
        "",
        "| Engine | Docs | Anomalous docs stopped | Flag recall | Flag precision | Decision accuracy | EUR at risk caught | Agent time | Model cost | Recorded |",
        "|---|---|---|---|---|---|---|---|---|---|",
        *rows,
        "",
        "Scored against `data/samples/ground_truth.json`, which the agent never sees. Local runs cost $0 in API fees.",
        "<!-- RESULTS:END -->",
    ])
    readme = ROOT / "README.md"
    text = re.sub(r"<!-- RESULTS:START -->.*?<!-- RESULTS:END -->", block, readme.read_text(), flags=re.S)
    readme.write_text(text)
    print(block)


if __name__ == "__main__":
    main()
