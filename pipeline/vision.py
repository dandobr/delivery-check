"""Stage 2: one Sonnet vision call per photo -> list of position-tag detections."""
from __future__ import annotations

import base64
import io
import logging

from PIL import Image, ImageOps

from .cost import CostTracker
from .llm import VISION_MODEL, call_json

log = logging.getLogger("pipeline.vision")

MAX_EDGE = 1568  # Anthropic's recommended max long edge; larger images are downscaled anyway.

DETECTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "detections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "position_tag": {"type": "string"},
                    "label_readable": {"type": "boolean"},
                    "sku_read": {"type": ["string", "null"]},
                    "name_read": {"type": ["string", "null"]},
                    "bbox": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 4,
                        "maxItems": 4,
                    },
                    "confidence": {"type": "number"},
                    "notes": {"type": ["string", "null"]},
                },
                "required": ["position_tag", "label_readable", "sku_read", "name_read", "bbox", "confidence", "notes"],
                "additionalProperties": False,
            },
        },
        "photo_notes": {"type": ["string", "null"]},
    },
    "required": ["detections", "photo_notes"],
    "additionalProperties": False,
}

SYSTEM = """You inspect a delivery photo for a goods-receipt check.

Capture convention: every physical item carries a small printed POSITION TAG reading POS-1, POS-2, POS-3, POS-4 or POS-5. This tag is separate from the product/SKU label on the same item. The position tag is the identity of the physical object - the same tag seen in two photos is the same object.

Your job: list EVERY position tag visible in this photo, one detection per tag. For each detection:
- position_tag: the tag text exactly (e.g. "POS-3"). Only report tags you can actually read. If a tag is present but its number is unreadable, do not invent a number - omit it and mention it in photo_notes.
- Find the product/SKU label on the SAME physical item that carries that tag.
  - If the SKU code is clearly legible, set label_readable=true and copy sku_read exactly as printed (keep dashes, digits and letters exact) and name_read as printed.
  - If the label is absent, obscured, out of focus, cut off, or you are not sure of every character of the SKU, set label_readable=false and sku_read=null. NEVER guess a SKU. A near-miss guess is worse than no reading.
- bbox: [x0, y0, x1, y1] as fractions of image width/height (0-1) tightly enclosing the whole physical item (box/package), not just the tag.
- confidence: 0-1 for the overall reading (tag identity and SKU read).
- notes: anything relevant (e.g. "label partly covered by tape", "item partially out of frame").

Do not count items that have no position tag; describe them in photo_notes instead. Do not report the same tag twice.
"""


def prepare_image(data: bytes) -> tuple[bytes, str, int, int]:
    """Downscale/normalise to JPEG. Returns (jpeg_bytes, media_type, width, height)."""
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)  # honour phone orientation so bboxes match what the user sees
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    w, h = img.size
    scale = min(1.0, MAX_EDGE / max(w, h))
    if scale < 1.0:
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    out = io.BytesIO()
    img.convert("RGB").save(out, format="JPEG", quality=88)
    return out.getvalue(), "image/jpeg", img.size[0], img.size[1]


def _clamp_bbox(b: list) -> list[float]:
    vals = [max(0.0, min(1.0, float(v))) for v in b[:4]]
    x0, y0, x1, y1 = vals
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    return [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)]


def analyse_photo(photo_id: str, data: bytes, tracker: CostTracker) -> dict:
    jpeg, media_type, w, h = prepare_image(data)
    b64 = base64.standard_b64encode(jpeg).decode("ascii")
    result = call_json(
        purpose=f"vision:{photo_id}",
        model=VISION_MODEL,
        system=SYSTEM,
        content=[
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
            {"type": "text", "text": f"This is photo '{photo_id}'. List every visible position tag as instructed."},
        ],
        schema=DETECTIONS_SCHEMA,
        tracker=tracker,
        max_tokens=4000,
    )
    detections = []
    for d in result.get("detections", []):
        tag = (d.get("position_tag") or "").strip().upper().replace(" ", "")
        if not tag:
            continue
        readable = bool(d.get("label_readable")) and bool(d.get("sku_read"))
        detections.append({
            "photo_id": photo_id,
            "position_tag": tag,
            "label_readable": readable,
            "sku_read": (d.get("sku_read") or "").strip() if readable else None,
            "name_read": (d.get("name_read") or None),
            "bbox": _clamp_bbox(d.get("bbox") or [0, 0, 1, 1]),
            "confidence": float(d.get("confidence") or 0.0),
            "notes": d.get("notes"),
        })
    log.info("%s: %d detections", photo_id, len(detections))
    return {"photo_id": photo_id, "width": w, "height": h, "detections": detections, "photo_notes": result.get("photo_notes")}
