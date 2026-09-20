#!/usr/bin/env python3
"""Offline unit test of the deterministic stages (aggregate + match) with NO API calls.

Feeds hand-written vision detections through aggregate() and match(), with the
identity-judgment LLM call stubbed. Run:  python scripts/test_offline.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import matching  # noqa: E402
from pipeline.aggregate import aggregate  # noqa: E402
from pipeline.cost import CostTracker  # noqa: E402

ROWS = [
    {"row_number": 1, "sku": "BRK-2200", "name": "Bracket Kit 2200", "expected_qty": 1},
    {"row_number": 2, "sku": "WGT-X100", "name": "Widget X100", "expected_qty": 1},
    {"row_number": 3, "sku": "CBL-USB-1M", "name": "USB-C Cable 1 m", "expected_qty": 1},
    {"row_number": 4, "sku": "FLT-HEPA-S", "name": "HEPA Filter, Small", "expected_qty": 1},
    {"row_number": 5, "sku": "PSU-65W", "name": "Power Supply 65 W", "expected_qty": 1},
]


def det(photo, tag, sku, conf=0.9, name=None, notes=None):
    return {"photo_id": photo, "position_tag": tag, "label_readable": sku is not None, "sku_read": sku,
            "name_read": name, "bbox": [0.1, 0.1, 0.4, 0.4], "confidence": conf, "notes": notes}


def photo(pid, dets):
    return {"photo_id": pid, "width": 100, "height": 100, "detections": dets, "photo_notes": None}


def fake_judge(unmatched, rows, tracker):
    # stands in for the Sonnet call: WGT-X200 is a variant of row 2, anything else is unrelated
    return {o["position_tag"]: {"row": 2 if o["sku"] == "WGT-X200" else None, "reason": "stub"} for o in unmatched}


def main():
    matching.judge_identity = fake_judge
    failures = 0

    def check(label, cond):
        nonlocal failures
        print(("ok   " if cond else "FAIL ") + label)
        if not cond:
            failures += 1

    # --- scenario B: messy -------------------------------------------------
    photos = [
        photo("photo1", [det("photo1", "POS-1", "BRK-2200"), det("photo1", "POS-2", "WGT-X200"), det("photo1", "POS-3", "CBL-USB-1M")]),
        photo("photo2", [det("photo2", "POS-3", "cbl usb 1m", 0.7), det("photo2", "POS-4", "CBL-USB-1M"), det("photo2", "POS-5", None, 0.6, "HEPA Filter")]),
        photo("photo3", [det("photo3", "POS-1", "BRK-2200", 0.95), det("photo3", "POS-4", "CBL-USB-1M"), det("photo3", "POS-5", None, 0.5)]),
    ]
    objs = aggregate(photos)
    check("B: 5 physical objects after dedup across 9 detections", len(objs) == 5)
    pos3 = next(o for o in objs if o["position_tag"] == "POS-3")
    check("B: POS-3 uses the most confident reading and normalises SKU", pos3["sku"] == "CBL-USB-1M" and len(pos3["evidence"]) == 2)
    res = matching.match(ROWS, objs, CostTracker(), ["photo1", "photo2", "photo3"])
    st = {r["row_number"]: r for r in res["rows"]}
    check("B: row1 confirmed", st[1]["status"] == "confirmed" and st[1]["found_qty"] == 1)
    check("B: row2 identity_mismatch via substitute", st[2]["status"] == "identity_mismatch" and st[2]["substitute_tags"] == ["POS-2"])
    check("B: row3 quantity_mismatch found 2 (POS-3 + POS-4), not 4", st[3]["status"] == "quantity_mismatch" and st[3]["found_qty"] == 2)
    check("B: row4 unverified with obscured-label hint and suggested action", st[4]["status"] == "unverified" and "POS-5" in st[4]["suggested_action"])
    check("B: row5 unverified, never 'missing'", st[5]["status"] == "unverified" and "missing" not in st[5]["explanation"].lower().replace("not evidence that the item is missing", ""))
    check("B: every non-unverified row cites photo+bbox", all(r["evidence"] for r in res["rows"] if r["status"] != "unverified"))
    check("B: POS-5 listed as obscured_label", any(u["kind"] == "obscured_label" and u["position_tag"] == "POS-5" for u in res["unattributed_objects"]))
    check("B: row1 evidence cites both photos", {e["photo_id"] for e in st[1]["evidence"]} == {"photo1", "photo3"})

    # --- scenario C: corrected --------------------------------------------
    photos = [
        photo("photo1", [det("photo1", "POS-1", "BRK-2200"), det("photo1", "POS-2", "WGT-X100"), det("photo1", "POS-3", "CBL-USB-1M")]),
        photo("photo2", [det("photo2", "POS-3", "CBL-USB-1M"), det("photo2", "POS-4", "FLT-HEPA-S"), det("photo2", "POS-5", "PSU-65W")]),
        photo("photo3", [det("photo3", "POS-1", "BRK-2200"), det("photo3", "POS-4", "FLT-HEPA-S"), det("photo3", "POS-5", "PSU-65W")]),
    ]
    res = matching.match(ROWS, aggregate(photos), CostTracker(), ["photo1", "photo2", "photo3"])
    check("C: all confirmed", all(r["status"] == "confirmed" and r["found_qty"] == 1 for r in res["rows"]))

    # --- unexpected SKU / under-count ------------------------------------
    rows2 = [{"row_number": 1, "sku": "BRK-2200", "name": "Bracket Kit 2200", "expected_qty": 2}]
    photos = [photo("photo1", [det("photo1", "POS-1", "BRK-2200"), det("photo1", "POS-2", "ZZZ-999")])]
    res = matching.match(rows2, aggregate(photos), CostTracker(), ["photo1"])
    check("under-count -> quantity_mismatch 1/2 with out-of-frame hint", res["rows"][0]["status"] == "quantity_mismatch" and "out of frame" in res["rows"][0]["explanation"])
    check("unrelated SKU -> unexpected_sku, not attributed to a row", res["unattributed_objects"][0]["kind"] == "unexpected_sku")

    # --- decline-to-conclude cases -----------------------------------------
    from pipeline.verify import decide_clarification
    from pipeline.packing_list import parse_packing_list
    msg = decide_clarification(ROWS, [], [photo("photo1", [])])
    check("no tags in any photo -> needs clarification, asks for re-shoot", msg is not None and "position tag" in msg.lower())
    check("zero rows parsed -> needs clarification", decide_clarification([], [], []) is not None)
    check("normal input -> no clarification", decide_clarification(ROWS, aggregate(photos), photos) is None)
    import io
    from reportlab.pdfgen import canvas as _c
    buf = io.BytesIO(); c = _c.Canvas(buf); c.showPage(); c.save()   # a PDF with no text at all
    try:
        parse_packing_list(buf.getvalue(), CostTracker()); raised = False
    except ValueError:
        raised = True
    check("PDF without extractable text is rejected before any API call", raised)

    print(f"\n{failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
