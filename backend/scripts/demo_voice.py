"""Generate the demo-video narration with ElevenLabs (video production only, not part of the product).

    .venv/bin/python backend/scripts/demo_voice.py      # needs ELEVENLABS_API_KEY in .env (TTS-only key)
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "runtime" / "video"
MAX_CHARS = 850  # hard guard on credits (Flash v2.5 bills ~0.5 credit per character)
VOICE = "JBFqnCBsd6RMkjVDRZzb"  # George

load_dotenv(ROOT / ".env")
spec = json.loads((ROOT / "docs" / "video" / "narration.json").read_text())
lines = [l for l in spec["lines"] if not (OUT / f"{l['id']}.mp3").exists()]
total = sum(len(l["text"]) for l in lines)
if total > MAX_CHARS:
    sys.exit(f"refusing: {total} characters exceeds the {MAX_CHARS}-character guard")
OUT.mkdir(parents=True, exist_ok=True)
key = os.environ["ELEVENLABS_API_KEY"]
prev = None
for l in spec["lines"]:
    path = OUT / f"{l['id']}.mp3"
    if not path.exists():
        body = {"text": l["text"], "model_id": spec["model"],
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.8, "style": 0.15, "speed": 1.0}}
        if prev:
            body["previous_text"] = prev
        r = httpx.post(f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}?output_format=mp3_44100_128",
                       headers={"xi-api-key": key}, json=body, timeout=120)
        if r.status_code != 200:
            sys.exit(f"{l['id']}: HTTP {r.status_code} {r.text[:200]}")
        path.write_bytes(r.content)
    prev = l["text"]
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True).stdout.strip()
    print(f"{l['id']:8} {float(dur):5.2f}s  {l['text']}")
print(f"sent {total} characters this run")
