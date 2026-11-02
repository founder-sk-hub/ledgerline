"""Document intake: register files, render page images, build multimodal model input."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import wave
from email import policy
from email.parser import BytesParser
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageOps

from .config import RUNTIME, SAMPLES
from .db import DB

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
AUDIO_EXT = {".wav"}
MAX_SIDE = 1600
MAX_PAGES = 6


def kind_of(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return "pdf"
    if ext in IMAGE_EXT:
        return "image"
    if ext == ".eml":
        return "email"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in (".txt", ".md"):
        return "text"
    raise ValueError(f"unsupported file type: {filename}")


def register_file(db: DB, batch_id: str, idx: int, path: Path, taken: set[str]) -> dict:
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    doc_id = sha[:10]
    while doc_id in taken:  # byte-identical uploads still get their own row
        doc_id = f"{sha[:10]}-{idx}"
    taken.add(doc_id)
    kind = kind_of(path.name)
    meta: dict = {"size": len(data)}
    if kind == "email":
        msg = BytesParser(policy=policy.default).parsebytes(data)
        meta.update({"from": str(msg["From"] or ""), "subject": str(msg["Subject"] or ""), "date": str(msg["Date"] or "")})
    if kind == "audio":
        with wave.open(io.BytesIO(data)) as w:
            meta["duration_s"] = round(w.getnframes() / w.getframerate(), 1)
    doc = {"doc_id": doc_id, "idx": idx, "filename": path.name, "kind": kind, "path": str(path), "sha256": sha, "meta": meta}
    doc["meta"]["pages"] = len(page_images(doc))
    db.upsert_document(batch_id, doc)
    return doc


def load_sample_batch(db: DB) -> list[dict]:
    """Register the committed synthetic batch in manifest (arrival) order.

    Rows from an older version of the sample batch move to "sample-archive" so earlier runs
    still resolve their document ids."""
    folder = SAMPLES / "batch"
    manifest = json.loads((folder / "manifest.json").read_text())
    current = {e["filename"]: hashlib.sha256((folder / e["filename"]).read_bytes()).hexdigest()
               for e in manifest["documents"]}
    existing = db.documents("sample")
    if len(existing) == len(current) and all(current.get(d["filename"]) == d["sha256"] for d in existing):
        return existing
    db.archive_batch("sample", "sample-archive")
    taken: set[str] = set()
    return [register_file(db, "sample", i, folder / entry["filename"], taken)
            for i, entry in enumerate(manifest["documents"])]


def asr_wav(doc: dict) -> bytes:
    """The recording as mono 16-bit PCM WAV at 24 kHz, the format Muse Voice Transcribe accepts."""
    import numpy as np

    with wave.open(doc["path"]) as w:
        rate, ch, width, frames = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.readframes(w.getnframes())
    if (rate, ch, width) == (24000, 1, 2) or (rate, ch, width) == (16000, 1, 2):
        return Path(doc["path"]).read_bytes()
    dtype = {1: np.uint8, 2: np.int16, 4: np.int32}[width]
    x = np.frombuffer(frames, dtype=dtype).astype(np.float32)
    if width == 1:
        x = (x - 128) * 256
    elif width == 4:
        x = x / 65536
    x = x.reshape(-1, ch).mean(axis=1)
    n = int(len(x) * 24000 / rate)
    x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(np.clip(x, -32768, 32767).astype(np.int16).tobytes())
    return out.getvalue()


# ---------------------------------------------------------------- rendering
def _norm(img: Image.Image) -> Image.Image:
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    return img


def _email_parts(path: Path) -> tuple[str, list[Image.Image]]:
    msg = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
    header = "\n".join(f"{h}: {msg[h]}" for h in ("From", "To", "Date", "Subject") if msg[h])
    body = msg.get_body(preferencelist=("plain", "html"))
    text = body.get_content() if body else ""
    images: list[Image.Image] = []
    for part in msg.iter_attachments():
        ctype = part.get_content_type()
        payload = part.get_payload(decode=True) or b""
        if ctype == "application/pdf":
            images.extend(_pdf_pages(payload))
        elif ctype.startswith("image/"):
            images.append(_norm(Image.open(io.BytesIO(payload))))
    return f"{header}\n\n{text}".strip(), images


def _pdf_pages(data: bytes | str) -> list[Image.Image]:
    pdf = pdfium.PdfDocument(data)
    out = []
    for i in range(min(len(pdf), MAX_PAGES)):
        page = pdf[i]
        w, h = page.get_size()
        scale = MAX_SIDE / max(w, h)
        out.append(_norm(page.render(scale=scale).to_pil()))
    pdf.close()
    return out


def page_images(doc: dict) -> list[Path]:
    """Return cached JPEG page renders for a document (rendering on first use)."""
    folder = RUNTIME / "pages" / doc["doc_id"]
    cached = sorted(folder.glob("p*.jpg"))
    if cached:
        return cached
    path = Path(doc["path"])
    if doc["kind"] == "pdf":
        imgs = _pdf_pages(str(path))
    elif doc["kind"] == "image":
        imgs = [_norm(Image.open(path))]
    elif doc["kind"] == "email":
        imgs = _email_parts(path)[1]
    else:
        imgs = []
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, img in enumerate(imgs, 1):
        p = folder / f"p{i}.jpg"
        img.save(p, "JPEG", quality=85)
        paths.append(p)
    return paths


def document_text(doc: dict) -> str:
    path = Path(doc["path"])
    if doc["kind"] == "email":
        return _email_parts(path)[0]
    if doc["kind"] == "text":
        return path.read_text(errors="replace")
    return ""


def model_content(doc: dict, pages: list[int] | None = None) -> list[dict]:
    """OpenAI-style content parts: text for emails, one image per page otherwise."""
    parts: list[dict] = []
    text = document_text(doc)
    if text:
        parts.append({"type": "text", "text": f"<document filename=\"{doc['filename']}\" kind=\"{doc['kind']}\">\n"
                                               f"{text}\n</document>"})
    for i, p in enumerate(page_images(doc), 1):
        if pages and i not in pages:
            continue
        b64 = base64.b64encode(p.read_bytes()).decode()
        parts.append({"type": "text", "text": f"[page {i} of {doc['filename']}]"})
        parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
    return parts
