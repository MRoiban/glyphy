"""Learning the style rules from reference icons."""
from __future__ import annotations

import json

import numpy as np
from PIL import Image

from .config import Project
from .metrics import crispness, measure
from .raster import SVG_SUFFIXES, glyph_files, load_mask

SCALE = 32  # px per unit while measuring


def _stats(values):
    values = np.array([v for v in values if np.isfinite(v)], dtype=float)
    if not len(values):
        return None
    return {"median": round(float(np.median(values)), 3), "p10": round(float(np.percentile(values, 10)), 3),
            "p90": round(float(np.percentile(values, 90)), 3)}


def measure_references(project: Project) -> dict:
    """Measure every reference icon, derive the [style] rules, and write the baseline report."""
    grid = project.grid
    files = glyph_files(project.path("reference"))
    if not files:
        raise SystemExit(f"No reference icons in {project.path('reference')} (SVG or PNG, one icon per file).")
    rows, crisp = {}, {}
    for file in files:
        m = measure(load_mask(file, grid * SCALE), SCALE, grid)
        if m:
            rows[file.stem] = m
            if file.suffix.lower() in SVG_SUFFIXES:
                crisp[file.stem] = crispness(file, grid)

    strokes = [m.stroke for m in rows.values()]
    stroke = _stats(strokes)
    sides = _stats([max(m.width, m.height) for m in rows.values()])
    pads = _stats([m.min_pad for m in rows.values()])
    # Letterforms (several components or a tall narrow box) set the letter rules when present.
    letters = [m for m in rows.values() if m.height >= 0.6 * grid and m.width <= 0.75 * m.height]
    letter_strokes = _stats([m.stroke for m in letters]) if letters else None

    s = dict(project.style)
    s["stroke"] = round(stroke["median"], 2)
    # Typical icons, not outliers, define the live area; padding may shrink to 3/4 of the typical one.
    s["live"] = round(min(float(grid), sides["median"]), 2)
    s["pad_min"] = round(max(0.25, 0.75 * min(pads["median"], (grid - s["live"]) / 2)), 2)
    s["letter_height"] = round(float(np.median([m.height for m in letters])) if letters else s["live"] * 0.85, 2)
    low = min(s["stroke"] * 0.95, letter_strokes["p10"] if letter_strokes else s["stroke"])
    high = max(stroke["p90"], letter_strokes["p90"] if letter_strokes else s["stroke"] * 1.45)
    s["letter_stroke"] = [round(low, 2), round(high, 2)]
    if crisp:
        s["crisp_reference"] = round(float(np.median(list(crisp.values()))), 2)
    # References trade exact centring for pixel alignment (an odd-width glyph on an
    # even grid cannot have both); allow as much off-centring as they show.
    centring = _stats([m.centring for m in rows.values()])
    s["centring_max"] = round(max(0.5, centring["p90"]), 2)
    # Hand-pinned values win over measurement.
    locked = set(project.style.get("locked", []))
    for key in ["stroke", "live", "pad_min", "letter_height", "letter_stroke", "crisp_reference", "centring_max"]:
        if key not in locked:
            project.style[key] = s[key]
    s = project.style

    baseline = {
        "icons": len(rows), "grid": grid,
        "stroke": stroke, "box_side": sides, "min_pad": pads,
        "coverage": _stats([m.coverage for m in rows.values()]),
        "centring": centring,
        "crispness": _stats(list(crisp.values())) if crisp else None,
        "letterforms": {"count": len(letters), "stroke": letter_strokes},
        "locked": sorted(locked),
        "derived_style": {k: s[k] for k in ["stroke", "live", "pad_min", "letter_height", "letter_stroke", "crisp_reference", "centring_max"]},
        "icons_measured": {name: m.as_dict() for name, m in rows.items()},
    }
    out = project.path("out")
    out.mkdir(parents=True, exist_ok=True)
    (out / "baseline.json").write_text(json.dumps(baseline, indent=1))
    reference_sheet(project, files)
    return baseline


def reference_sheet(project: Project, files=None, columns: int = 6, limit: int = 18) -> None:
    """A black-on-white sheet of reference icons to show the image model the style."""
    grid = project.grid
    files = (files or glyph_files(project.path("reference")))[:limit]
    cell = grid * 24
    rows = (len(files) + columns - 1) // columns
    sheet = Image.new("L", (cell * columns, cell * max(rows, 1)), 255)
    for i, file in enumerate(files):
        mask = load_mask(file, grid * 20)
        tile = Image.fromarray(np.where(mask, 0, 255).astype("uint8"))
        sheet.paste(tile, ((i % columns) * cell + grid * 2, (i // columns) * cell + grid * 2))
    sheet.save(project.path("out") / "reference-sheet.png")
