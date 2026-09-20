"""Stage 1: packing-list PDF -> structured rows (pdfplumber text + Haiku)."""
from __future__ import annotations

import io
import logging

import pdfplumber

from .cost import CostTracker
from .llm import PARSE_MODEL, call_json

log = logging.getLogger("pipeline.packing_list")

ROWS_SCHEMA = {
    "type": "object",
    "properties": {
        "order_reference": {"type": ["string", "null"]},
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "row_number": {"type": "integer"},
                    "sku": {"type": "string"},
                    "name": {"type": "string"},
                    "expected_qty": {"type": "integer"},
                },
                "required": ["row_number", "sku", "name", "expected_qty"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["order_reference", "rows"],
    "additionalProperties": False,
}

SYSTEM = """You convert the text of a one-page packing list into structured line items.

Rules:
- Return one entry per physical line item, in the order printed. row_number starts at 1 and
  follows the printed line order (use the printed line/row number if there is one).
- sku is the product/SKU code exactly as printed (keep dashes and case).
- name is the product description as printed.
- expected_qty is the integer quantity ordered/shipped for that line.
- Ignore headers, totals, addresses, signatures and footer text.
- Never invent rows. If the text has no line items, return an empty rows list.
"""


def extract_pdf_text(pdf_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pages = [(p.extract_text() or "") for p in pdf.pages]
    return "\n\n".join(pages).strip()


def parse_packing_list(pdf_bytes: bytes, tracker: CostTracker) -> dict:
    text = extract_pdf_text(pdf_bytes)
    if not text:
        raise ValueError("The packing list PDF has no extractable text (scanned image PDFs are not supported).")
    log.info("packing list text: %d chars", len(text))
    result = call_json(
        purpose="parse_packing_list",
        model=PARSE_MODEL,
        system=SYSTEM,
        content=f"<packing_list_text>\n{text}\n</packing_list_text>",
        schema=ROWS_SCHEMA,
        tracker=tracker,
        max_tokens=2000,
    )
    rows = sorted(result.get("rows", []), key=lambda r: r["row_number"])
    return {"order_reference": result.get("order_reference"), "rows": rows, "raw_text": text}
