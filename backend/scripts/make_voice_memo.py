"""Generate the synthetic staff voice memo for the sample batch (sample data only, not part of the product).

    .venv/bin/python backend/scripts/make_voice_memo.py     # needs ELEVENLABS_API_KEY in .env

Writes data/samples/sources/voice_memo_tom.wav (24 kHz mono 16-bit, the format Muse Voice Transcribe accepts),
which generate_samples.py copies into the batch. It sounds like a phone recording: light band-limiting and room tone.
"""

import os
import subprocess
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "samples" / "sources" / "voice_memo_tom.wav"
VOICE = "TX3LPaxmHKxFdv7VOQHJ"  # ElevenLabs premade "Liam" (young, energetic), speaking German
TEXT = ("Hey, hier ist Tom aus der Filiale Mitte. Kurz wegen der Milch von der Molkerei Havelland, Kalenderwoche "
        "dreiundvierzig: Da sind nur achtundzwanzig Kannen gekommen, statt vierzig. Also zweihundertachtzig Liter "
        "statt vierhundert. Der Fahrer meinte, der Rest kommt nicht mehr. Bitte zahlt nicht die volle Rechnung, okay? "
        "Danke dir!")

load_dotenv(ROOT / ".env")
r = httpx.post(f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}?output_format=mp3_44100_128",
               headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]}, timeout=120,
               json={"text": TEXT, "model_id": "eleven_multilingual_v2",
                     "voice_settings": {"stability": 0.4, "similarity_boost": 0.8, "style": 0.3, "use_speaker_boost": True}})
if r.status_code != 200:
    sys.exit(f"HTTP {r.status_code}: {r.text[:200]}")
mp3 = OUT.with_suffix(".mp3")
mp3.write_bytes(r.content)
# phone-memo character: band-limit, gentle compression, faint room tone
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(mp3), "-f", "lavfi", "-i", "anoisesrc=color=pink:amplitude=0.004",
                "-filter_complex", "[0:a]highpass=f=110,lowpass=f=7500,acompressor=threshold=-18dB:ratio=3[v];"
                "[v][1:a]amix=inputs=2:duration=first:normalize=0",
                "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", "-map_metadata", "-1", str(OUT)], check=True)
mp3.unlink()
print(f"wrote {OUT} ({len(TEXT)} characters)")
