"""Stage 3: merge per-photo detections into one record per physical object.

Grouping key is the position tag. The same tag seen in several photos is ONE
object, so nothing is double-counted. The SKU used for matching is the most
confident *readable* reading across all photos the object appeared in.
"""
from __future__ import annotations

import re


def normalise_sku(s: str | None) -> str:
    """Case/punctuation-insensitive key for SKU comparison ("wgt-x100" == "WGT X100")."""
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def aggregate(photo_results: list[dict]) -> list[dict]:
    objects: dict[str, dict] = {}
    for pr in photo_results:
        for det in pr["detections"]:
            tag = det["position_tag"]
            obj = objects.setdefault(tag, {
                "position_tag": tag,
                "sku": None,
                "sku_key": "",
                "name_read": None,
                "confidence": 0.0,
                "label_readable": False,
                "conflicting_skus": [],
                "evidence": [],
                "readings": [],
            })
            obj["evidence"].append({
                "photo_id": det["photo_id"],
                "bbox": det["bbox"],
                "label_readable": det["label_readable"],
                "sku_read": det["sku_read"],
                "confidence": det["confidence"],
                "notes": det["notes"],
            })
            obj["readings"].append(det)

    for obj in objects.values():
        readable = [r for r in obj["readings"] if r["label_readable"]]
        if readable:
            best = max(readable, key=lambda r: r["confidence"])
            obj["label_readable"] = True
            obj["sku"] = best["sku_read"]
            obj["sku_key"] = normalise_sku(best["sku_read"])
            obj["name_read"] = best.get("name_read")
            obj["confidence"] = best["confidence"]
            others = sorted({r["sku_read"] for r in readable if normalise_sku(r["sku_read"]) != obj["sku_key"]})
            obj["conflicting_skus"] = others
        else:
            # keep the best-effort product name even when the SKU is unreadable
            names = [r.get("name_read") for r in obj["readings"] if r.get("name_read")]
            obj["name_read"] = names[0] if names else None
            obj["confidence"] = max((r["confidence"] for r in obj["readings"]), default=0.0)
        del obj["readings"]

    def sort_key(tag: str):
        m = re.search(r"(\d+)", tag)
        return (int(m.group(1)) if m else 10**6, tag)

    return [objects[t] for t in sorted(objects, key=sort_key)]
