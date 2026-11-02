"""Record the demo video by driving the real app (replay of a recorded live run), with chapter cards,
camera zooms and captions, paced to the narration clips from demo_voice.py.

    .venv/bin/python backend/scripts/demo_video.py record     # needs the app on http://localhost:8020
    .venv/bin/python backend/scripts/demo_video.py assemble

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
VOICE = WORK / "v2"
OUT = ROOT / "docs" / "video" / "ledgerline-demo.mp4"
BASE = "http://localhost:8020"
VW, VH, DPR = 1280, 720, 1.5  # laid out at 1280x720, rendered at 1.5x -> 1920x1080 video
MEMO = ROOT / "data" / "samples" / "batch" / "Sprachmemo_Tom_Filiale-Mitte.wav"
MEMO_CUTS = [(0.0, 2.8), (8.7, 12.7)]  # "Hey, hier ist Tom..." + "Da sind nur achtundzwanzig Kannen gekommen, statt vierzig"

OVERLAY_JS = """
() => {
  if (document.getElementById('ll-cap')) return;
  const st = document.createElement('style');
  st.textContent = `
    #root { transition: transform .9s cubic-bezier(.2,.7,.2,1); transform-origin: 0 0; will-change: transform; }
    #ll-cap { position: fixed; left: 50%; bottom: 18px; transform: translateX(-50%); max-width: 1080px; z-index: 9998;
      background: rgba(17,32,31,.9); color: #fff; font: 600 22px/1.3 Inter, system-ui, sans-serif; padding: 12px 24px;
      border-radius: 14px; box-shadow: 0 10px 30px rgba(0,0,0,.25); transition: opacity .35s; text-align: center; }
    #ll-cap b { color: #f2b33d; }
    #ll-card { position: fixed; inset: 0; z-index: 9999; display: flex; flex-direction: column; align-items: center;
      justify-content: center; gap: 16px; background: radial-gradient(circle at 30% 20%, #1c5a54, #0f3d3a 60%);
      color: #fff; text-align: center; transition: opacity .5s; font-family: Inter, system-ui, sans-serif; padding: 40px; }
    #ll-card h1 { font-size: 64px; margin: 0; letter-spacing: -1.5px; }
    #ll-card h2 { font-size: 48px; margin: 0; letter-spacing: -1px; }
    #ll-card .n { font-size: 22px; font-weight: 700; color: #0f3d3a; background: #f2b33d; border-radius: 999px;
      width: 44px; height: 44px; display: flex; align-items: center; justify-content: center; }
    #ll-card p { font-size: 24px; margin: 0; max-width: 900px; color: #d1fae5; line-height: 1.4; }
    #ll-card small { font-size: 16px; color: #a7f3d0; }
    #ll-card .chips { display: flex; flex-wrap: wrap; gap: 10px; justify-content: center; max-width: 900px; }
    #ll-card .chips span { background: rgba(255,255,255,.12); border-radius: 999px; padding: 8px 16px; font-size: 18px; }
    #ll-cursor { position: fixed; width: 20px; height: 20px; border-radius: 50%; background: rgba(242,179,61,.55);
      border: 2px solid #f2b33d; z-index: 9997; pointer-events: none; transform: translate(-50%,-50%); transition: all .2s; }
  `;
  document.head.appendChild(st);
  for (const id of ['ll-cap', 'll-cursor']) { const e = document.createElement('div'); e.id = id; e.style.opacity = 0; document.body.appendChild(e); }
  document.addEventListener('mousemove', e => { const c = document.getElementById('ll-cursor'); c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; c.style.opacity = 1; });
  // "Camera": scale the app around an element and centre it, without showing past the app's edges.
  window.llFocus = (el, s) => {
    const root = document.getElementById('root');
    root.style.transform = '';
    if (!el || s === 1) return;
    el.scrollIntoView({block: 'center', inline: 'nearest'});
    const rr = root.getBoundingClientRect(), r = el.getBoundingClientRect();
    if (r.height < 4 || r.width < 4) return;  // nothing visible to zoom on
    const ex = r.left + r.width / 2 - rr.left, ey = r.top + r.height / 2 - rr.top;
    const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);
    const tx = clamp(innerWidth / 2 - rr.left - s * ex, innerWidth - rr.left - s * rr.width, -rr.left);
    const ty = clamp(innerHeight / 2 - rr.top - s * ey, innerHeight - rr.top - s * rr.height, -rr.top);
    requestAnimationFrame(() => { root.style.transform = `translate(${tx}px, ${ty}px) scale(${s})`; });
  };
}
"""


def clip_len(name: str) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                          str(VOICE / f"{name}.mp3")], capture_output=True, text=True).stdout.strip()
    return float(out)


class Director:
    def __init__(self, page):
        self.page, self.t0, self.cues = page, time.monotonic(), []

    def now(self) -> float:
        return time.monotonic() - self.t0

    def say(self, name: str) -> float:
        """Start a narration clip now; returns the time it ends."""
        self.cues.append({"name": name, "t": round(self.now(), 2)})
        return self.now() + (clip_len(name) if (VOICE / f"{name}.mp3").exists() else 0.0)

    def mark(self, name: str) -> None:
        self.cues.append({"name": name, "t": round(self.now(), 2)})

    def until(self, t_end: float) -> None:
        if t_end > self.now():
            self.wait(t_end - self.now())

    def overlay(self) -> None:
        self.page.evaluate(OVERLAY_JS)

    def caption(self, html: str | None) -> None:
        self.page.evaluate("""h => { const c = document.getElementById('ll-cap');
            if (!h) { c.style.opacity = 0; return; } c.innerHTML = h; c.style.opacity = 1; }""", html)

    def card(self, html: str | None) -> None:
        self.page.evaluate("""h => { let c = document.getElementById('ll-card');
            if (!h) { if (c) { c.style.opacity = 0; setTimeout(() => c.remove(), 600); } return; }
            if (!c) { c = document.createElement('div'); c.id = 'll-card'; document.body.appendChild(c); }
            c.innerHTML = h; c.style.opacity = 1; }""", html)

    def chapter(self, n: int, title: str, sub: str) -> None:
        self.caption(None)
        self.focus(None, settle=0.2)
        self.card(f"<div class='n'>{n}</div><h2>{title}</h2><p>{sub}</p>")
        self.wait(2.2)
        self.card(None)
        self.wait(0.5)

    def focus(self, locator, scale: float = 1.6, settle: float = 1.0) -> None:
        if locator is None:
            self.page.evaluate("() => window.llFocus(null, 1)")
        elif locator.count():
            locator.first.evaluate("(el, s) => window.llFocus(el, s)", scale)
        self.wait(settle)

    def wait(self, s: float) -> None:
        self.page.wait_for_timeout(int(s * 1000))

    def go(self, hash_: str, caption: str | None = None) -> None:
        self.caption(None)
        self.page.evaluate("() => { window.llFocus(null, 1); window.scrollTo(0, 0); }")
        self.page.evaluate("h => { location.hash = h; }", hash_)
        self.wait(0.9)
        if caption:
            self.caption(caption)

    def point(self, locator, click: bool = False) -> None:
        box = locator.bounding_box()
        if box:
            self.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=14)
        self.wait(0.3)
        if click:
            locator.click()

    def scroll(self, dy: int, steps: int = 10, x: int = 560, y: int = 400) -> None:
        self.page.mouse.move(x, y)
        for _ in range(steps):
            self.page.mouse.wheel(0, dy / steps)
            self.wait(0.06)


def record() -> None:
    from playwright.sync_api import sync_playwright

    WORK.mkdir(parents=True, exist_ok=True)
    for f in WORK.glob("*.webm"):
        f.unlink()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": VW, "height": VH}, device_scale_factor=DPR,
                                  record_video_dir=str(WORK), record_video_size={"width": 1920, "height": 1080})
        page = ctx.new_page()
        d = Director(page)
        page.goto(BASE + "/")
        page.wait_for_selector("text=Replay the run")
        d.overlay()
        btn = lambda name: page.get_by_role("button", name=name)  # noqa: E731
        section = lambda text: page.locator(f"text={text}").first.locator("xpath=ancestor::div[contains(@class,'rounded-xl')][1]")  # noqa: E731

        # Hook: the problem, in the founder's own voice
        d.card("<h1>Ledgerline</h1><p>An AI bookkeeper that checks every bill before money moves</p>"
               "<small>Built during the Meta Global AI Developer Hackathon · Oct 26 – Nov 4, 2026</small>")
        d.wait(0.8)
        end = d.say("hook")
        d.wait(5.5)
        d.card(None)
        d.wait(0.6)
        d.focus(section("Sample batch"), 1.3)
        d.caption("A month of bills for a Berlin coffee roaster: <b>32 documents</b> (synthetic demo data)")
        d.until(end + 0.3)

        # What it is
        d.focus(None, settle=0.3)
        end = d.say("intro")
        d.focus(page.locator("h1").first, 1.5)
        d.caption("Checks every bill against <b>your own records</b> · <b>never pays without you</b>")
        d.wait(4.5)
        d.focus(section("Engine"), 1.5)
        d.until(end + 0.2)

        d.chapter(1, "It reads everything", "PDFs, phone photos, scans, emails, voice memos")
        d.point(btn("10×"), click=True)
        d.point(btn(re.compile("Replay the run")), click=True)
        page.wait_for_url(re.compile(r"#/run/"))
        run_id = re.search(r"#/run/([0-9a-f]+)", page.url).group(1)
        end = d.say("read")
        d.caption("A <b>real recorded run</b> on Muse Spark 1.3 · every call with its latency, tokens and cost")
        d.wait(3.0)
        d.focus(page.locator("text=Documents read").first.locator("xpath=ancestor::div[contains(@class,'grid')][1]"), 1.35)
        d.wait(4.5)
        d.focus(page.locator("text=Documents").first.locator("xpath=.."), 1.35)
        d.until(end)
        page.wait_for_selector("text=The agent stopped for your approval", timeout=180_000)
        d.focus(None, settle=0.3)
        d.caption("Every document read, checked and <b>verified</b>; the payment batch is drafted")
        d.wait(2.5)

        st = page.request.get(f"{BASE}/api/runs/{run_id}").json()
        doc = {x["filename"]: x for x in st["docs"]}
        audit = lambda f: f"#/run/{run_id}/audit/{doc[f]['doc_id']}"  # noqa: E731

        d.chapter(2, "It checks against your books", "Purchase orders, contracts, VAT rules, payment history, what arrived")
        d.go(audit("Wareneingang_RGC_13-10.jpg"))
        end = d.say("sam")
        d.focus(page.locator("img[alt^='Wareneingang']"), 1.55)
        d.caption("<b>SAM 3.1</b> segments and counts every sack: <b>9 × 60 kg</b>")
        d.until(end - 7.5)
        d.go(audit("RGC-1022.pdf"), "The invoice bills <b>600 kg (10 sacks)</b> → <b>held</b>, €426 at risk")
        d.focus(section("Why did it do that?"), 1.5)
        d.until(end + 0.3)

        d.go(audit("Sprachmemo_Tom_Filiale-Mitte.wav"),
             "Voice memo from the café: <i>“Da sind nur achtundzwanzig Kannen gekommen, statt vierzig”</i>")
        d.focus(page.locator("audio").locator("xpath=.."), 1.6)
        d.mark("memo_audio")
        d.wait(sum(b - a for a, b in MEMO_CUTS) + 0.6)
        end = d.say("memo")
        d.caption("<b>Muse Voice Transcribe</b> turns it into evidence: 280 L received, 400 L invoiced")
        d.until(end - 6.0)
        d.go(audit("IMG_4471.jpg"), "The milk invoice is <b>held</b>: €139.96 at risk")
        d.focus(section("Why did it do that?"), 1.5)
        d.until(end + 0.3)

        d.chapter(3, "It catches what people miss", "Duplicates, price creep, wrong VAT, fake bank details")
        fraud = doc["Neue Bankverbindung - Rechnung KH-24-0958.eml"]
        d.go(audit("Neue Bankverbindung - Rechnung KH-24-0958.eml"))
        end = d.say("fraud")
        d.focus(page.locator("pre").first, 1.45)
        d.caption("From <b>kaffe<u>i</u>mport-hansa.com</b> (the real one is kaffee<u>import</u>-hansa.de), new Lithuanian IBAN")
        d.wait(5.5)
        d.focus(section("Why did it do that?"), 1.45)
        d.caption("→ <b>Rejected</b>. The warning goes to the supplier's <b>known</b> contact, not the sender")
        d.until(end + 0.2)
        end = d.say("verify")
        d.focus(section("Independent verification"), 1.45)
        d.caption("A <b>second, independent Muse Spark pass</b> checks every claim against the original")
        for c in (fraud.get("verification") or {}).get("claims", [])[:3]:
            loc = page.get_by_text(c["claim"][:40], exact=False).first
            if loc.count():
                d.point(loc)
                d.wait(0.8)
        d.until(end + 0.3)

        d.chapter(4, "You approve", "Nothing is paid or sent without a human")
        d.go(f"#/run/{run_id}/approvals")
        end = d.say("approve")
        d.focus(section("Payment batch"), 1.35)
        d.caption("SEPA batch, always to the IBAN in <b>your</b> vendor master · emails in the supplier's language")
        d.wait(3.5)
        d.focus(None, settle=0.4)
        for name in ("Approve all payments", "Approve all emails"):
            if btn(name).count():
                d.point(btn(name), click=True)
                d.wait(0.6)
        for x in [x for x in st["approval_items"] if x["kind"] == "escalation"]:
            card = page.locator("div.border-violet-200", has_text=x["payload"]["filename"]).first
            label = "Release for payment" if x["payload"]["filename"] == "IMG_4510.jpg" else "Don't pay"
            b = card.get_by_role("button", name=label)
            if b.count():
                b.scroll_into_view_if_needed()
                d.point(b, click=True)
                d.wait(0.4)
        page.evaluate("() => window.scrollTo({top: 0, behavior: 'smooth'})")
        d.wait(0.6)
        d.point(btn("Create SEPA file + outbox"), click=True)
        d.wait(0.6)
        d.focus(section("Execute"), 1.7)
        d.caption("Plain code writes the <b>SEPA file</b>. Nothing is transmitted without you")
        d.until(end + 1.5)

        d.go("#/")
        page.wait_for_selector("text=Replay the run")
        d.point(btn(re.compile("Private · on this laptop")), click=True)
        end = d.say("private")
        d.focus(section("Engine"), 1.55)
        d.caption("<b>Muse Glimmer</b>, Meta's open-weight model, on this MacBook: <b>no document leaves it</b>")
        d.wait(2.5)
        d.focus(None, settle=0.3)
        btn("10×").click()
        d.point(btn(re.compile("Replay the run")), click=True)
        d.wait(1.5)
        d.focus(page.locator("header"), 1.6)
        d.caption("Same agent, same tools: every call here ran on <b>muse-glimmer</b> on the laptop, $0 in API fees")
        d.until(end + 1.2)

        d.go(f"#/run/{run_id}/metrics")
        end = d.say("close")
        d.focus(page.locator("text=Time saved").first.locator("xpath=ancestor::div[contains(@class,'grid')][1]"), 1.25)
        d.caption("<b>12 / 12</b> problems stopped · <b>€8,339</b> protected · <b>6 min</b> · about <b>$1.25</b> of AI")
        d.wait(5.0)
        d.focus(section("Accuracy on the synthetic benchmark"), 1.3)
        d.until(end + 0.3)

        d.caption(None)
        d.focus(None, settle=0.2)
        d.card("<h1>Ledgerline</h1><p>Let the agent do the checking. You do the approving.</p>"
               "<div class='chips'><span>Muse Spark 1.3</span><span>Muse Voice Transcribe</span><span>SAM 3.1</span>"
               "<span>Muse Glimmer · on-device</span><span>Muse Image · sample data</span></div>"
               "<small>github.com/founder-sk-hub/ledgerline · try it: founder-sk-hub.github.io/ledgerline</small>")
        end = d.say("end")
        d.until(end + 2.5)
        total = d.now()
        video = page.video.path()
        ctx.close()
        browser.close()
    (WORK / "cues.json").write_text(json.dumps({"cues": d.cues, "duration": round(total, 2), "video": str(video)}, indent=1))
    print(json.dumps(d.cues), f"duration {total:.1f}s")


def assemble() -> None:
    meta = json.loads((WORK / "cues.json").read_text())
    inputs, filters, labels = ["-i", meta["video"]], [], []
    for cue in meta["cues"]:
        name, t = cue["name"], cue["t"]
        if name == "memo_audio":
            off = t
            for a, b in MEMO_CUTS:
                inputs += ["-i", str(MEMO)]
                k = len(inputs) // 2 - 1
                filters.append(f"[{k}:a]atrim={a}:{b},asetpts=PTS-STARTPTS,afade=t=out:st={b - a - 0.25}:d=0.25,"
                               f"adelay={int(off * 1000)}:all=1,volume=1.1[a{k}]")
                labels.append(f"[a{k}]")
                off += b - a
            continue
        clip = VOICE / f"{name}.mp3"
        if not clip.exists():
            continue
        inputs += ["-i", str(clip)]
        k = len(inputs) // 2 - 1
        filters.append(f"[{k}:a]adelay={int(t * 1000)}:all=1[a{k}]")
        labels.append(f"[a{k}]")
    filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11,apad[aout]")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[aout]",
           "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", "-r", "30",
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(OUT)]
    subprocess.run(cmd, check=True, capture_output=True)
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(OUT)],
                         capture_output=True, text=True).stdout.strip()
    print(f"wrote {OUT} ({float(dur):.1f}s, {OUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    {"record": record, "assemble": assemble}[sys.argv[1] if len(sys.argv) > 1 else "record"]()
