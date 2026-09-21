# Delivery notes

Prototype: verify delivery photos against a packing-list PDF.
Live demo: https://delivery-check.onrender.com  ·  Repository: https://github.com/dandobr/delivery-check

## Sample inputs and expected/actual results

Test material is in `fixtures/`. Each folder holds the packing list, the photos, `physical_contents.json`
(what was actually in the delivery), and `expected.json` (outcomes recorded **before** the first run).
`python scripts/run_tests.py` runs the same function the web endpoint calls and diffs field by field.

Real photographs of household objects carrying printed labels from `samples/label_sheet.pdf`:

| Scenario | Expected | Actual | Match | Time | Cost |
|---|---|---|---|---|---|
| A normal (3 rows) | confirmed x3 | confirmed, confirmed, confirmed | yes | 7.3 s | $0.0328 |
| B messy (5 rows) | confirmed, identity mismatch, quantity mismatch, unverified, unverified | confirmed, identity mismatch, quantity mismatch, unverified, unverified | yes | 13.7 s | $0.0461 |
| C corrected (5 rows) | confirmed x5 | confirmed, confirmed, confirmed, confirmed, confirmed | yes | 5.1 s | $0.0319 |

Scenario A also carried one item that is **not** on the packing list (a HEPA filter box). The app did not
attribute it to any row; it is listed separately as an unexpected SKU. That is the no-false-positive check.

Scenario B is the hard case, all four difficulties in one delivery:

| Packing-list row | Physically delivered | App result |
|---|---|---|
| 1 BRK-2200 | correct, tag POS-1 | confirmed |
| 2 WGT-X100 | WGT-X200 delivered instead, tag POS-2 | identity mismatch |
| 3 CBL-USB-1M qty 1 | two units, tags POS-3 and POS-6 | quantity mismatch, found 2 of 1 |
| 4 FLT-HEPA-S | present, tag POS-4, label flipped blank-side-up | unverified, asks for a clearer photo of POS-4 |
| 5 PSU-65W | absent from the delivery | unverified, never "missing" |

Synthetic fixtures (rendered images, kept as a cheap deterministic second test set, including the
decline-to-conclude case):

| Scenario | Result | Time | Cost |
|---|---|---|---|
| synthetic a-normal | complete, confirmed, confirmed, confirmed | 6.0 s | $0.0261 |
| synthetic b-messy | complete, confirmed, identity_mismatch, quantity_mismatch, unverified, unverified | 7.0 s | $0.0317 |
| synthetic c-corrected | complete, confirmed, confirmed, confirmed, confirmed, confirmed | 4.3 s | $0.0287 |
| synthetic d-unclear | needs_clarification, unverified, unverified, unverified | 4.2 s | $0.0092 |

Harness output, all seven folders:

```
7 scenario(s) run, 0 failed
```

## What failed

Found and fixed while building, all visible in the git history:

1. **Structured-output schema rejected a bbox array constraint.** Every vision call silently fell back to a
   second plain-text request, doubling cost. The constraint is now validated in code instead.
2. **Bounding boxes were mis-scaled on non-square images.** Asking for fractions produced x divided by the
   height in 2 of 3 photos, so the rightmost box came back pinned to the right edge. The prompt now states
   the exact pixel dimensions and asks for pixel coordinates, which the code converts. Boxes now land within
   1% of the true positions.
3. **A retry path swallowed real errors.** The plain-text fallback also triggered on billing and auth
   failures, hiding the cause. It now only catches structured-output rejections.
4. **The printed tag sheet ran out of tags.** The extra unit in scenario B needed a sixth tag that the sheet
   did not have. The sheet now prints seven, and the vision prompt no longer names a fixed tag range.

Not fixed, accepted for this prototype: see "Known limitations" in the README.

Nothing failed on the real photographs. All three scenarios passed on the first live run with no prompt
changes, including a label photographed blank-side-up and two identical SKUs on different objects.

## Time spent

| Activity | Time |
|---|---|
| Building the prototype with Claude Code, supervised | 3 h |
| Printing labels, preparing the objects, photographing | 1 h |
| Running the scenarios, debugging, fixing the four defects above | 1 h |
| Deploying, write-up and video | 1 h |
| **Total** | **6 h** |

Within the eight-hour budget the brief suggests. The largest single saving was generating the test kit:
the label sheet and both packing lists come from `scripts/`, so re-cutting the test set after changing a
product name is a one-command job rather than an afternoon.

## AI tools and models used

Code generation: Claude Code, models Claude Fable 5.1 and Claude Opus 5, in one working session.
Everything in the repository was generated that way; see "Reused components" in the README for the
library-by-library split and what was written for this brief.

In the running product, via the official `anthropic` Python SDK with structured outputs:

| Model | Job | Calls per delivery |
|---|---|---|
| `claude-haiku-4-5-20251001` | packing-list text to structured rows | 1 |
| `claude-sonnet-5` | read position tags and SKU labels in one photo | 1 per photo |
| `claude-sonnet-5` | judge whether an unmatched SKU is a variant of a row | 0 or 1 |

No speech, no OCR service, no other paid intermediary. Matching itself is plain deterministic Python, so
every status is auditable without a model in the loop.

## How I checked an AI output by hand

Worked example, scenario B row 3, the quantity mismatch.

1. The app reported `quantity_mismatch`, found 2 of 1, citing POS-3 in photo1 and photo3, and POS-6 in photo3.
2. I opened `fixtures/scenario-b-messy/actual.json` and read the `objects` list. POS-3 has two evidence
   entries, one per photo; POS-6 has one. Four sightings across the photos collapsed into two objects, which
   is the anti-double-counting rule working.
3. I opened photo1 and photo3 and looked at the highlighted regions in the web UI. Both objects genuinely
   carry a `CBL-USB-1M` label, and their position tags differ, so they are two physical units.
4. I compared the model's `sku_read` string against the printed label character by character. Exact match,
   including the dashes.
5. I checked the packing list: row 3 orders one unit. Two delivered, one ordered, so the status is right.

I ran the same check on row 4, where the label was face-down. The model returned `label_readable: false`
with no SKU rather than guessing from the visible product name, which is the behaviour the prompt demands.

## Measured time to a useful result

Measured on the real photographs, three photos per delivery, from `usage.total_seconds`.

| Scenario | Server processing |
|---|---|
| A normal | 7.3 s |
| B messy | 13.7 s |
| C corrected | 5.1 s |
| Average | 8.7 s |

Through the hosted demo, scenario B end to end from the browser was 9.1 s against 8.4 s of server
processing. The free hosting tier sleeps after 15 minutes idle and the first request then takes 30 to 60
seconds to wake the container; that is a hosting characteristic, not model latency.

The packing-list parse and the per-photo vision calls run concurrently, so wall-clock time tracks the
slowest photo rather than the sum. The busiest photo in scenario B took 11.6 s because it contained four
tagged objects.

## Measured cost per delivery

Pricing assumptions, USD per million tokens, from `PRICING` in `pipeline/cost.py`, checked against
anthropic.com/pricing on 2026-09-21:

| Model | Input | Output |
|---|---|---|
| claude-sonnet-5 | $2.00 | $10.00 |
| claude-haiku-4-5-20251001 | $1.00 | $5.00 |

| Scenario | Calls | Input tokens | Output tokens | Cost |
|---|---|---|---|---|
| a-normal | 5 | 12,049 | 987 | $0.0328 |
| b-messy | 5 | 12,195 | 2,328 | $0.0461 |
| c-corrected | 4 | 11,217 | 1,110 | $0.0319 |
| **Average** | | | | **$0.0369** |

So roughly **4 cents per delivery** of three photos and five rows. Cost is dominated by image
input: each photo costs about 3,500 input tokens regardless of content, so the number of photos drives the
bill far more than the number of rows.

Counted in the figures above: every model call the pipeline makes, including the identity judgment.
Not counted, and not billed: SDK transport retries, which only fire on a failed request. There were none
in these runs. No speech, recognition or third-party service is used, so there is no other variable cost.

**Hosting, separate from the above:** Render free tier, $0 per month, one web service, no database, nothing
stored between requests. A paid instance that does not sleep is $7 per month at the time of writing. Free
credits are not zero operating cost; the $ figures above are what the API bills once credits run out.

## What I would improve next

1. Cheaper per-photo pass: downscale more aggressively and crop to detected tag regions before the full
   read, or route the first pass to Haiku and escalate to Sonnet only where a label is hard to read.
2. Let the user draw a box and ask "what does this say" instead of re-uploading a whole photo.
3. Accept HEIC directly; phone photos currently need converting before upload.
4. Confidence-weighted disagreement: if two photos read the same tag as different SKUs, surface it rather
   than taking the more confident reading.
