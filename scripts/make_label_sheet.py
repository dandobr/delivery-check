#!/usr/bin/env python3
"""Generate samples/label_sheet.pdf (A4): SKU labels, position tags, alternate label.

Product names/SKUs come from scripts/kit.py - edit PRODUCTS there.
Print at 100% scale, cut along the borders, stick one SKU label + one POS tag on each box.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kit import ALTERNATE_FOR_ROW_2, POSITION_TAGS, PRODUCTS  # noqa: E402

from reportlab.graphics.barcode import code128  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "samples" / "label_sheet.pdf"

LABEL_W, LABEL_H = 90 * mm, 35 * mm
TAG_W, TAG_H = 42 * mm, 42 * mm
MARGIN_X, TOP = 12 * mm, 285 * mm


def sku_label(c, x, y, sku, name, note=None):
    c.setLineWidth(0.6)
    c.setDash(3, 3)
    c.rect(x, y, LABEL_W, LABEL_H)
    c.setDash()
    c.setFont("Helvetica", 8)
    c.drawString(x + 4 * mm, y + LABEL_H - 6 * mm, "PRODUCT LABEL")
    c.setFont("Helvetica-Bold", 13)
    c.drawString(x + 4 * mm, y + LABEL_H - 12 * mm, name)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(x + 4 * mm, y + LABEL_H - 21 * mm, sku)
    bc = code128.Code128(sku, barHeight=7 * mm, barWidth=0.35 * mm, humanReadable=False)
    bc.drawOn(c, x + 4 * mm, y + 3 * mm)
    c.setFont("Helvetica", 7)
    c.drawRightString(x + LABEL_W - 3 * mm, y + 3 * mm, f"SKU {sku}")
    if note:
        c.setFont("Helvetica-Oblique", 7)
        c.drawRightString(x + LABEL_W - 3 * mm, y + LABEL_H - 6 * mm, note)


def pos_tag(c, x, y, tag):
    c.setLineWidth(1.2)
    c.rect(x, y, TAG_W, TAG_H)
    c.setFont("Helvetica", 8)
    c.drawCentredString(x + TAG_W / 2, y + TAG_H - 7 * mm, "POSITION TAG")
    c.setFont("Helvetica-Bold", 30)
    c.drawCentredString(x + TAG_W / 2, y + 12 * mm, tag)


def main():
    OUT.parent.mkdir(exist_ok=True)
    c = canvas.Canvas(str(OUT), pagesize=A4)
    c.setTitle("Delivery test kit - label sheet")

    c.setFont("Helvetica-Bold", 12)
    c.drawString(MARGIN_X, TOP, "Delivery verification test kit - label sheet (print at 100%, A4)")
    c.setFont("Helvetica", 8)
    c.drawString(MARGIN_X, TOP - 5 * mm,
                 "Each box gets ONE product label + ONE position tag, both visible from the camera. Edit names in scripts/kit.py.")

    # Column 1: SKU labels (5 products + extra copy of row 3 + alternate for row 2)
    labels = [(p["sku"], p["name"], f"row {i}") for i, p in enumerate(PRODUCTS, start=1)]
    labels.append((PRODUCTS[2]["sku"], PRODUCTS[2]["name"], "row 3 - 2nd unit (scenario B extra)"))
    labels.append((ALTERNATE_FOR_ROW_2["sku"], ALTERNATE_FOR_ROW_2["name"], "ALTERNATE for row 2 (scenario B wrong SKU)"))
    y = TOP - 12 * mm - LABEL_H
    for sku, name, note in labels:
        sku_label(c, MARGIN_X, y, sku, name, note)
        y -= LABEL_H + 2 * mm

    # Column 2: position tags
    x = MARGIN_X + LABEL_W + 8 * mm
    y = TOP - 12 * mm - TAG_H
    for tag in POSITION_TAGS:
        pos_tag(c, x, y, tag)
        y -= TAG_H + 3 * mm

    c.showPage()
    c.save()
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
