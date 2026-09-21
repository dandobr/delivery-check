"""Pipeline entry point. The API route and the test harness both call `verify_delivery`."""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor

from .aggregate import aggregate
from .cost import CostTracker
from .matching import match
from .packing_list import parse_packing_list
from .vision import analyse_photo

log = logging.getLogger("pipeline.verify")

MAX_PHOTOS = 3


def decide_clarification(rows: list[dict], objects: list[dict], photo_results: list[dict]) -> str | None:
    """Return a message when the input cannot support any conclusion, else None.

    Rows still come back (all unverified) so the UI can show what was expected, but the
    top-level status says clearly that this run proved nothing and what to upload next.
    """
    if not rows:
        return ("The PDF was read but no line items were found. Please upload the packing list itself "
                "(a one-page text PDF with SKU, description and quantity per line).")
    if not objects:
        notes = "; ".join(f"{p['photo_id']}: {p['photo_notes']}" for p in photo_results if p.get("photo_notes"))
        return ("No position tags (POS-1, POS-2, ...) were detected in any photo, so nothing can be counted "
                "or matched. Please re-photograph the delivery with each item's position tag and SKU label "
                "facing the camera." + (f" Model notes: {notes}" if notes else ""))
    return None


def verify_delivery(pdf_bytes: bytes, photos: list[tuple[str, bytes]]) -> dict:
    """photos: list of (photo_id, image_bytes). Returns the full result dict (JSON-serialisable)."""
    if not photos:
        raise ValueError("At least one delivery photo is required.")
    if len(photos) > MAX_PHOTOS:
        raise ValueError(f"At most {MAX_PHOTOS} photos are supported.")

    tracker = CostTracker()
    t0 = time.perf_counter()

    # PDF parse and the per-photo vision passes are independent - run them concurrently.
    with ThreadPoolExecutor(max_workers=1 + len(photos)) as pool:
        pl_future = pool.submit(parse_packing_list, pdf_bytes, tracker)
        photo_futures = [pool.submit(analyse_photo, pid, data, tracker) for pid, data in photos]
        packing = pl_future.result()
        photo_results = [f.result() for f in photo_futures]

    objects = aggregate(photo_results)

    clarification = decide_clarification(packing["rows"], objects, photo_results)

    matched = match(packing["rows"], objects, tracker, [pid for pid, _ in photos])

    summary = tracker.summary()
    summary["total_seconds"] = round(time.perf_counter() - t0, 3)
    counts = {s: sum(1 for r in matched["rows"] if r["status"] == s)
              for s in ("confirmed", "identity_mismatch", "quantity_mismatch", "unverified")}
    return {
        "top_level_status": "needs_clarification" if clarification else "complete",
        "clarification_message": clarification,
        "order_reference": packing["order_reference"],
        "packing_list_rows": packing["rows"],
        "photos": [{"photo_id": p["photo_id"], "width": p["width"], "height": p["height"], "photo_notes": p["photo_notes"]}
                   for p in photo_results],
        "objects": objects,
        "rows": matched["rows"],
        "unattributed_objects": matched["unattributed_objects"],
        "status_counts": counts,
        "usage": summary,
    }
