#!/usr/bin/env python3
"""Generate the two sample packing-list PDFs (Order A and Order B) from scripts/kit.py.

Writes samples/packing_list_order_A.pdf and samples/packing_list_order_B.pdf and copies
them into the fixture folders as packing_list.pdf (A -> scenario-a, B -> scenario-b and -c).
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kit import ORDER_A, ORDER_B, SHIP_TO, SUPPLIER  # noqa: E402

from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
FIXTURES = ROOT / "fixtures"


def write_packing_list(order: dict, out: Path):
    c = canvas.Canvas(str(out), pagesize=A4)
    W, H = A4
    c.setTitle(f"Packing list {order['ref']}")
    c.setFont("Helvetica-Bold", 20)
    c.drawString(20 * mm, H - 25 * mm, "PACKING LIST")
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, H - 33 * mm, f"Order reference: {order['ref']}")
    c.drawString(20 * mm, H - 38 * mm, "Date: 2026-09-20")
    c.drawString(120 * mm, H - 33 * mm, f"Supplier: {SUPPLIER}")
    c.drawString(120 * mm, H - 38 * mm, "Ship to:")
    for i, line in enumerate(SHIP_TO):
        c.drawString(120 * mm, H - 43 * mm - i * 5 * mm, line)

    y = H - 70 * mm
    c.setFillColor(colors.HexColor("#e6e6e6"))
    c.rect(20 * mm, y - 2 * mm, 170 * mm, 8 * mm, fill=1, stroke=0)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(22 * mm, y, "#")
    c.drawString(32 * mm, y, "SKU")
    c.drawString(70 * mm, y, "Description")
    c.drawRightString(185 * mm, y, "Qty")
    c.setFont("Helvetica", 10)
    for i, row in enumerate(order["rows"], start=1):
        y -= 9 * mm
        c.drawString(22 * mm, y, str(i))
        c.drawString(32 * mm, y, row["sku"])
        c.drawString(70 * mm, y, row["name"])
        c.drawRightString(185 * mm, y, str(row["qty"]))
        c.setStrokeColor(colors.HexColor("#cccccc"))
        c.line(20 * mm, y - 2.5 * mm, 190 * mm, y - 2.5 * mm)
    y -= 14 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(185 * mm, y, f"Total units: {sum(r['qty'] for r in order['rows'])}")
    c.setFont("Helvetica", 8)
    c.drawString(20 * mm, 20 * mm, "Please check contents against this list on receipt and report discrepancies within 48 hours.")
    c.showPage()
    c.save()
    print(f"wrote {out}")


def main():
    SAMPLES.mkdir(exist_ok=True)
    a = SAMPLES / "packing_list_order_A.pdf"
    b = SAMPLES / "packing_list_order_B.pdf"
    write_packing_list(ORDER_A, a)
    write_packing_list(ORDER_B, b)
    for scenario, src in (("scenario-a-normal", a), ("scenario-b-messy", b), ("scenario-c-corrected", b)):
        dst = FIXTURES / scenario / "packing_list.pdf"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dst)
        print(f"copied -> {dst}")


if __name__ == "__main__":
    main()
