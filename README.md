# Delivery photos vs. packing list

**Live demo: https://delivery-check.onrender.com** (free tier: the first request after
15 minutes idle takes 30-60 s to wake the container)

**Start here:** [DELIVERY_NOTES.md](DELIVERY_NOTES.md) has the measured results, speed and
cost per delivery, what failed, and a worked example of checking a model output by hand.
The test material is in [`fixtures/`](fixtures/), one folder per scenario.

A working prototype that takes a one-page packing list (PDF) and up to three delivery photos and
returns, per packing-list row, one of **confirmed / identity mismatch / quantity mismatch /
unverified**, each with a citation to the row number and the photo + region that supports it.

Every result comes from live model calls on the files uploaded at request time. Nothing is
hardcoded for the fixtures; the test harness calls the same function as the API route.

## Setup and run

Requires Python 3.11+ and an Anthropic API key.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env   # or export it in your shell
uvicorn main:app --reload
```

Open http://127.0.0.1:8000, choose the PDF and 1–3 photos, press **Verify delivery**.

Test harness (runs the real pipeline on every fixture folder and diffs against `expected.json`):

```bash
python scripts/run_tests.py            # all folders under fixtures/
python scripts/run_tests.py --only scenario-b --save   # one scenario, write actual.json
python scripts/test_offline.py         # deterministic stages + decline cases, no API calls
python scripts/check_fixtures.py       # expected.json consistent with physical_contents.json
```

Folders without `packing_list.pdf` or `photo1.jpg` are skipped with a message, not an error.

Docker: `docker build -t delivery-check . && docker run -p 8000:8000 -e ANTHROPIC_API_KEY=... delivery-check`.
`GET /health` returns `{"status":"ok"}` for host health checks.

## Capture convention (read before taking photos)

**Every physical item carries a small printed numbered position tag (`POS-1`, `POS-2`, …),
separate from its product/SKU label, and the tag must be visible in every photo the item
appears in.**

- Counting groups detections by position tag, not by photo. The same tag seen in two photos is
  one object, so nothing is double-counted.
- An item whose tag is not visible in any photo cannot be counted and is reported as *unverified*.
- An item whose tag is visible but whose SKU label is unreadable in every photo is *unverified*
  ("obscured label"), with a suggestion to re-photograph that tag's label.
- The vision prompt is told not to guess a SKU it cannot read; it returns `label_readable: false`
  instead.

Tags are physical-object identities only. The code does **not** assume `POS-n` corresponds to
packing-list row `n`, and there may be more tags than rows: the SKU label is what links an object
to a row. In `scenario-b-messy` the extra, unordered cable carries `POS-6`. A tag is only an
identity when its number is legible; a tag that is present but unreadable is reported as a region
to re-photograph and is never counted.

## Behavioural rules baked into the matcher

1. There is no "missing" status. A row with no matching evidence is *unverified* with a suggested
   next action (e.g. "upload another photo covering row 5"). Absence of evidence is an evidence gap.
2. No double counting: aggregation by position tag across photos (`pipeline/aggregate.py`).
3. Every conclusion cites row number + `photo_id` + bbox. For *unverified* rows the citations point
   at obscured-label objects that might be the item (so a reviewer knows where to look); if there
   are none the evidence list is empty and the explanation says why.
4. Real files, at request time, same code path for API and harness (`pipeline/verify.py`).

## Pipeline

| Stage | Where | Model |
|---|---|---|
| 1. Packing list PDF → text (`pdfplumber`) → rows `{row_number, sku, name, expected_qty}` | `pipeline/packing_list.py` | `claude-haiku-4-5-20251001` |
| 2. Vision pass, once per photo → `{position_tag, sku_read, name_read, bbox, label_readable, confidence}` | `pipeline/vision.py` | `claude-sonnet-5` |
| 3. Aggregate detections by position tag; keep the most confident readable SKU per object | `pipeline/aggregate.py` | none (code) |
| 4. Match objects to rows (deterministic). Objects whose readable SKU matches no row go to one batched identity-judgment call that decides whether they are a "wrong-but-similar" substitute for a specific row | `pipeline/matching.py` | code, plus `claude-sonnet-5` for the judgment only |

Top-level `top_level_status` is `needs_clarification` (with `clarification_message`) when the PDF
yields zero rows or no position tag was detected in any photo; otherwise `complete`.

Status rules (per row):

- SKU matches, count == expected → `confirmed`
- no exact-SKU object, but a substitute judged similar → `identity_mismatch`
- SKU matches, count ≠ expected → `quantity_mismatch` (under-count explains the unit may be out of frame)
- otherwise → `unverified`, with a suggested next action

Objects that belong to no row (unreadable label, or an unrelated SKU) are returned separately as
`unattributed_objects` and shown in the UI, so nothing seen is silently dropped.

All model calls go through `pipeline/llm.py`, which logs `usage.input_tokens` /
`usage.output_tokens` for every response and feeds `pipeline/cost.py`. Per-token prices live in the
single `PRICING` dict at the top of `pipeline/cost.py`. Structured outputs (`output_config.format`
with a JSON schema) are used for every call so responses are schema-valid JSON. Stage 1 and the
per-photo vision passes run concurrently in threads.

Images are EXIF-rotated and downscaled to a 1568 px long edge before upload. The vision prompt
states the exact pixel size and asks for pixel bounding boxes, which the code converts to fractions
of width/height (so they map back to the original file in the browser). Fractions straight from the
model were unreliable on non-square images: in testing it sometimes divided x by the height.

## Output shape (`POST /api/verify`)

```
{
  order_reference, packing_list_rows[], photos[{photo_id,width,height,photo_notes}],
  objects[ {position_tag, sku, label_readable, confidence, evidence[{photo_id,bbox,...}]} ],
  rows[ {row_number, sku, name, expected_qty, found_qty, status, evidence[{photo_id,bbox,position_tag}],
         explanation, suggested_action (unverified only), matched_tags, substitute_tags} ],
  unattributed_objects[ {position_tag, kind: obscured_label|unexpected_sku, sku, evidence, explanation} ],
  status_counts, usage{total_seconds,total_cost_usd,total_input_tokens,total_output_tokens,pricing_usd_per_mtok,calls[]}
}
```

## Test kit and fixtures

- `samples/label_sheet.pdf` – printable A4 sheet: 5 product labels (rows 1–5), a second copy of row
  3's label (needed for scenario B's extra unit), the alternate `WGT-X200` label for row 2, and
  position tags `POS-1`…`POS-7` (more tags than rows, so extra or unexpected units can be tagged too). Edit product names/SKUs in `scripts/kit.py`, then rerun
  `scripts/make_label_sheet.py` and `scripts/make_packing_lists.py`.
- `samples/packing_list_order_A.pdf` – 3-item order (scenario A). `samples/packing_list_order_B.pdf`
  – 5-item order (scenarios B and C). Copies are already placed in the fixture folders.
- `fixtures/scenario-{a-normal,b-messy,c-corrected}/` – drop `photo1.jpg`, `photo2.jpg`,
  `photo3.jpg` into each. `expected.json` is already there; edit it if your kit differs.
- `fixtures/scenario-a-normal/`, `scenario-b-messy/`, `scenario-c-corrected/` – real photographs of household objects carrying the printed labels. Scenario A also contains one item that is not on the packing list, which must not be attributed to any row.
- `fixtures/scenario-d-unclear/` – the "ask for clarification / decline to conclude" input: Order A
  photographed with no position tag visible. Expected: `top_level_status: needs_clarification`, all
  rows unverified, a banner asking for a re-shoot. A PDF with no extractable text is the second
  decline case (HTTP 422 with a message).
- Every scenario folder has `physical_contents.json` recording what was physically in the delivery
  (tag, SKU label applied, obscured or not, which photos it appears in). `scripts/check_fixtures.py`
  verifies `expected.json` is consistent with it, with no API calls.
- `fixtures/synthetic/…` – rendered cartoon "photos" produced by `scripts/make_synthetic_photos.py`.
  They exercise the full code path (real API calls, dedup across photos, obscured label, extra
  unit, absent item) before real photos exist. They are drawings, not evidence of real-world
  robustness. Delete the folder if you don't want the harness to run them.

`expected.json` lists per row the keys to assert (`status` at minimum, optionally `found_qty`), plus
`row_count`. Only keys present are compared.

## Reused components vs. work written for this project

Reused, unmodified, via `requirements.txt`:

| Component | Role here |
|---|---|
| `anthropic` (official Python SDK) | every model call, retries, error types |
| `fastapi` + `uvicorn` + `python-multipart` | HTTP server, multipart upload handling |
| `pdfplumber` | text extraction from the packing-list PDF |
| `pillow` | EXIF rotation, downscaling, JPEG re-encoding of uploads |
| `reportlab` | generating the label sheet and the sample packing lists |

Written for this project (no framework, no starter template, no vendored code):

- the whole pipeline: prompts, aggregation by position tag, the deterministic matcher, the
  clarification rule, cost accounting (`pipeline/`)
- the API layer (`main.py`) and the single-file frontend (`static/index.html`), vanilla JS, no build step
- the test harness, offline tests, fixture consistency checker and kit generators (`scripts/`)
- the test set: label sheet, two packing lists, four scenarios with recorded expected outcomes

Nothing here is an existing product of mine repackaged; the repository was created from scratch for
this brief.

## Known limitations / unfinished

- **Not yet run against real photos.** I had no API key in the build environment, so the live
  API path (Haiku parse, Sonnet vision, Sonnet judgment) has not been executed end to end. The
  deterministic stages are covered by `scripts/test_offline.py`. First thing to do: export a key
  and run `python scripts/run_tests.py --only synthetic --save`, then real photos.
- Scanned/image-only PDFs are rejected (no OCR); packing lists must have extractable text.
- Bounding boxes come from the vision model and are approximate; the UI pads the crop.
- Duplicate SKUs on several rows are attributed to the first row that is not yet full.
- Under-count (found 1 of 2) is reported as `quantity_mismatch` per the spec, with an
  out-of-frame hint in the explanation; there is no suggested-action field for it.
- No retries/backoff beyond the SDK default (3 retries), no request size limits, no auth.
  Single-process, in-memory only.
- The synthetic photos are cartoons; a model that reads them fine may still struggle with glare,
  angle, or small print on real boxes.

## Generated vs. hand-edited

Everything in this repository was generated by Claude Code (Claude Fable 5.1) in one session on
2026-09-20 from the build brief, including this README. Files edited by hand afterwards are listed
here: *(none yet)*.

## Out of scope

Warehouse integrations, automatic supplier complaints, accounts/logins, multi-language, native
packaging.

## Test photo metadata

EXIF metadata, including GPS coordinates, has been stripped from every photograph in
`fixtures/`. Image orientation was baked in first, so the files render identically and
the pipeline (which applies `ImageOps.exif_transpose`) is unaffected.
