# Delivery notes

_Template. Fill in after running against the physical test kit. Numbers in italics are placeholders._

## Sample inputs and results

| Scenario | Packing list | Photos | Expected | Actual | Pass |
|---|---|---|---|---|---|
| A – normal | `samples/packing_list_order_A.pdf` | 3 | 3 × confirmed | _…_ | _…_ |
| B – messy | `samples/packing_list_order_B.pdf` | 3 | confirmed / identity_mismatch / quantity_mismatch (2 of 1) / unverified / unverified | _…_ | _…_ |
| C – corrected | `samples/packing_list_order_B.pdf` | 3 | 5 × confirmed | _…_ | _…_ |

Harness output (`python scripts/run_tests.py`):

```
_paste here_
```

## What failed

- _e.g. "photo3 in scenario B: POS-4 tag read as POS-1 at low confidence → row 3 counted 1 instead of 2; re-shot with tag facing camera."_

## Time spent

| Activity | Time |
|---|---|
| Building the code (generated) | _…_ |
| Printing/assembling the kit, photographing | _…_ |
| Running, debugging, prompt tweaks | _…_ |
| Writing up | _…_ |

## AI tools and models used

- Code generation: Claude Code with Claude Fable 5.1 (`claude-fable-5-1`), single session, 2026-09-20.
- In the product:
  - `claude-sonnet-5` – vision pass per photo; identity-mismatch judgment (one call per verification, only when an unmatched readable SKU exists).
  - `claude-haiku-4-5-20251001` – packing-list text → rows.
  - Official `anthropic` Python SDK, structured outputs (`output_config.format`).
- No other AI services.

## Worked example: manually checking one AI output

_Pick one row from scenario B and show the check end to end. Example structure:_

1. Row 3 (`CBL-USB-1M`, expected 1) came back `quantity_mismatch`, found 2, evidence `photo1` bbox `[…]` (POS-3) and `photo2` bbox `[…]` (POS-4).
2. Opened `actual.json` → `objects`: POS-3 has readings in photo1 and photo2 (two evidence entries, one object); POS-4 has readings in photo2 and photo3. Confirms dedup: 4 detections → 2 objects.
3. Opened the photos, looked at the highlighted regions in the UI: both boxes carry `CBL-USB-1M` labels and distinct tags. Conclusion correct.
4. Checked the one thing the model could have got wrong: `sku_read` string for each detection matches the printed label character for character (`actual.json` → `objects[].evidence[].sku_read`).

## Measured time-to-useful-result

| Scenario | Server processing (from `usage.total_seconds`) | End-to-end in browser | Notes |
|---|---|---|---|
| A | _… s_ | _… s_ | |
| B | _… s_ | _… s_ | |
| C | _… s_ | _… s_ | |

## Measured cost per delivery

Pricing assumptions (USD per 1M tokens, taken from `pipeline/cost.py` `PRICING`; verify at
https://www.anthropic.com/pricing on the day of measurement):

| Model | Input | Output |
|---|---|---|
| claude-sonnet-5 | _$2.00_ | _$10.00_ |
| claude-haiku-4-5-20251001 | _$1.00_ | _$5.00_ |

| Scenario | Calls | Input tokens | Output tokens | Cost |
|---|---|---|---|---|
| A | _…_ | _…_ | _…_ | _$…_ |
| B | _…_ | _…_ | _…_ | _$…_ |
| C | _…_ | _…_ | _…_ | _$…_ |

Per-call detail is in the UI footer ("Per-call breakdown") and in `actual.json` → `usage.calls`.

**Hosting cost (separate from model cost):** the app is a single FastAPI process with no
database; _e.g. one small VM / container at ~$5–10 per month, or effectively $0 on a laptop_. Model
cost above scales per delivery; hosting does not.
