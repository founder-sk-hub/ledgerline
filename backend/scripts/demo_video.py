"""Record the 3-minute demo video by driving the real app (replay of a recorded live run).

    .venv/bin/python backend/scripts/demo_video.py record     # needs the app on http://localhost:8020
    .venv/bin/python backend/scripts/demo_video.py assemble   # mixes in the narration (demo_voice.py)

Video production only; not part of the product. Output: docs/video/ledgerline-demo.mp4
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "data" / "runtime" / "video"
OUT = ROOT / "docs" / "video" / "ledgerline-demo.mp4"
BASE = "http://localhost:8020"
W, H = 1920, 1080  # video size; the page is laid out at 1536x864 and rendered at 1.25x

OVERLAY_JS = """
() => {
  if (document.getElementById('ll-cap')) return;
  const st = document.createElement('style');
  st.textContent = `
    #ll-cap { position: fixed; left: 50%; bottom: 22px; transform: translateX(-50%); max-width: 1180px; z-index: 9998;
      background: rgba(17,32,31,.88); color: #fff; font: 600 21px/1.35 Inter, system-ui, sans-serif; padding: 12px 22px;
      border-radius: 14px; box-shadow: 0 8px 30px rgba(0,0,0,.25); transition: opacity .35s; text-align: center; }
    #ll-cap b { color: #f2b33d; }
    #ll-card { position: fixed; inset: 0; z-index: 9999; display: flex; flex-direction: column; align-items: center;
      justify-content: center; gap: 18px; background: #0f3d3a; color: #fff; text-align: center; transition: opacity .6s;
      font-family: Inter, system-ui, sans-serif; padding: 40px; }
    #ll-card h1 { font-size: 64px; margin: 0; letter-spacing: -1px; }
    #ll-card p { font-size: 26px; margin: 0; max-width: 980px; color: #d1fae5; line-height: 1.4; }
    #ll-card small { font-size: 17px; color: #a7f3d0; opacity: .9; }
    #ll-card .chips { display: flex; flex-wrap: wrap; gap: 10px; justify-content: center; max-width: 1000px; }
    #ll-card .chips span { background: rgba(255,255,255,.12); border-radius: 999px; padding: 8px 16px; font-size: 18px; }
    #ll-cursor { position: fixed; width: 22px; height: 22px; border-radius: 50%; background: rgba(242,179,61,.55);
      border: 2px solid #f2b33d; z-index: 9997; pointer-events: none; transform: translate(-50%,-50%); transition: all .25s; }
  `;
  document.head.appendChild(st);
  const cap = document.createElement('div'); cap.id = 'll-cap'; cap.style.opacity = 0; document.body.appendChild(cap);
  const cur = document.createElement('div'); cur.id = 'll-cursor'; cur.style.opacity = 0; document.body.appendChild(cur);
  document.addEventListener('mousemove', e => { cur.style.left = e.clientX + 'px'; cur.style.top = e.clientY + 'px'; cur.style.opacity = 1; });
}
"""


class Director:
    def __init__(self, page):
        self.page, self.t0, self.cues = page, time.monotonic(), []

    def now(self) -> float:
        return time.monotonic() - self.t0

    def cue(self, name: str) -> None:
        self.cues.append({"name": name, "t": round(self.now(), 2)})

    def overlay(self) -> None:
        self.page.evaluate(OVERLAY_JS)

    def caption(self, html: str | None) -> None:
        self.page.evaluate("""h => { const c = document.getElementById('ll-cap');
            if (!h) { c.style.opacity = 0; return; } c.innerHTML = h; c.style.opacity = 1; }""", html)

    def card(self, html: str | None) -> None:
        self.page.evaluate("""h => { let c = document.getElementById('ll-card');
            if (!h) { if (c) { c.style.opacity = 0; setTimeout(() => c.remove(), 700); } return; }
            if (!c) { c = document.createElement('div'); c.id = 'll-card'; document.body.appendChild(c); }
            c.innerHTML = h; c.style.opacity = 1; }""", html)

    def wait(self, s: float) -> None:
        self.page.wait_for_timeout(int(s * 1000))

    def go(self, hash_: str, caption: str | None = None) -> None:
        self.caption(None)
        self.page.evaluate("h => { location.hash = h; }", hash_)
        self.wait(1.0)
        if caption:
            self.caption(caption)

    def point(self, locator, click=False) -> None:
        box = locator.bounding_box()
        if box:
            self.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=12)
        self.wait(0.3)
        if click:
            locator.click()

    def scroll(self, dy: int, steps: int = 8, x: int = 720, y: int = 420) -> None:
        self.page.mouse.move(x, y)
        for _ in range(steps):
            self.page.mouse.wheel(0, dy / steps)
            self.wait(0.08)


def record() -> None:
    from playwright.sync_api import sync_playwright

    WORK.mkdir(parents=True, exist_ok=True)
    for f in WORK.glob("*.webm"):
        f.unlink()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1536, "height": 864}, device_scale_factor=1.25,
                                  record_video_dir=str(WORK), record_video_size={"width": W, "height": H})
        page = ctx.new_page()
        d = Director(page)
        page.goto(BASE + "/")
        page.wait_for_selector("text=Replay the run")
        d.overlay()

        # 1. hook
        d.card("<h1>Ledgerline</h1><p>The accounts-payable agent that checks every invoice before money moves</p>"
               "<small>Built during the Meta Global AI Developer Hackathon · Oct 26 – Nov 4, 2026</small>")
        d.wait(1.0)
        d.cue("hook")
        d.wait(7.6)
        d.card(None)
        d.wait(0.8)

        # 2. the pile
        d.cue("intro")
        d.caption("A month of paperwork for a (synthetic) Berlin coffee roaster: <b>32 documents</b>, PDFs, phone photos, "
                  "a stamped scan, emails, a <b>voice memo</b> and a <b>delivery photo</b>")
        d.scroll(500, steps=14, x=560)
        d.wait(2.5)
        d.scroll(-500, steps=8, x=560)
        d.point(page.get_by_role("button", name="10×"), click=True)
        d.wait(0.6)
        d.point(page.get_by_role("button", name=re.compile("Replay the run")), click=True)
        page.wait_for_url(re.compile(r"#/run/"))
        run_id = re.search(r"#/run/([0-9a-f]+)", page.url).group(1)

        # 3. live run
        d.caption("Replay of a <b>real recorded run</b>: every Muse Spark call with its latency, tokens and cost")
        d.wait(2.5)
        d.cue("read")
        d.wait(3.5)
        d.caption("<b>Muse Voice Transcribe</b> hears a staff voice memo · <b>SAM 3.1</b> counts the sacks in a delivery photo")
        page.wait_for_selector("text=The agent stopped for your approval", timeout=120_000)
        d.caption("Done: every document read, checked, <b>independently verified</b>, and the payment batch drafted")
        d.wait(3.5)

        st = page.request.get(f"{BASE}/api/runs/{run_id}").json()
        doc = {x["filename"]: x for x in st["docs"]}

        # 4. delivery photo + three-way match
        d.go(f"#/run/{run_id}/audit/{doc['Wareneingang_RGC_13-10.jpg']['doc_id']}", "Muse Spark decides <b>what</b> to count; <b>SAM 3.1</b> segments every sack: <b>9 × 60 kg</b>")
        d.wait(6.0)
        d.go(f"#/run/{run_id}/audit/{doc['RGC-1022.pdf']['doc_id']}", "The invoice bills 600 kg (10 sacks) → <b>held, €426 at risk</b>. Three-way match: PO ↔ invoice ↔ what arrived")
        d.wait(6.0)

        # 5. voice memo
        d.go(f"#/run/{run_id}/audit/{doc['Sprachmemo_Tom_Filiale-Mitte.wav']['doc_id']}", "A voice memo from the branch: <i>“only 28 cans of milk came, not 40”</i>")
        d.cue("memo_audio")
        d.wait(7.5)
        d.go(f"#/run/{run_id}/audit/{doc['IMG_4471.jpg']['doc_id']}", "→ the dairy invoice for 400 L is <b>held, €139.96 at risk</b>, and a German email asks for a credit note")
        d.wait(5.0)

        # 6. verification + fraud
        fraud = doc["Neue Bankverbindung - Rechnung KH-24-0958.eml"]
        d.go(f"#/run/{run_id}/audit/{fraud['doc_id']}")
        d.cue("verify")
        d.caption("A <b>second, independent Muse Spark pass</b> checks every claim against the original document")
        for c in (fraud.get("verification") or {}).get("claims", [])[:3]:
            loc = page.get_by_text(c["claim"][:40], exact=False).first
            if loc.count():
                d.point(loc)
                d.wait(1.0)
        d.wait(1.5)
        d.cue("fraud")
        d.caption("Sender <b>kaffe<u>i</u>mport-hansa.com</b>, one letter off, asks to pay a new Lithuanian IBAN → "
                  "<b>rejected</b>; the vendor's real contact gets a warning")
        d.wait(7.5)

        # 7. human approval + execution
        d.go(f"#/run/{run_id}/approvals")
        d.cue("approve")
        d.caption("It <b>stops</b>. A human approves every payment, email and exception")
        d.wait(2.0)
        d.scroll(600, steps=10)
        first_email = page.locator("text=to Jana Petersen").first
        if first_email.count():
            d.point(first_email, click=True)
            d.caption("Vendor emails drafted in the vendor's language, to the <b>known contact</b> from the vendor master")
            d.wait(4.0)
        d.scroll(-800, steps=8)
        for name in ("Approve all payments", "Approve all emails"):
            b = page.get_by_role("button", name=name)
            if b.count():
                d.point(b, click=True)
                d.wait(1.0)
        for x in [x for x in st["approval_items"] if x["kind"] == "escalation"]:
            card = page.locator("div.border-violet-200", has_text=x["payload"]["filename"]).first
            label = "Release for payment" if x["payload"]["filename"] == "IMG_4510.jpg" else "Don't pay"
            btn = card.get_by_role("button", name=label)
            if btn.count():
                d.scroll(300, steps=4)
                d.point(btn, click=True)
                d.wait(0.8)
        ex = page.get_by_role("button", name="Create SEPA file + outbox")
        d.point(ex, click=True)
        d.caption("Plain code, not the model, writes the <b>SEPA file</b> and the email outbox. Nothing is transmitted")
        d.wait(4.5)

        # 8. private mode
        d.go("#/")
        page.wait_for_selector("text=Replay the run")
        local = page.get_by_role("button", name=re.compile("Private · on this laptop"))
        d.point(local, click=True)
        d.cue("private")
        d.caption("<b>Private mode</b>: the same agent on <b>Muse Glimmer</b>, Meta's open-weight model, on this MacBook. "
                  "No document leaves the machine")
        d.wait(2.5)
        replay_btn = page.get_by_role("button", name=re.compile("Replay the run"))
        if replay_btn.is_enabled():
            d.point(page.get_by_role("button", name="10×"), click=True)
            d.point(replay_btn, click=True)
            d.wait(7.0)
        else:
            d.wait(4.0)

        # 9. results
        d.go(f"#/run/{run_id}/metrics")
        d.cue("close")
        d.caption("<b>12 / 12</b> planted problems stopped · 100% flag recall and precision · <b>€8,339</b> at risk · "
                  "about four hours saved · <b>$1.25</b> of model calls")
        d.wait(8.0)

        # 10. end card
        d.caption(None)
        d.card("<h1>Ledgerline</h1><p>Let the agent do the checking. You do the approving.</p>"
               "<div class='chips'><span>Muse Spark 1.3</span><span>Muse Voice Transcribe</span><span>SAM 3.1</span>"
               "<span>Muse Glimmer (on-device)</span><span>Muse Image (sample data)</span></div>"
               "<small>github.com/founder-sk-hub/ledgerline · synthetic demo data · built Oct 26 – Nov 4, 2026</small>")
        d.cue("end")
        d.wait(6.0)
        total = d.now()
        video = page.video.path()
        ctx.close()
        browser.close()
    (WORK / "cues.json").write_text(json.dumps({"cues": d.cues, "duration": round(total, 2), "video": str(video)},
                                               indent=1))
    print(json.dumps(d.cues), f"duration {total:.1f}s")


def assemble() -> None:
    meta = json.loads((WORK / "cues.json").read_text())
    cues = {c["name"]: c["t"] for c in meta["cues"]}
    inputs, filters, labels = ["-i", meta["video"]], [], []
    for name in ("hook", "intro", "read", "verify", "fraud", "approve", "private", "close"):
        clip = WORK / f"{name}.mp3"
        if name not in cues or not clip.exists():
            continue
        inputs += ["-i", str(clip)]
        k = len(inputs) // 2 - 1
        filters.append(f"[{k}:a]adelay={int(cues[name] * 1000)}:all=1,volume=1.0[a{k}]")
        labels.append(f"[a{k}]")
    memo = ROOT / "data" / "samples" / "batch" / "Sprachmemo_Tom_Filiale-Mitte.wav"
    if "memo_audio" in cues and memo.exists():
        inputs += ["-i", str(memo)]
        k = len(inputs) // 2 - 1
        filters.append(f"[{k}:a]atrim=0:7.2,afade=t=out:st=6.4:d=0.8,adelay={int(cues['memo_audio'] * 1000)}:all=1,"
                       f"volume=0.9[a{k}]")
        labels.append(f"[a{k}]")
    filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0,apad[aout]")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[aout]",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30",
           "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(OUT)]
    subprocess.run(cmd, check=True, capture_output=True)
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(OUT)],
                         capture_output=True, text=True).stdout.strip()
    print(f"wrote {OUT} ({float(dur):.1f}s, {OUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    {"record": record, "assemble": assemble}[sys.argv[1] if len(sys.argv) > 1 else "record"]()
