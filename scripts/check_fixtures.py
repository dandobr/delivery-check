#!/usr/bin/env python3
"""Consistency check: expected.json must follow from physical_contents.json + packing list.

For each fixture folder with both files, derive the status each row *should* have from what is
physically there (by SKU label, obscured labels excluded) and compare with expected.json.
No API calls. Run: python scripts/check_fixtures.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kit import ORDER_A, ORDER_B  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ORDERS = {ORDER_A["ref"]: ORDER_A, ORDER_B["ref"]: ORDER_B}


def derive(order: dict, contents: dict) -> dict:
    boxes = contents["boxes"]
    tagged = [b for b in boxes if b.get("position_tag")]
    if not tagged:
        return {"top_level_status": "needs_clarification",
                "rows": {i: "unverified" for i in range(1, len(order["rows"]) + 1)}}
    readable = [b for b in tagged if not b.get("label_obscured")]
    order_skus = {r["sku"] for r in order["rows"]}
    rows = {}
    for i, r in enumerate(order["rows"], start=1):
        n = sum(1 for b in readable if b["sku_label"] == r["sku"])
        substitutes = [b for b in readable if b["sku_label"] not in order_skus and b["sku_label"][:3] == r["sku"][:3]]
        if n == r["qty"]:
            rows[i] = "confirmed"
        elif n == 0 and substitutes:
            rows[i] = "identity_mismatch"
        elif n > 0:
            rows[i] = "quantity_mismatch"
        else:
            rows[i] = "unverified"
    return {"top_level_status": "complete", "rows": rows}


def main() -> int:
    failures = 0
    for folder in sorted(p.parent for p in ROOT.rglob("physical_contents.json")):
        exp_path = folder / "expected.json"
        if not exp_path.exists():
            continue
        contents = json.loads((folder / "physical_contents.json").read_text())
        expected = json.loads(exp_path.read_text())
        order = ORDERS.get(contents["order"])
        if not order:
            print(f"FAIL {folder.name}: unknown order {contents['order']}"); failures += 1; continue
        d = derive(order, contents)
        problems = []
        if "top_level_status" in expected and expected["top_level_status"] != d["top_level_status"]:
            problems.append(f"top_level_status {expected['top_level_status']} vs derived {d['top_level_status']}")
        for row in expected["rows"]:
            n = row["row_number"]
            if row.get("status") != d["rows"].get(n):
                problems.append(f"row {n}: expected.json says {row.get('status')}, physical contents imply {d['rows'].get(n)}")
        for b in contents["boxes"]:
            if b.get("position_tag") and not b.get("appears_in"):
                problems.append(f"{b['position_tag']} appears in no photo")
        if problems:
            failures += 1
            print(f"FAIL {folder.relative_to(ROOT)}"); [print("   -", p) for p in problems]
        else:
            print(f"ok   {folder.relative_to(ROOT)}")
    print(f"\n{failures} inconsistent fixture(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
