"""Short social cut for X: 1080x1920 (vertical) and 1080x1080 (square), real app footage only.

    .venv/bin/python backend/scripts/demo_social.py [vertical|square] [--stills]   # needs the app on :8020
    .venv/bin/python backend/scripts/demo_social.py --voice-only   # same cuts with only the voice memo

Video production only; not part of the product. Each format plays a fresh replay of the recorded Muse Spark run and
films one short shot per step with Playwright. Captions and red highlights are drawn on the page, so they are burned
in. The shots are cut together on a 120 BPM grid with a generated music bed and the real staff voice memo.
`--stills` saves one frame per shot instead (for checking the framing).
Output: docs/video/ledgerline-x-vertical.mp4, docs/video/ledgerline-x-square.mp4
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "data" / "runtime" / "video" / "social"
OUT = ROOT / "docs" / "video"
BASE = "http://localhost:8020"
MEMO = ROOT / "data" / "samples" / "batch" / "Sprachmemo_Tom_Filiale-Mitte.wav"
MEMO_CUT = (6.8, 9.9)  # "Da sind nur achtundzwanzig Kannen gekommen, statt vierzig"
# Filmed at 1440 px wide, where the app uses its desktop layout, then scaled down to the output size.
FORMATS = {"vertical": ((1440, 2560), (1080, 1920)), "square": ((1440, 1440), (1080, 1080))}
SR = 48000
# Shot lengths in seconds, all whole beats at 120 BPM so every cut lands on the beat.
LENGTHS = {"hook": 2.0, "sam": 2.5, "invoice": 2.5, "flag": 2.5, "memo": 4.0, "milk": 2.5, "waiting": 3.0,
           "held": 2.5, "email": 3.0, "approve": 2.5, "export": 3.0, "end": 3.5}
STARTS = dict(zip(LENGTHS, np.cumsum([0.0, *LENGTHS.values()])[:-1].tolist()))
TOTAL = sum(LENGTHS.values())

OVERLAY_JS = """
(fmt) => {
  if (window.scFit) return;
  const V = fmt === 'vertical', u = innerWidth / 1080, px = n => `${n * u}px`;  // sizes are given for 1080 wide
  const st = document.createElement('style');
  st.textContent = `
    html, body { overflow: hidden !important; background: #f5f5f0; }
    #root { width: 1280px; position: relative; transform-origin: 0 0; }
    /* the app's one-line replay notice runs off both edges when zoomed; #sc-tag says the same at frame width */
    header > div.border-t { display: none !important; }
    #sc-cap { position: fixed; left: 50%; transform: translateX(-50%); z-index: 9998; text-align: center;
      bottom: ${px(V ? 250 : 52)}; width: max-content; max-width: ${px(V ? 960 : 1000)}; box-sizing: border-box;
      background: rgba(15,28,27,.94); color: #fff; font: 800 ${px(V ? 58 : 44)}/1.18 Inter, system-ui, sans-serif;
      letter-spacing: -.5px; padding: ${V ? px(26) + ' ' + px(38) : px(18) + ' ' + px(30)}; border-radius: ${px(28)};
      box-shadow: 0 ${px(18)} ${px(50)} rgba(0,0,0,.3); }
    #sc-cap:empty, #sc-tag:empty { display: none; }
    #sc-cap b { color: #f5b83d; } #sc-cap em { color: #ff6b5e; font-style: normal; } #sc-cap i { font-weight: 700; }
    #sc-tag { position: fixed; top: ${px(V ? 56 : 24)}; left: 50%; transform: translateX(-50%); z-index: 9998;
      font: 600 ${px(V ? 28 : 22)} Inter, system-ui, sans-serif; color: #33413f; background: rgba(255,255,255,.9);
      padding: ${px(10)} ${px(24)}; border-radius: 999px; white-space: nowrap; box-shadow: 0 4px 14px rgba(0,0,0,.12); }
    #sc-full { position: fixed; inset: 0; z-index: 9999; display: none; flex-direction: column; align-items: center;
      justify-content: center; text-align: center; font-family: Inter, system-ui, sans-serif; color: #fff;
      padding: ${px(60)}; box-sizing: border-box; }
    #sc-full.flash { display: flex; background: #ff0000; }
    #sc-full.hook { display: flex; background: rgba(8,18,17,.6); }
    #sc-full.hook div { font-size: ${px(V ? 150 : 120)}; font-weight: 900; letter-spacing: -${px(4)}; line-height: 1.04;
      text-shadow: 0 6px 30px rgba(0,0,0,.45); }
    #sc-full.hook .b { color: #ff6b5e; }
    #sc-full.end { display: flex; background: rgba(12,52,48,.95); backdrop-filter: blur(8px); gap: ${px(V ? 34 : 22)}; }
    #sc-full.end h1 { font-size: ${px(V ? 150 : 118)}; margin: 0; letter-spacing: -${px(4)}; font-weight: 800; }
    #sc-full.end p { font-size: ${px(V ? 56 : 44)}; margin: 0; line-height: 1.25; color: #d1fae5; font-weight: 600;
      max-width: 900px; }
    #sc-full.end .h { font-family: 'JetBrains Mono', ui-monospace, monospace; font-weight: 700; color: #fff; }
    #sc-full.end .url { font-size: ${px(V ? 44 : 36)}; font-weight: 700; color: #0f3d3a; background: #f5b83d;
      border-radius: 999px; padding: ${V ? px(18) + ' ' + px(34) : px(14) + ' ' + px(28)}; }
    .sc-mark { position: absolute; border-style: solid; border-color: #ef4444; pointer-events: none; z-index: 50;
      box-sizing: border-box; opacity: 0; }
    .sc-mark.on { animation: scpop .35s ease-out forwards; }
    @keyframes scpop { from { opacity: 0; transform: scale(1.12); } to { opacity: 1; transform: scale(1); } }
    #sc-cur { position: fixed; width: ${px(64)}; height: ${px(64)}; margin: -${px(32)} 0 0 -${px(32)}; border-radius: 50%; z-index: 9997;
      pointer-events: none; border: ${px(5)} solid #f5b83d; background: rgba(245,184,61,.3); opacity: 0;
      transition: transform .12s; }
    #sc-cur.tap { transform: scale(.7); }
  `;
  document.head.appendChild(st);
  for (const id of ['sc-cap', 'sc-tag', 'sc-full', 'sc-cur']) {
    const e = document.createElement('div'); e.id = id; document.body.appendChild(e);
  }
  const cur = document.getElementById('sc-cur');
  document.addEventListener('mousemove', e => { cur.style.left = e.clientX + 'px'; cur.style.top = e.clientY + 'px'; });
  document.addEventListener('mousedown', () => cur.classList.add('tap'));
  document.addEventListener('mouseup', () => cur.classList.remove('tap'));
  // a target is an element, or {el, from, to} for a run of text inside it
  const rangeOf = t => {
    const w = document.createTreeWalker(t.el, NodeFilter.SHOW_TEXT);
    for (let n; (n = w.nextNode());) {
      const i = n.data.indexOf(t.from);
      if (i < 0) continue;
      const j = t.to ? n.data.indexOf(t.to, i) : -1, r = document.createRange();
      r.setStart(n, i); r.setEnd(n, j >= 0 ? j + t.to.length : i + t.from.length);
      return r;
    }
    return null;
  };
  const rectOf = t => t.el ? (rangeOf(t) || t.el).getBoundingClientRect() : t.getBoundingClientRect();
  const linesOf = t => {  // one rect per line of a text run, so a highlight hugs the words
    const r = t.el && rangeOf(t);
    if (!r) return [rectOf(t)];
    const out = [];
    for (const c of r.getClientRects()) {
      const l = out.find(o => Math.abs(o.top - c.top) < 3);
      if (l) { l.left = Math.min(l.left, c.left); l.right = Math.max(l.right, c.right); l.bottom = Math.max(l.bottom, c.bottom); }
      else out.push({left: c.left, top: c.top, right: c.right, bottom: c.bottom});
    }
    return out;
  };
  window.scSet = (cap, full, cursor) => {
    document.getElementById('sc-cap').innerHTML = cap || '';
    const f = document.getElementById('sc-full');
    f.className = full ? full.kind : ''; f.innerHTML = full ? full.html : '';
    document.getElementById('sc-tag').textContent = full ? '' : 'Real app · recorded Muse Spark run · synthetic demo data';
    cur.style.opacity = cursor ? 1 : 0;
  };
  // "Camera": frame the targets in the upper part of the picture (captions sit below), optionally from slightly
  // wider so scGo can push in during the shot. Positions are measured in the app's own, unscaled layout.
  window.scFit = (targets, marks, o) => {
    const root = document.getElementById('root');
    root.style.transition = 'none'; root.style.transform = 'none'; root.style.width = (o.width || 1280) + 'px';
    window.scrollTo(0, 0);
    document.querySelectorAll('.sc-mark').forEach(m => m.remove());
    const rr = root.getBoundingClientRect();
    const box = (list, of = rectOf) => {
      let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
      for (const t of list) {
        const r = of(t);
        x0 = Math.min(x0, r.left - rr.left); y0 = Math.min(y0, r.top - rr.top);
        x1 = Math.max(x1, r.right - rr.left); y1 = Math.max(y1, r.bottom - rr.top);
      }
      return {x0, y0, x1, y1};
    };
    const W = innerWidth, H = innerHeight, V = H > W * 1.2, b = box(targets), pad = (o.pad ?? 44) * W / 1080;
    const fit = [(W - 2 * pad) / (b.x1 - b.x0), H * (V ? 0.56 : 0.6) / (b.y1 - b.y0)];
    const S = o.cover ? Math.max(W / (b.x1 - b.x0), H / (b.y1 - b.y0)) : Math.min(...fit, (o.max ?? 3.2) * W / 1080);
    const cx = (b.x0 + b.x1) / 2, cy = (b.y0 + b.y1) / 2, ay = o.cover ? H / 2 : H * (V ? 0.43 : 0.42);
    for (const line of marks.flatMap(linesOf)) {
      const r = box([line], x => x), e = document.createElement('div'), g = 8 * u / S;
      e.className = 'sc-mark';
      Object.assign(e.style, {left: (r.x0 - g) + 'px', top: (r.y0 - g) + 'px', width: (r.x1 - r.x0 + 2 * g) + 'px',
        height: (r.y1 - r.y0 + 2 * g) + 'px', borderWidth: (6 * u / S) + 'px', borderRadius: (14 * u / S) + 'px',
        boxShadow: `0 0 0 ${5 * u / S}px rgba(239,68,68,.22)`});
      root.appendChild(e);
    }
    const at = k => `translate(${W / 2 - S * k * cx}px, ${ay - S * k * cy}px) scale(${S * k})`;
    window.__sc = {at, push: o.push};
    root.style.transform = at(o.push ? 0.93 : 1);
    void root.offsetWidth;
  };
  window.scGo = sec => {
    const root = document.getElementById('root'), f = window.__sc;
    if (f && f.push && sec) { root.style.transition = `transform ${sec}s cubic-bezier(.3,.1,.3,1)`; root.style.transform = f.at(1); }
    document.querySelectorAll('.sc-mark').forEach(m => m.classList.add('on'));
  };
}
"""


class Camera:
    def __init__(self, page, stills: Path | None):
        self.page, self.stills, self.t0, self.shots = page, stills, time.monotonic(), []

    def now(self) -> float:
        return time.monotonic() - self.t0

    def wait(self, s: float) -> None:
        if s > 0:
            self.page.wait_for_timeout(int(s * 1000))

    def go(self, hash_: str, ready: str) -> None:
        self.page.evaluate("h => { location.hash = h; }", hash_)
        self.page.wait_for_selector(ready)
        self.page.wait_for_function("() => [...document.images].every(i => i.complete)")
        self.wait(0.3)

    def shot(self, name: str, caption: str | None, frame: list, marks: list = (), *, full: dict | None = None,
             push: bool = True, width: int | None = None, max_zoom: float | None = None, cover: bool = False,
             cursor: bool = False, action=None) -> None:
        dur = LENGTHS[name]
        p = self.page
        p.evaluate("([c, f, k]) => scSet(c, f, k)", [caption, full, cursor])
        p.evaluate("([t, m, o]) => scFit(t, m, o)",
                   [frame, list(marks), {"push": push and not self.stills, "width": width, "max": max_zoom, "cover": cover}])
        self.wait(0.45)
        if self.stills:
            p.evaluate("() => scGo(0)")
            self.wait(0.4)
            if action:
                action()
                self.wait(0.6)
            p.screenshot(path=str(self.stills / f"{len(self.shots):02d}-{name}.png"))
            self.shots.append((name, 0.0, dur))
            return
        t = self.now()
        p.evaluate("d => scGo(d)", dur)
        if action:
            action()
        self.wait(t + dur + 0.15 - self.now())
        self.shots.append((name, round(t, 3), dur))

    def tap(self, locator) -> None:
        """Move the visible cursor to a button and click it (plain mouse events: no auto-scrolling)."""
        b = locator.bounding_box()
        x, y = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
        self.page.mouse.move(x + 340, y + 300)
        self.page.mouse.move(x, y, steps=18)
        self.wait(0.15)
        self.page.mouse.click(x, y)


def film(fmt: str, stills: bool) -> tuple[Path | None, list, float]:
    from playwright.sync_api import sync_playwright

    (W, H), _ = FORMATS[fmt]
    WORK.mkdir(parents=True, exist_ok=True)
    still_dir = WORK / f"stills-{fmt}" if stills else None
    if still_dir:
        still_dir.mkdir(exist_ok=True)
    vid_dir = WORK / f"raw-{fmt}"
    vid_dir.mkdir(exist_ok=True)
    for f in vid_dir.glob("*.webm"):
        f.unlink()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        rec = {} if stills else {"record_video_dir": str(vid_dir), "record_video_size": {"width": W, "height": H}}
        ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=1, **rec)
        page = ctx.new_page()
        cam = Camera(page, still_dir)
        api = page.request

        # a fresh replay of the recorded run, played at full speed off camera
        run_id = api.post(f"{BASE}/api/runs", data={"mode": "replay", "replay_id": "meta-sample", "speed": 1000}).json()["run_id"]
        for _ in range(240):
            st = api.get(f"{BASE}/api/runs/{run_id}").json()
            if st["run"]["status"] == "awaiting_approval":
                break
            time.sleep(0.25)
        doc = {d["filename"]: d["doc_id"] for d in st["docs"]}
        audit = lambda f: f"#/run/{run_id}/audit/{doc[f]}"  # noqa: E731

        page.goto(BASE + "/")
        page.wait_for_selector("text=Replay the run")
        page.evaluate(OVERLAY_JS, fmt)
        flash = 0.0
        if not stills:  # sync mark: one red frame tells assemble() where director time sits in the video
            page.evaluate("() => scSet(null, {kind: 'flash', html: ''}, false)")
            flash = cam.now()
            cam.wait(0.4)
        why = lambda: page.get_by_text("Why did it do that?").first.locator("xpath=..")  # noqa: E731
        flag = lambda text: page.locator("div.rounded-lg.bg-paper", has_text=text).first  # noqa: E731

        cam.go(audit("Wareneingang_RGC_13-10.jpg"), "img[alt^='Wareneingang']")
        photo = page.locator("img[alt^='Wareneingang']").first
        cam.shot("hook", None, [photo.element_handle()], cover=True,
                 full={"kind": "hook", "html": "<div>10 sacks billed.</div><div class='b'>9 arrived.</div>"})
        cam.shot("sam", "<b>SAM 3.1</b> counts the delivery photo: <b>9&nbsp;sacks</b>",
                 [photo.element_handle(), page.get_by_text("counted 9").first.element_handle()])

        cam.go(audit("RGC-1022.pdf"), "text=What Muse Spark read")
        read = page.get_by_text("What Muse Spark read").first.locator("xpath=ancestor::div[contains(@class,'rounded-xl')][1]")
        cells = [read.locator("tr").first.locator("th").nth(i) for i in (0, 1)]
        cells += [read.locator("tr", has_text="60 kg bags").first.locator("td").nth(i) for i in (0, 1)]
        cam.shot("invoice", "<b>Muse Spark</b> reads the bill: <b>600&nbsp;kg = 10&nbsp;sacks</b>",
                 [c.element_handle() for c in cells], [cells[3].element_handle()], max_zoom=3.0)
        cam.shot("flag", "Bill and photo don't match: <em>€426&nbsp;held</em>",
                 [why().element_handle(), flag("Short delivery").element_handle()],
                 [flag("Short delivery").element_handle()])

        cam.go(audit("Sprachmemo_Tom_Filiale-Mitte.wav"), "audio")
        player = page.locator("audio").first.locator("xpath=..")
        said = page.get_by_text("Hey, hier ist Tom").first
        page.locator("audio").first.evaluate("a => { a.muted = true; a.currentTime = 6.8; }")
        cam.shot("memo", "Café staff voice note on the milk, transcribed by <b>Muse Voice Transcribe</b>:"
                         "<br><i>“Only 28&nbsp;cans came, not&nbsp;40”</i>",
                 [player.element_handle(), said.element_handle()],
                 [{"el": said.element_handle(), "from": "Da sind nur", "to": "statt 40"}],
                 action=lambda: page.locator("audio").first.evaluate("a => a.play().catch(() => {})"))

        cam.go(audit("IMG_4471.jpg"), "text=Why did it do that?")
        cam.shot("milk", "The milk bill is <em>held</em> too: €139.96",
                 [why().element_handle(), flag("Short delivery").element_handle()],
                 [flag("Short delivery").element_handle()])

        cam.go(f"#/run/{run_id}/approvals", "text=Held or rejected by the agent")
        export = page.get_by_text("Create export").first.locator("xpath=..")
        cam.shot("waiting", "<b>Waiting for your OK.</b><br>Nothing paid. Nothing sent.", [export.element_handle()],
                 max_zoom=2.6)
        held = page.get_by_text("Held or rejected by the agent").first.locator("xpath=..")
        row = lambda f: held.locator("button", has_text=f).first  # noqa: E731
        cam.shot("held", "Short bills stay <em>out of the payment run</em>", [held.element_handle()],
                 [row("RGC-1022.pdf").element_handle(), row("IMG_4471.jpg").element_handle()], max_zoom=2.6)

        # Off camera: decide everything except the coffee supplier's correction email, which is approved on camera.
        for it in st["approval_items"]:
            if it["item"] == "email:E04":
                continue
            ok = it["kind"] != "escalation" or it["payload"]["filename"] == "IMG_4510.jpg"
            api.post(f"{BASE}/api/runs/{run_id}/approvals",
                     data={"item": it["item"], "decision": "approved" if ok else "rejected"})
        page.reload()
        page.wait_for_selector("text=Vendor emails")
        page.evaluate(OVERLAY_JS, fmt)
        card = page.locator("div.rounded-lg.border.border-line", has_text="RGC-1022 and RGC-1047").last
        card.locator("button").first.evaluate("b => b.click()")  # DOM click: the card may be off camera
        page.wait_for_selector("pre")
        head = card.locator("div").first
        body = {"el": card.locator("pre").first.element_handle(), "from": "1. Invoice RGC-1022", "to": "missing bag."}
        counted = {**body, "from": "we counted only 9 bags", "to": None}
        cam.shot("email", "It asks the supplier for a <b>corrected invoice</b>: 9&nbsp;sacks, not&nbsp;10",
                 [head.element_handle(), body], [counted], width=900, max_zoom=2.6)
        cam.shot("approve", "<b>You approve.</b>", [head.element_handle(), body], push=False, width=900, max_zoom=2.6,
                 cursor=True, action=lambda: cam.tap(card.get_by_role("button", name="Approve")))

        export = page.get_by_text("Create export").first.locator("xpath=..")
        cam.shot("export", "Payment file ready. The&nbsp;€426 is&nbsp;<b>not</b>&nbsp;paid.", [export.element_handle()],
                 push=False, max_zoom=2.4, cursor=True,
                 action=lambda: (cam.tap(page.get_by_role("button", name="Create SEPA file + outbox")),
                                 page.wait_for_selector("text=Export created")))
        cam.shot("end", None, [export.element_handle()], push=False, max_zoom=2.4,
                 full={"kind": "end", "html": "<h1>Ledgerline</h1><p>built solo for the <span class='h'>@AIatMeta</span> hackathon</p>"
                                               "<div class='url'>founder-sk-hub.github.io/ledgerline</div>"})
        video = None if stills else Path(page.video.path())
        ctx.close()
        browser.close()
    return video, cam.shots, flash


# ---------------------------------------------------------------- audio: generated music bed + the real voice memo
def music(rng: np.random.Generator) -> np.ndarray:
    """An upbeat 120 BPM pop/house loop (C-G-Am-F), synthesised here so it has no licence strings attached."""
    n = int((TOTAL + 1.5) * SR)
    drums, keys, bass, fx = (np.zeros((n, 2)) for _ in range(4))
    groove = (STARTS["sam"], STARTS["end"])  # full beat from the first cut to the end card

    def put(buf, x, at, pan=0.0):
        i = int(at * SR)
        x = x[: max(0, n - i)]
        buf[i:i + len(x), 0] += x * (1 - max(pan, 0))
        buf[i:i + len(x), 1] += x * (1 + min(pan, 0))

    def env(d, tau, attack=0.004):
        t = np.arange(int(d * SR)) / SR
        e = np.exp(-t / tau)
        k = max(1, int(attack * SR))
        e[:k] *= np.linspace(0, 1, k)
        e[-int(0.01 * SR):] *= np.linspace(1, 0, int(0.01 * SR))
        return e, t

    def tone(midi, d, tau, cut, odd=False, detune=(0.0,)):
        e, t = env(d, tau)
        x = np.zeros_like(t)
        for c in detune:
            f = 440 * 2 ** ((midi - 69 + c / 100) / 12)
            for k in range(1, int(min(40, 14000 / f)) + 1):
                if odd and k % 2 == 0:
                    continue
                x += np.sin(2 * np.pi * k * f * t + rng.uniform(0, 2 * np.pi)) / k / np.sqrt(1 + (k * f / cut) ** 4)
        return x * e / len(detune)

    def noise(d, tau, hp=1, attack=0.001):
        x = rng.normal(0, 1, int(d * SR))
        for _ in range(hp):
            x = np.diff(x, prepend=0.0)
        return x * env(d, tau, attack)[0]

    def kick():
        e, t = env(0.38, 0.2, 0.001)
        ph = 2 * np.pi * np.cumsum(46 + 120 * np.exp(-t / 0.032)) / SR
        return np.sin(ph) * e

    chords = [(48, (60, 64, 67)), (43, (59, 62, 67)), (45, (60, 64, 69)), (41, (60, 65, 69))]  # C G Am F
    kicks = []
    put(drums, kick() * 1.0, 0.0)  # the hook: one hit, then a riser into the first cut
    put(bass, tone(36, 1.6, 0.6, 500, odd=True) * 0.5, 0.0)
    rise = int(STARTS["sam"] * SR)
    r = noise(STARTS["sam"], 99.0, hp=1) * np.linspace(0, 1, rise) ** 2.2 * 0.07
    put(fx, r, 0.0, 0.0)
    for bar, t0 in enumerate(np.arange(*groove, 2.0)):
        root, triad = chords[bar % 4]
        for b in range(4):
            tb = t0 + b * 0.5
            put(drums, kick(), tb)
            kicks.append(tb)
            put(drums, noise(0.06, 0.018, hp=2) * 0.11, tb + 0.25, 0.25)  # off-beat hat
            for s in (0.125, 0.375):
                put(drums, noise(0.04, 0.01, hp=2) * 0.045, tb + s, 0.3)
            if b in (1, 3):
                clap = sum(noise(0.2, 0.06, hp=1) * (0.5 if j < 2 else 1) for j in range(1)) * 0.22
                for j, dt in enumerate((0.0, 0.011, 0.022)):
                    put(drums, noise(0.012, 0.004, hp=1) * 0.12, tb + dt)
                put(drums, clap, tb + 0.03)
            for e8 in (0.0, 0.25):
                put(bass, tone(root + (12 if e8 else 0), 0.24, 0.12, 900, odd=True) * 0.42, tb + e8)
            for m in triad:  # off-beat chord stabs
                put(keys, tone(m, 0.22, 0.09, 2600, detune=(-8, 8)) * 0.13, tb + 0.25, -0.2 + 0.2 * (m % 3))
            if t0 >= STARTS["waiting"] - 0.01:  # second half: add a plucked arpeggio
                arp = [triad[0] + 12, triad[1] + 12, triad[2] + 12, triad[1] + 12]
                for s in range(2):
                    put(keys, tone(arp[(b * 2 + s) % 4], 0.16, 0.06, 4200) * 0.07, tb + s * 0.25, 0.35)
        if bar % 4 == 3 or t0 + 2.0 >= STARTS["waiting"] > t0:  # snare fill into the next phrase
            for s in range(4):
                put(drums, noise(0.08, 0.03, hp=1) * (0.07 + 0.03 * s), t0 + 1.5 + s * 0.125)
    for at in (STARTS["sam"], STARTS["waiting"], STARTS["end"]):
        put(fx, noise(1.6, 0.5, hp=2) * 0.05, at)  # crash
    put(drums, kick(), STARTS["end"])
    for m in (48, 60, 64, 67, 72):  # final chord rings over the end card
        put(keys, tone(m, 3.4, 1.1, 2200, detune=(-6, 6)) * 0.1, STARTS["end"])

    # sidechain pump on everything tonal, then a small room on the keys and claps
    pump = np.ones(n)
    for tk in kicks:
        i = int(tk * SR)
        seg = np.arange(min(int(0.5 * SR), n - i)) / SR
        pump[i:i + len(seg)] = np.minimum(pump[i:i + len(seg)], 1 - 0.5 * np.exp(-seg / 0.11))
    tonal = (keys + bass) * pump[:, None]
    ir_t = np.arange(int(1.1 * SR)) / SR
    wet = np.zeros_like(keys)
    for ch in range(2):
        ir = rng.normal(0, 1, len(ir_t)) * np.exp(-ir_t / 0.32)
        ir = np.convolve(ir, np.ones(24) / 24, mode="same")
        ir /= np.sqrt((ir ** 2).sum())
        size = 1 << int(np.ceil(np.log2(n + len(ir))))
        src = keys[:, ch] + drums[:, ch] * 0.35
        wet[:, ch] = np.fft.irfft(np.fft.rfft(src, size) * np.fft.rfft(ir, size), size)[:n] * 0.22
    mix = drums + tonal + fx + wet
    mix = np.tanh(1.3 * mix / np.abs(mix).max()) / np.tanh(1.3)
    return mix[: int(TOTAL * SR)]


VOICE_AT = STARTS["memo"] + 0.25  # where the memo excerpt starts in the cut


def memo_clip() -> np.ndarray:
    """The staff voice memo excerpt (mono, SR), levelled to about -14 dBFS RMS."""
    with wave.open(str(MEMO)) as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(float) / 32768
    x = x[int(MEMO_CUT[0] * sr): int(MEMO_CUT[1] * sr)]
    x = np.interp(np.arange(int(len(x) * SR / sr)) * sr / SR, np.arange(len(x)), x)
    k = int(0.03 * SR)
    x[:k] *= np.linspace(0, 1, k)
    x[-k:] *= np.linspace(1, 0, k)
    x *= 10 ** (-14 / 20) / np.sqrt((x[np.abs(x) > 0.01] ** 2).mean())
    return x * min(1.0, 0.95 / np.abs(x).max())  # keep the peaks under full scale


def voice() -> np.ndarray:
    """A full-length track that is silent except for the memo excerpt under the memo shot."""
    out, x = np.zeros((int(TOTAL * SR), 2)), memo_clip()
    i = int(VOICE_AT * SR)
    out[i:i + len(x)] += x[:, None]
    return out


def soundtrack() -> np.ndarray:
    mix = music(np.random.default_rng(7))
    mix *= 10 ** (-19 / 20) / np.sqrt((mix ** 2).mean())  # music bed around -19 dBFS RMS
    # duck the music under the voice memo, then lay the memo on top, clearly louder
    t = np.arange(len(mix)) / SR
    a, b = STARTS["memo"] + 0.05, STARTS["memo"] + LENGTHS["memo"] - 0.2
    gain = np.interp(t, [0, a - 0.12, a, b, b + 0.25, TOTAL], [1, 1, 0.22, 0.22, 1, 1])
    mix = mix * gain[:, None] + voice()
    fade = int(0.5 * SR)
    mix[-fade:] *= np.linspace(1, 0, fade)[:, None]
    return np.clip(mix, -0.99, 0.99)


def voice_only(fmt: str) -> Path:
    """Same picture with only the voice memo, for adding your own music in an editor."""
    src, track = OUT / f"ledgerline-x-{fmt}.mp4", WORK / "voice.wav"
    write_wav(track, voice())
    out = OUT / f"ledgerline-x-{fmt}-voice-only.mp4"
    subprocess.run(["ffmpeg", "-y", "-i", str(src), "-i", str(track), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)], check=True, capture_output=True)
    return out


def write_wav(path: Path, x: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


def flash_time(video: Path) -> float:
    """Video time of the first red sync frame."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-t", "6", "-i", str(video), "-vf", "scale=4:4,format=rgb24",
                          "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    px = np.frombuffer(raw, np.uint8).reshape(-1, 16, 3).mean(axis=1)
    i = int(np.argmax((px[:, 0] > 200) & (px[:, 1] < 70) & (px[:, 2] < 70)))
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=r_frame_rate",
                            "-of", "csv=p=0", str(video)], capture_output=True, text=True).stdout.strip()
    num, den = (float(v) for v in probe.split("/"))
    return i * den / num


def assemble(fmt: str, video: Path, shots: list, flash: float, audio: Path) -> Path:
    off = flash_time(video) - flash  # video time = director time + off
    parts, labels = [], ""
    for i, (_, t, dur) in enumerate(shots):
        s = t + off + 0.04
        parts.append(f"[0:v]trim={s:.3f}:{s + dur:.3f},setpts=PTS-STARTPTS[v{i}]")
        labels += f"[v{i}]"
    w, h = FORMATS[fmt][1]
    flt = ";".join(parts) + f";{labels}concat=n={len(shots)}:v=1:a=0,fps=30,scale={w}:{h}:flags=lanczos[v]"
    out = OUT / f"ledgerline-x-{fmt}.mp4"
    subprocess.run(["ffmpeg", "-y", "-i", str(video), "-i", str(audio), "-filter_complex", flt, "-map", "[v]",
                    "-map", "1:a", "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-t", f"{TOTAL:.2f}", "-movflags", "+faststart", str(out)],
                   check=True, capture_output=True)
    return out


if __name__ == "__main__":
    stills = "--stills" in sys.argv
    fmts = [a for a in sys.argv[1:] if a in FORMATS] or list(FORMATS)
    if "--voice-only" in sys.argv:  # re-mux the finished cuts with the memo alone, plus the memo clip itself
        WORK.mkdir(parents=True, exist_ok=True)
        for fmt in fmts:
            print(f"wrote {voice_only(fmt)}")
        clip = OUT / "voice-memo-excerpt.wav"
        write_wav(clip, np.repeat(memo_clip()[:, None], 2, axis=1))
        print(f"wrote {clip} (starts at {VOICE_AT:.2f}s in the cut)")
        sys.exit()
    audio = WORK / "soundtrack.wav"
    if not stills:
        WORK.mkdir(parents=True, exist_ok=True)
        write_wav(audio, soundtrack())
    for fmt in fmts:
        video, shots, flash = film(fmt, stills)
        if stills:
            print(f"{fmt}: stills in {WORK / f'stills-{fmt}'}")
            continue
        out = assemble(fmt, video, shots, flash, audio)
        (WORK / f"shots-{fmt}.json").write_text(json.dumps({"shots": shots, "flash": flash}, indent=1))
        print(f"wrote {out} ({TOTAL:.1f}s)")
