"""Stage 4: deterministic matching of aggregated objects against packing-list rows.

The only non-deterministic piece is `judge_identity`: when an object has a
readable SKU that matches no row exactly, Sonnet decides whether it is a
"wrong-but-similar" substitute for a specific row. Everything else is plain code.

Allowed statuses: confirmed | identity_mismatch | quantity_mismatch | unverified.
There is deliberately no "missing" status - absence of evidence is not evidence of absence.
"""
from __future__ import annotations

import logging
import re

from .aggregate import normalise_sku
from .cost import CostTracker
from .llm import VISION_MODEL, call_json

log = logging.getLogger("pipeline.matching")

STATUSES = ("confirmed", "identity_mismatch", "quantity_mismatch", "unverified")

JUDGMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "position_tag": {"type": "string"},
                    "substitute_for_row": {"type": ["integer", "null"]},
                    "reason": {"type": "string"},
                },
                "required": ["position_tag", "substitute_for_row", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["decisions"],
    "additionalProperties": False,
}

JUDGMENT_SYSTEM = """You help reconcile a delivery against a packing list.

You are given packing-list rows (row_number, sku, name, expected_qty) and a list of physical
objects whose SKU label was read clearly but does not exactly match any row's SKU.

For each object decide whether it is most plausibly a WRONG-BUT-SIMILAR item delivered in place of
one specific row (e.g. "WGT-X200" delivered where "WGT-X100" was ordered, or the same product
family with a different size/colour/variant code). If so, return that row_number in
substitute_for_row. If the object does not correspond to any row (an unrelated product),
return null.

Be strict: only pick a row when the SKU or product name is clearly a variant of that row's
product. A different product family is null. Give a one-sentence reason.
"""


def judge_identity(unmatched: list[dict], rows: list[dict], tracker: CostTracker) -> dict[str, dict]:
    """Ask Sonnet which row (if any) each unmatched readable-SKU object substitutes for."""
    if not unmatched:
        return {}
    payload = {
        "packing_list_rows": [
            {"row_number": r["row_number"], "sku": r["sku"], "name": r["name"], "expected_qty": r["expected_qty"]}
            for r in rows
        ],
        "unmatched_objects": [
            {"position_tag": o["position_tag"], "sku_read": o["sku"], "name_read": o["name_read"]}
            for o in unmatched
        ],
    }
    import json
    result = call_json(
        purpose="identity_judgment",
        model=VISION_MODEL,
        system=JUDGMENT_SYSTEM,
        content=json.dumps(payload, indent=2),
        schema=JUDGMENT_SCHEMA,
        tracker=tracker,
        max_tokens=2000,
        effort="medium",
    )
    valid_rows = {r["row_number"] for r in rows}
    out = {}
    for d in result.get("decisions", []):
        tag = (d.get("position_tag") or "").strip().upper()
        row = d.get("substitute_for_row")
        out[tag] = {"row": row if row in valid_rows else None, "reason": d.get("reason", "")}
    return out


def _name_matches(row_name: str, name_read: str | None) -> bool:
    """Loose product-name match: most significant words of the row name appear in the read name."""
    if not name_read:
        return False
    def words(t: str) -> set[str]:
        return {w for w in re.sub(r"[^a-z0-9 ]", " ", t.lower()).split() if len(w) > 1}
    a, b = words(row_name), words(name_read)
    if not a or not b:
        return False
    return len(a & b) / len(a) >= 0.6


def _evidence(obj: dict) -> list[dict]:
    return [{"photo_id": e["photo_id"], "bbox": e["bbox"], "position_tag": obj["position_tag"]} for e in obj["evidence"]]


def _photos_of(obj: dict) -> str:
    return ", ".join(sorted({e["photo_id"] for e in obj["evidence"]}))


def match(rows: list[dict], objects: list[dict], tracker: CostTracker, photo_ids: list[str]) -> dict:
    by_key: dict[str, list[dict]] = {}
    for r in rows:
        by_key.setdefault(normalise_sku(r["sku"]), []).append(r)

    matched: dict[int, list[dict]] = {r["row_number"]: [] for r in rows}
    substitutes: dict[int, list[dict]] = {r["row_number"]: [] for r in rows}
    unreadable: list[dict] = []
    unmatched_readable: list[dict] = []

    for obj in objects:
        if not obj["label_readable"]:
            unreadable.append(obj)
            continue
        hits = by_key.get(obj["sku_key"])
        if hits:
            # Same SKU on several rows is unusual; attribute to the first row that is not yet full.
            target = next((r for r in hits if len(matched[r["row_number"]]) < r["expected_qty"]), hits[0])
            matched[target["row_number"]].append(obj)
        else:
            unmatched_readable.append(obj)

    judgments = judge_identity(unmatched_readable, rows, tracker)
    unexpected: list[dict] = []
    for obj in unmatched_readable:
        j = judgments.get(obj["position_tag"], {"row": None, "reason": "no judgment returned"})
        obj["judgment"] = j["reason"]
        if j["row"] is not None:
            substitutes[j["row"]].append(obj)
        else:
            unexpected.append(obj)

    photo_list = ", ".join(photo_ids) if photo_ids else "the supplied photos"
    results = []
    for r in rows:
        n = r["row_number"]
        found = matched[n]
        subs = substitutes[n]
        count = len(found)
        expected = r["expected_qty"]
        evidence = [ev for o in found for ev in _evidence(o)] + [ev for o in subs for ev in _evidence(o)]
        suggested = None

        if count == 0 and subs:
            status = "identity_mismatch"
            sub_desc = "; ".join(
                f"{o['position_tag']} reads SKU '{o['sku']}' ({o['judgment']}) in {_photos_of(o)}" for o in subs
            )
            explanation = (f"Row {n} expects SKU {r['sku']} but the tagged item(s) delivered in its place carry a different SKU: {sub_desc}.")
        elif count == expected and count > 0:
            status = "confirmed"
            tags = ", ".join(f"{o['position_tag']} ({_photos_of(o)})" for o in found)
            explanation = f"Row {n}: {count} of {expected} unit(s) of SKU {r['sku']} identified by position tag {tags}."
            if subs:
                explanation += " Additionally, a similar-SKU item was seen: " + "; ".join(
                    f"{o['position_tag']} reads '{o['sku']}'" for o in subs) + "."
        elif count > 0:
            status = "quantity_mismatch"
            tags = ", ".join(f"{o['position_tag']} ({_photos_of(o)})" for o in found)
            if count > expected:
                explanation = (f"Row {n} expects {expected} unit(s) of SKU {r['sku']} but {count} distinct tagged units were found: {tags}. "
                               f"Objects seen in several photos were counted once by position tag.")
            else:
                explanation = (f"Row {n} expects {expected} unit(s) of SKU {r['sku']} but only {count} tagged unit(s) were identified: {tags}. "
                               f"The remaining unit(s) may simply be out of frame - a photo covering them would settle it.")
        else:
            status = "unverified"
            explanation = (f"Row {n} (SKU {r['sku']}) could not be verified: no tagged item with a readable matching label appears in {photo_list}. "
                           "This is an evidence gap, not evidence that the item is missing.")
            # Obscured-label objects whose *product name* is legible and matches this row are the likeliest candidates.
            name_hits = [o for o in unreadable if _name_matches(r["name"], o.get("name_read"))]
            if name_hits:
                explanation += " Likely obscured label: " + "; ".join(
                    f"{o['position_tag']} ({_photos_of(o)}) shows the product name '{o['name_read']}' but its SKU is not readable" for o in name_hits) + "."
                suggested = ("Upload a clearer photo of the SKU label on " + ", ".join(o["position_tag"] for o in name_hits) + ".")
                evidence = [ev for o in name_hits for ev in _evidence(o)]
            elif unreadable:
                explanation += " Note: object(s) with an unreadable label were seen (" + "; ".join(
                    f"{o['position_tag']} in {_photos_of(o)}" for o in unreadable) + ") - one of them may be this item."
                suggested = ("Upload a clearer photo of the SKU label on " + ", ".join(o["position_tag"] for o in unreadable) +
                             f", or a photo covering row {n} ({r['name']}).")
                # cited as *possible* evidence so the reviewer knows where to look
                evidence = [ev for o in unreadable for ev in _evidence(o)]
            else:
                suggested = f"Upload another photo covering row {n} ({r['name']}, SKU {r['sku']}) with its position tag and SKU label visible."
                evidence = []

        results.append({
            "row_number": n,
            "sku": r["sku"],
            "name": r["name"],
            "expected_qty": expected,
            "found_qty": count,
            "status": status,
            "evidence": evidence,
            "explanation": explanation,
            "suggested_action": suggested,
            "matched_tags": [o["position_tag"] for o in found],
            "substitute_tags": [o["position_tag"] for o in subs],
        })

    unattributed = [
        {"position_tag": o["position_tag"], "kind": "obscured_label", "sku": None, "name_read": o["name_read"],
         "evidence": _evidence(o), "explanation": f"{o['position_tag']} seen in {_photos_of(o)} but its SKU label is not readable in any photo."}
        for o in unreadable
    ] + [
        {"position_tag": o["position_tag"], "kind": "unexpected_sku", "sku": o["sku"], "name_read": o["name_read"],
         "evidence": _evidence(o), "explanation": f"{o['position_tag']} reads SKU '{o['sku']}' which is not on the packing list ({o['judgment']})."}
        for o in unexpected
    ]
    return {"rows": results, "unattributed_objects": unattributed}
