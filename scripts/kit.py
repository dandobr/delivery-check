"""Shared definition of the physical test kit.

EDIT HERE to change placeholder product names / SKUs. Every generator
(label sheet, packing lists, synthetic photos) reads from this file, so the
labels, the PDFs and expected.json stay consistent.
"""

# Row order below = row order on packing list "Order B" (5 items).
PRODUCTS = [
    {"sku": "BRK-2200",   "name": "Bracket Kit 2200"},        # row 1
    {"sku": "WGT-X100",   "name": "Widget X100"},             # row 2  (wrong-but-similar variant below)
    {"sku": "CBL-USB-1M", "name": "USB-C Cable 1 m"},         # row 3  (extra unit in scenario B -> 2 labels printed)
    {"sku": "FLT-HEPA-S", "name": "HEPA Filter, Small"},      # row 4  (label obscured in scenario B)
    {"sku": "PSU-65W",    "name": "Power Supply 65 W"},       # row 5  (out of frame in scenario B)
]

# The "wrong-but-similar" SKU delivered instead of row 2 in scenario B.
ALTERNATE_FOR_ROW_2 = {"sku": "WGT-X200", "name": "Widget X200"}

POSITION_TAGS = ["POS-1", "POS-2", "POS-3", "POS-4", "POS-5"]

# Order A = first three products, qty 1 each. Order B = all five, qty 1 each.
ORDER_A = {"ref": "ORD-A-1001", "rows": [dict(p, qty=1) for p in PRODUCTS[:3]]}
ORDER_B = {"ref": "ORD-B-1002", "rows": [dict(p, qty=1) for p in PRODUCTS]}

SHIP_TO = ["Acme Receiving Dock", "12 Example Street", "Springfield"]
SUPPLIER = "Northwind Components Ltd."
