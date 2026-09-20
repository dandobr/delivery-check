#!/usr/bin/env python3
"""Render synthetic 'delivery photos' (drawn boxes with labels) for smoke-testing the pipeline
before real photos of the physical kit exist.

Writes fixtures/synthetic/<scenario>/ with packing_list.pdf, photo1..3.jpg and expected.json.
The scenarios mirror scenario-a/b/c. These are cartoons, not photos - they prove the code path
end to end (real API calls, real dedup, real matching), not the vision model's robustness on
real-world images.
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kit import ALTERNATE_FOR_ROW_2, PRODUCTS  # noqa: E402

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "fixtures"
OUT = FIX / "synthetic"
W, H = 1400, 1000


def font(size):
    for name in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Helvetica.ttc",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_box(d: ImageDraw.ImageDraw, x, y, w, h, tag, sku, name, obscured=False, no_tag=False):
    d.rectangle([x, y, x + w, y + h], fill=(196, 160, 110), outline=(120, 90, 50), width=4)
    d.line([x, y + h * 0.5, x + w, y + h * 0.5], fill=(150, 115, 70), width=3)
    # product label (white sticker)
    lx, ly, lw, lh = x + 20, y + 20, w - 40, 110
    d.rectangle([lx, ly, lx + lw, ly + lh], fill="white", outline="black", width=2)
    d.text((lx + 10, ly + 8), name, fill="black", font=font(24))
    d.text((lx + 10, ly + 42), sku, fill="black", font=font(40))
    for i in range(0, lw - 40, 6):  # fake barcode
        if i % 3:
            d.rectangle([lx + 10 + i, ly + 92, lx + 12 + i, ly + lh - 4], fill="black")
    if obscured:  # a strip of packing tape / smudge over the SKU text
        d.rectangle([lx + 5, ly + 36, lx + lw - 5, ly + 88], fill=(170, 150, 120))
        d.rectangle([lx + 5, ly + 36, lx + lw - 5, ly + 88], outline=(140, 120, 90), width=3)
    if no_tag:
        return
    # position tag (yellow sticker, bottom right)
    tx, ty, tw, th = x + w - 150, y + h - 90, 130, 70
    d.rectangle([tx, ty, tx + tw, ty + th], fill=(255, 230, 60), outline="black", width=3)
    d.text((tx + 10, ty + 4), "POSITION", fill="black", font=font(16))
    d.text((tx + 10, ty + 24), tag, fill="black", font=font(38))


def render(objects, out: Path):
    img = Image.new("RGB", (W, H), (225, 222, 215))
    d = ImageDraw.Draw(img)
    d.rectangle([0, H * 0.55, W, H], fill=(190, 186, 178))  # floor
    slots = [(60, 120), (520, 90), (980, 130), (300, 520), (800, 540)]
    for (x, y), obj in zip(slots, objects):
        draw_box(d, x, y, 380, 320, obj["tag"], obj["sku"], obj["name"], obj.get("obscured", False), obj.get("no_tag", False))
    img.save(out, "JPEG", quality=90)


def P(i):
    return PRODUCTS[i]


SCENARIOS = {
    "scenario-a-normal": {
        "pdf": "packing_list_order_A.pdf",
        "objects": {
            "POS-1": dict(tag="POS-1", **P(0)), "POS-2": dict(tag="POS-2", **P(1)), "POS-3": dict(tag="POS-3", **P(2)),
        },
        "photos": [["POS-1", "POS-2", "POS-3"], ["POS-1", "POS-2"], ["POS-2", "POS-3"]],
    },
    "scenario-b-messy": {
        "pdf": "packing_list_order_B.pdf",
        "objects": {
            "POS-1": dict(tag="POS-1", **P(0)),
            "POS-2": dict(tag="POS-2", **ALTERNATE_FOR_ROW_2),   # wrong-but-similar SKU
            "POS-3": dict(tag="POS-3", **P(2)),
            "POS-4": dict(tag="POS-4", **P(2)),                  # extra unit of row 3
            "POS-5": dict(tag="POS-5", obscured=True, **P(3)),   # row 4, label obscured
            # row 5 (PSU-65W) never appears
        },
        "photos": [["POS-1", "POS-2", "POS-3"], ["POS-3", "POS-4", "POS-5"], ["POS-1", "POS-4", "POS-5"]],
    },
    "scenario-c-corrected": {
        "pdf": "packing_list_order_B.pdf",
        "objects": {f"POS-{i+1}": dict(tag=f"POS-{i+1}", **P(i)) for i in range(5)},
        "photos": [["POS-1", "POS-2", "POS-3"], ["POS-3", "POS-4", "POS-5"], ["POS-1", "POS-4", "POS-5"]],
    },
    "scenario-d-unclear": {
        "pdf": "packing_list_order_A.pdf",
        "objects": {f"N{i}": dict(tag="", no_tag=True, **P(i)) for i in range(3)},   # labels visible, NO position tags
        "photos": [["N0", "N1", "N2"]],
    },
}


def main():
    for name, sc in SCENARIOS.items():
        folder = OUT / name
        folder.mkdir(parents=True, exist_ok=True)
        pdf = ROOT / "samples" / sc["pdf"]
        if not pdf.exists():
            sys.exit(f"{pdf} missing - run scripts/make_packing_lists.py first")
        shutil.copy(pdf, folder / "packing_list.pdf")
        for i, tags in enumerate(sc["photos"], start=1):
            render([sc["objects"][t] for t in tags], folder / f"photo{i}.jpg")
        for fname in ("expected.json", "physical_contents.json"):
            src = FIX / name / fname
            if src.exists():
                shutil.copy(src, folder / fname)
        print(f"wrote {folder}")


if __name__ == "__main__":
    main()
