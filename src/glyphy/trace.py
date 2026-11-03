"""Draft image → style-conformant SVG, verified by measurement.

Per draft (every number comes from `Project.settings(glyph)`, so any step can be
tuned globally in [trace]/[style] or for one glyph in [glyphs.<name>]):

1. Ink mask at `work_scale` px per grid unit (`threshold`, `speck`).
2. Fit into the target box (`fit`; icons: live × live, letters: letter_height
   tall; a glyph may set its own `box = [w, h]`).
3. Correct the stroke from measurement (`correct`, `rounds`, `stroke_epsilon`;
   a glyph may force `stroke_target`).
4. Trace with potrace (`turdsize`, `alphamax`, `opticurve`, `opttolerance`);
   snap straight corners near whole pixels (`snap`); try sub-pixel offsets and
   keep the most crisp result that passes (`offsets`).
5. Re-render and measure with the same code as the references.

The functions are public so they can be composed differently from Python.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

from .config import Project
from .metrics import Metrics, crispness, measure, measure_svg
from .raster import RASTER_SUFFIXES, glyph_files, render_svg


def glyph_name(stem: str) -> str:
    """`heading-2` → `heading`; a stem without a numeric suffix is its own name."""
    head, _, tail = stem.rpartition("-")
    return head if head and tail.isdigit() else stem


def box_for(cfg: dict) -> tuple[float, float]:
    if "box" in cfg:
        return float(cfg["box"][0]), float(cfg["box"][1])
    if cfg.get("kind") == "letter":
        return float(cfg["live"]), float(cfg["letter_height"])
    return float(cfg["live"]), float(cfg["live"])


def stroke_target(cfg: dict, measured: float) -> float:
    if "stroke_target" in cfg:
        return float(cfg["stroke_target"])
    if cfg.get("kind") == "letter":
        low, high = cfg["letter_stroke"]
        return float(min(max(measured, low), high))
    return float(cfg["stroke"])


def ink_mask(path: Path, cfg: dict, grid: int) -> np.ndarray:
    size = grid * int(cfg["work_scale"])
    if path.suffix.lower() not in RASTER_SUFFIXES:
        return render_svg(path, size)
    pixels = np.array(Image.open(path).convert("L").resize((size, size), Image.LANCZOS), dtype=float)
    mask = pixels < float(cfg["threshold"])
    labels, count = ndimage.label(mask)
    if count:
        sizes = ndimage.sum(mask, labels, range(1, count + 1))
        mask = np.isin(labels, np.nonzero(sizes >= mask.size * float(cfg["speck"]))[0] + 1)
    return mask


def fit(mask: np.ndarray, grid: int, work: int, box_w: float, box_h: float) -> np.ndarray:
    ys, xs = np.nonzero(mask)
    crop = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = crop.shape
    factor = min(box_w * work / w, box_h * work / h)
    size = (max(1, round(w * factor)), max(1, round(h * factor)))
    small = np.array(Image.fromarray((crop * 255).astype("uint8")).resize(size, Image.LANCZOS)) > 127
    canvas = np.zeros((grid * work, grid * work), bool)
    oy, ox = (canvas.shape[0] - small.shape[0]) // 2, (canvas.shape[1] - small.shape[1]) // 2
    canvas[oy:oy + small.shape[0], ox:ox + small.shape[1]] = small
    return canvas


def adjust_stroke(mask: np.ndarray, grid: int, work: int, target: float) -> np.ndarray:
    radius = (target - measure(mask, work, grid).stroke) / 2 * work
    if not np.isfinite(radius) or abs(radius) < 1:
        return mask
    op = ndimage.binary_dilation if radius > 0 else ndimage.binary_erosion
    return op(mask, ndimage.generate_binary_structure(2, 1), iterations=int(round(abs(radius))))


def normalise(mask: np.ndarray, cfg: dict, grid: int) -> tuple[np.ndarray, float, float]:
    """Fit and correct until stroke and box both hold. Returns (mask, raw stroke, target)."""
    work, box = int(cfg["work_scale"]), box_for(cfg)
    current = fit(mask, grid, work, *box) if cfg["fit"] else mask
    raw = measure(current, work, grid).stroke
    target = stroke_target(cfg, raw)
    if not cfg["correct"]:
        return current, raw, target
    for _ in range(int(cfg["rounds"])):
        current = adjust_stroke(current, grid, work, target)
        m = measure(current, work, grid)
        if cfg["fit"] and max(m.width - box[0], m.height - box[1]) > 0.05:
            current = fit(current, grid, work, *box)
            m = measure(current, work, grid)
        if abs(m.stroke - target) <= float(cfg["stroke_epsilon"]):
            break
    return current, raw, target


def to_svg(mask: np.ndarray, cfg: dict, grid: int) -> str:
    import potrace

    snap, work, decimals = float(cfg["snap"]), int(cfg["work_scale"]), int(cfg["decimals"])

    def snapped(v: float) -> float:
        nearest = round(v)
        return float(nearest) if abs(v - nearest) <= snap else v

    def num(v: float) -> str:
        return f"{v:.{decimals}f}".rstrip("0").rstrip(".") if decimals else str(round(v))

    # potracer treats dark (low) values as ink, like a scanned page.
    paths = potrace.Bitmap(~mask).trace(turdsize=int(cfg["turdsize"]), alphamax=float(cfg["alphamax"]),
                                        opticurve=bool(cfg["opticurve"]), opttolerance=float(cfg["opttolerance"]))
    k = 1 / work
    parts = []
    for curve in paths:
        start = (curve.start_point.x * k, curve.start_point.y * k)
        sx, sy = snapped(start[0]), snapped(start[1])
        prev_shift = (sx - start[0], sy - start[1])
        parts.append(f"M{num(sx)} {num(sy)}")
        for seg in curve.segments:
            end = (seg.end_point.x * k, seg.end_point.y * k)
            # Only straight runs snap: snapping curve endpoints makes round shapes lumpy.
            ex, ey = (snapped(end[0]), snapped(end[1])) if seg.is_corner else end
            shift = (ex - end[0], ey - end[1])
            if seg.is_corner:
                parts.append(f"L{num(snapped(seg.c.x * k))} {num(snapped(seg.c.y * k))}L{num(ex)} {num(ey)}")
            else:
                c1 = (seg.c1.x * k + prev_shift[0], seg.c1.y * k + prev_shift[1])
                c2 = (seg.c2.x * k + shift[0], seg.c2.y * k + shift[1])
                parts.append(f"C{num(c1[0])} {num(c1[1])} {num(c2[0])} {num(c2[1])} {num(ex)} {num(ey)}")
            prev_shift = shift
        parts.append("Z")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {grid} {grid}" fill="currentColor">'
            f'<path fill-rule="evenodd" d="{"".join(parts)}"/></svg>\n')


def check(m: Metrics, cfg: dict, target: float) -> dict:
    if cfg.get("kind") == "letter" and "stroke_target" not in cfg:
        low, high = cfg["letter_stroke"]
        stroke_ok = low <= m.stroke <= high
    else:
        stroke_ok = abs(m.stroke - target) <= float(cfg["stroke_tolerance"])
    box = box_for(cfg)
    result = {
        "kind": cfg.get("kind", "icon"), "stroke": round(m.stroke, 3), "stroke_target": round(target, 3), "stroke_ok": bool(stroke_ok),
        "box": [round(m.width, 2), round(m.height, 2)], "box_ok": m.width <= box[0] + 0.1 and m.height <= max(box) + 0.1,
        "min_pad": round(m.min_pad, 2), "pad_ok": m.min_pad >= float(cfg["pad_min"]) - 0.01,
        "centring": round(m.centring, 2), "centring_ok": m.centring <= float(cfg["centring_max"]),
    }
    result["ok"] = all(result[k] for k in ["stroke_ok", "box_ok", "pad_ok", "centring_ok"])
    return result


def check_svg(project: Project, svg, kind: str | None = None, overrides: dict | None = None) -> dict:
    """Check a finished SVG (hand-drawn or traced) against the style."""
    name = glyph_name(Path(svg).stem) if isinstance(svg, Path) else None
    cfg = {**project.settings(name), **({"kind": kind} if kind else {}), **(overrides or {})}
    cfg.setdefault("kind", "icon")
    m = measure_svg(svg, project.grid)
    if m is None:
        return {"ok": False, "error": "no ink"}
    return {**check(m, cfg, stroke_target(cfg, m.stroke)), "crisp": round(crispness(svg, project.grid), 2)}


def trace_file(project: Project, path: Path, overrides: dict | None = None) -> tuple[str, dict]:
    name = glyph_name(path.stem)
    cfg = {**project.settings(name), **(overrides or {})}
    cfg.setdefault("kind", "icon")
    grid, work = project.grid, int(cfg["work_scale"])
    mask = ink_mask(path, cfg, grid)
    if not mask.any():
        return "", {"glyph": name, "ok": False, "error": "no ink found"}
    normal, raw, target = normalise(mask, cfg, grid)
    offsets = max(1, int(cfg["offsets"]))
    # Evenly spaced shifts across one grid unit, e.g. 4 → -0.5, -0.25, 0, +0.25 units.
    shifts = [round(k * work / offsets) - work // 2 for k in range(offsets)] if offsets > 1 else [0]
    best = None
    for dy in shifts:
        for dx in shifts:
            shifted = np.roll(normal, (dy, dx), axis=(0, 1))
            svg = to_svg(shifted, cfg, grid)
            m = measure_svg(svg, grid)
            if m is None:
                continue
            result = {**check(m, cfg, target), "crisp": round(crispness(svg, grid), 2)}
            # Prefer crisp edges, but not at any cost in centring.
            score = (result["ok"], result["crisp"] - float(cfg["centring_weight"]) * result["centring"])
            if best is None or score > best[0]:
                best = (score, svg, result)
    if best is None:
        return "", {"glyph": name, "ok": False, "error": "tracing produced no ink"}
    _, svg, result = best
    return svg, {"glyph": name, "raw_stroke": round(raw, 3), **result, "bytes": len(svg)}


def trace_all(project: Project, only: list[str] | None = None, overrides: dict | None = None) -> dict:
    src, dst = project.path("generated"), project.path("traced")
    dst.mkdir(parents=True, exist_ok=True)
    out = project.path("out")
    out.mkdir(parents=True, exist_ok=True)
    report_file = out / "report.json"
    report = json.loads(report_file.read_text()) if report_file.exists() else {}
    for path in glyph_files(src):
        if only and glyph_name(path.stem) not in only and path.stem not in only:
            continue
        svg, result = trace_file(project, path, overrides)
        if svg:
            (dst / f"{path.stem}.svg").write_text(svg)
        report[path.stem] = result
    report_file.write_text(json.dumps(report, indent=1))
    return report
