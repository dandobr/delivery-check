#!/usr/bin/env python3
"""Run the real pipeline against every fixture folder and diff against expected.json.

Usage:  python scripts/run_tests.py [fixtures_dir] [--only scenario-b-messy] [--save]

- Calls pipeline.verify.verify_delivery - the exact function the API route calls.
- A folder is a scenario if it contains packing_list.pdf; photos are photo1.jpg..photo3.jpg
  (also accepts .jpeg/.png). Folders without a PDF or without photos are skipped with a message.
- expected.json format:
    {"rows": [{"row_number": 1, "status": "confirmed", "found_qty": 1}, ...],
     "top_level_status": "complete" | "needs_clarification"   (optional)}
  Only keys present in each expected row are compared, so you can assert as little or as
  much as you like per row (status is the minimum).
- --save writes actual output to <folder>/actual.json for inspection.
- Exit code is non-zero if any scenario fails.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.env import credentials_present, load_dotenv  # noqa: E402
from pipeline.verify import verify_delivery  # noqa: E402

PHOTO_EXTS = (".jpg", ".jpeg", ".png", ".webp")


def find_photos(folder: Path) -> list[tuple[str, bytes]]:
    photos = []
    for i in (1, 2, 3):
        for ext in PHOTO_EXTS:
            p = folder / f"photo{i}{ext}"
            if p.exists():
                photos.append((f"photo{i}", p.read_bytes()))
                break
    return photos


def diff_rows(expected: dict, actual: dict) -> list[str]:
    problems = []
    actual_rows = {r["row_number"]: r for r in actual["rows"]}
    for exp in expected.get("rows", []):
        n = exp.get("row_number")
        act = actual_rows.get(n)
        if act is None:
            problems.append(f"row {n}: expected but not present in output (parsed rows: {sorted(actual_rows)})")
            continue
        for key, val in exp.items():
            if key == "row_number":
                continue
            if act.get(key) != val:
                problems.append(f"row {n}: {key} expected {val!r}, got {act.get(key)!r}")
        if act["status"] not in ("confirmed", "identity_mismatch", "quantity_mismatch", "unverified"):
            problems.append(f"row {n}: illegal status {act['status']!r}")
        if not act.get("evidence") and act["status"] != "unverified":
            problems.append(f"row {n}: status {act['status']} has no evidence citation")
    if "top_level_status" in expected and actual.get("top_level_status") != expected["top_level_status"]:
        problems.append(f"top_level_status expected {expected['top_level_status']!r}, got {actual.get('top_level_status')!r}")
    if "row_count" in expected and len(actual["rows"]) != expected["row_count"]:
        problems.append(f"row_count expected {expected['row_count']}, got {len(actual['rows'])}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("fixtures_dir", nargs="?", default=str(Path(__file__).resolve().parent.parent / "fixtures"))
    ap.add_argument("--only", help="run only folders whose name contains this text")
    ap.add_argument("--save", action="store_true", help="write actual.json next to each fixture")
    args = ap.parse_args()

    load_dotenv()
    if not credentials_present():
        print("WARNING: ANTHROPIC_API_KEY is not set and no .env file was found next to this project.\n"
              "         The pipeline makes real API calls and will fail unless the SDK can find credentials\n"
              "         another way. Put ANTHROPIC_API_KEY=sk-ant-... in a .env file, or export it.\n")

    root = Path(args.fixtures_dir)
    folders = sorted({p.parent for p in root.rglob("expected.json")} | {p.parent for p in root.rglob("packing_list.pdf")})
    if args.only:
        folders = [f for f in folders if args.only in str(f.relative_to(root))]
    if not folders:
        print(f"No fixture folders found under {root}")
        return 1

    failures = 0
    ran = 0
    for folder in folders:
        name = folder.relative_to(root) if folder != root else folder.name
        pdf = folder / "packing_list.pdf"
        photos = find_photos(folder)
        expected_path = folder / "expected.json"
        if not pdf.exists() or not photos:
            print(f"SKIP  {name}: needs packing_list.pdf and photo1.jpg (found pdf={pdf.exists()}, photos={len(photos)})")
            continue
        if not expected_path.exists():
            print(f"SKIP  {name}: no expected.json")
            continue
        expected = json.loads(expected_path.read_text())
        print(f"RUN   {name} ({len(photos)} photo(s)) ...", flush=True)
        try:
            actual = verify_delivery(pdf.read_bytes(), photos)
        except Exception as e:
            print(f"FAIL  {name}: pipeline raised {type(e).__name__}: {e}")
            failures += 1
            continue
        ran += 1
        if args.save:
            (folder / "actual.json").write_text(json.dumps(actual, indent=2))
        problems = diff_rows(expected, actual)
        u = actual["usage"]
        stats = f"{u['total_seconds']:.1f}s, ${u['total_cost_usd']:.4f}, {len(u['calls'])} calls"
        if problems:
            failures += 1
            print(f"FAIL  {name} [{stats}]")
            for p in problems:
                print(f"        - {p}")
        else:
            print(f"PASS  {name} [{stats}]")
        if actual.get("clarification_message"):
            print(f"        top_level_status={actual['top_level_status']}: {actual['clarification_message'][:120]}")
        for r in actual["rows"]:
            print(f"        row {r['row_number']:>2} {r['status']:<18} found {r['found_qty']}/{r['expected_qty']}  {r['sku']}")

    print(f"\n{ran} scenario(s) run, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
