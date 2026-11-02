"""Build the static browser demo (GitHub Pages): recorded replays play entirely client-side.

    .venv/bin/python backend/scripts/export_static.py [--base /ledgerline/]

Writes site/ (index.html, assets, static/demo.json, page images, original files).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ledgerline.config import ROOT, SAMPLES, providers  # noqa: E402
from ledgerline.db import DB  # noqa: E402
from ledgerline.documents import document_text, load_sample_batch, page_images  # noqa: E402
from ledgerline.replay import REPLAYS, list_replays  # noqa: E402

SITE = ROOT / "site"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="/ledgerline/")
    args = ap.parse_args()

    env = {**os.environ, "VITE_STATIC": "1"}
    subprocess.run(["npx", "vite", "build", "--base", args.base, "--outDir", str(SITE), "--emptyOutDir"],
                   cwd=ROOT / "frontend", env=env, check=True)
    static = SITE / "static"
    static.mkdir(parents=True, exist_ok=True)

    db = DB()
    docs = load_sample_batch(db)
    files, texts = {}, {}
    for d in docs:
        for i, p in enumerate(page_images(d), 1):
            target = static / "pages" / d["doc_id"] / f"p{i}.jpg"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(p, target)
        safe = re.sub(r"[^\w.\-]+", "_", d["filename"])
        target = static / "files" / d["doc_id"] / safe
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(d["path"], target)
        files[d["doc_id"]] = f"files/{d['doc_id']}/{safe}"
        if d["kind"] in ("email", "text"):
            texts[d["doc_id"]] = document_text(d)

    replays = {p.stem: json.loads(p.read_text()) for p in sorted(REPLAYS.glob("*.json"))}
    demo = {
        "config": {
            "mode": "replay", "live_enabled": False, "budget_usd": 0, "spent_usd": 0, "buyer": db.buyer(),
            "providers": [{**p.public(), "available": False} for p in providers().values()],
            "replays": list_replays(),
        },
        "documents": [{k: d[k] for k in ("doc_id", "idx", "filename", "kind", "meta")} for d in docs],
        "email_texts": texts,
        "files": files,
        "ground_truth": json.loads((SAMPLES / "ground_truth.json").read_text())["documents"],
        "replays": replays,
    }
    (static / "demo.json").write_text(json.dumps(demo, ensure_ascii=False))
    (SITE / ".nojekyll").write_text("")
    size = sum(f.stat().st_size for f in SITE.rglob("*") if f.is_file())
    print(f"site/ ready: {len(docs)} documents, {len(replays)} replays, {size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
