"""Document intake: register files, render page images, build multimodal model input."""

from __future__ import annotations

import base64
import hashlib
import io
import json
from email import policy
from email.parser import BytesParser
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageOps

from .config import RUNTIME, SAMPLES
from .db import DB

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
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
    doc = {"doc_id": doc_id, "idx": idx, "filename": path.name, "kind": kind, "path": str(path), "sha256": sha, "meta": meta}
    doc["meta"]["pages"] = len(page_images(doc))
    db.upsert_document(batch_id, doc)
    return doc


def load_sample_batch(db: DB) -> list[dict]:
    """Register the committed synthetic batch in manifest (arrival) order."""
    folder = SAMPLES / "batch"
    manifest = json.loads((folder / "manifest.json").read_text())
    existing = {d["filename"]: d for d in db.documents("sample")}
    if len(existing) == len(manifest["documents"]):
        return db.documents("sample")
    taken: set[str] = set()
    return [register_file(db, "sample", i, folder / entry["filename"], taken)
            for i, entry in enumerate(manifest["documents"])]


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
