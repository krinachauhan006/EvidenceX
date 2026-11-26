"""OCR preprocessing that never breaks provenance.

Steps (each recorded in the extraction metadata):
1. contrast: greyscale + auto-contrast (no geometry change);
2. orientation: Tesseract OSD (needs the ``osd`` pack) detects 90/180/270-degree
   rotation; the page is rotated for OCR;
3. deskew: a small skew (0.5-8 degrees) is estimated from the row-projection profile and
   removed for OCR.
OCR runs on the processed image, and every word/line box is mapped BACK to the
coordinates of the original (EXIF-oriented) image, so highlights land on the original.
Text is never altered or translated.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


def _osd_rotation(image: Any, options: Mapping[str, Any]) -> int:
    try:
        import pytesseract

        from app.modules.processing.extractors.ocr_engine import find_tesseract

        path = find_tesseract(str(options.get("tesseract_cmd") or ""))
        if not path:
            return 0
        pytesseract.pytesseract.tesseract_cmd = path
        osd = pytesseract.image_to_osd(image, output_type=pytesseract.Output.DICT, timeout=30)
        if float(osd.get("orientation_conf", 0)) < 2.0:
            return 0
        return int(osd.get("rotate", 0)) % 360
    except Exception:  # noqa: BLE001 - OSD is optional (missing pack, too little text)
        return 0


def estimate_skew(grey: Any, max_deg: float = 8.0) -> float:
    """Skew angle (degrees) maximising the variance of dark-pixel row counts."""
    small = grey.copy()
    small.thumbnail((800, 800))
    w, h = small.size
    if w < 50 or h < 50:
        return 0.0
    best, best_score = 0.0, -1.0
    for step in [x / 2 for x in range(int(-max_deg * 2), int(max_deg * 2) + 1)]:
        rot = small.rotate(step, expand=False, fillcolor=255)
        px = rot.load()
        rows = [sum(1 for x in range(0, w, 2) if px[x, y] < 128) for y in range(0, h, 2)]
        mean = sum(rows) / len(rows)
        score = sum((r - mean) ** 2 for r in rows)
        if score > best_score:
            best, best_score = step, score
    return best if abs(best) >= 0.5 else 0.0


def _inverse_point(
    x: float, y: float, w: int, h: int, rot90: int, skew: float, rw: int, rh: int
) -> tuple[float, float]:
    """Map a point from the processed image back to the original image."""
    # undo deskew (rotation about the centre of the rotated-by-90 image, no expand)
    if skew:
        cx, cy = rw / 2, rh / 2
        a = math.radians(skew)  # PIL rotates counter-clockwise for positive angles
        dx, dy = x - cx, y - cy
        x = cx + dx * math.cos(a) - dy * math.sin(a)
        y = cy + dx * math.sin(a) + dy * math.cos(a)
    # undo the 90-degree-step rotation (PIL rotate(-r, expand=True) for OSD's "rotate")
    if rot90 == 90:  # image rotated clockwise by 90 for OCR
        return y, h - x
    if rot90 == 180:
        return w - x, h - y
    if rot90 == 270:
        return w - y, x
    return x, y


def map_box(box: list[float], ctx: dict[str, Any]) -> list[float]:
    x0, y0, x1, y1 = box
    pts = [
        _inverse_point(px, py, ctx["w"], ctx["h"], ctx["rot90"], ctx["skew"], ctx["rw"], ctx["rh"])
        for px, py in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))
    ]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return [
        max(0.0, min(xs)),
        max(0.0, min(ys)),
        min(float(ctx["w"]), max(xs)),
        min(float(ctx["h"]), max(ys)),
    ]


def prepare(image: Any, options: Mapping[str, Any]) -> tuple[Any, dict[str, Any]]:
    """(image for OCR, context to map boxes back). ``context['steps']`` lists what ran."""
    from PIL import ImageOps

    w, h = image.size
    grey = ImageOps.autocontrast(image.convert("L"), cutoff=1)
    steps = ["contrast"]
    rot90 = _osd_rotation(grey, options)
    if rot90:
        grey = grey.rotate(-rot90, expand=True, fillcolor=255)
        steps.append(f"orientation_{rot90}")
    skew = estimate_skew(grey)
    rw, rh = grey.size
    if skew:
        grey = grey.rotate(skew, expand=False, fillcolor=255)
        steps.append(f"deskew_{skew:+.1f}")
    return grey, {"w": w, "h": h, "rot90": rot90, "skew": skew, "rw": rw, "rh": rh, "steps": steps}


def map_data_back(data: Mapping[str, list], ctx: dict[str, Any]) -> dict[str, list]:
    """Rewrite word boxes in a pytesseract image_to_data dict to original coordinates."""
    if ctx["rot90"] == 0 and not ctx["skew"]:
        return dict(data)
    out = {k: list(v) for k, v in data.items()}
    for i in range(len(out.get("text", []))):
        try:
            left, top = float(out["left"][i]), float(out["top"][i])
            ww, hh = float(out["width"][i]), float(out["height"][i])
        except (TypeError, ValueError):
            continue
        x0, y0, x1, y1 = map_box([left, top, left + ww, top + hh], ctx)
        out["left"][i], out["top"][i] = x0, y0
        out["width"][i], out["height"][i] = x1 - x0, y1 - y0
    return out
