"""Stroke correction on the outline instead of the pixels (`stroke_shape = "mitre"`).

Growing or shrinking pixels changes axis strokes and diagonals by different
amounts and rounds or bevels corners. Offsetting the traced outline by half the
stroke error with mitred joins changes every direction equally and keeps
corners sharp. The glyph is fitted once, at the size where the corrected
outline fills the box exactly, so no refit rescales it afterwards.
"""
from __future__ import annotations

import numpy as np

from .metrics import measure
from .raster import render_svg


def to_geometry(mask: np.ndarray, cfg: dict):
    """Trace without snapping and flatten to a shapely geometry in grid units (even-odd fill)."""
    import potrace
    from shapely.geometry import Polygon
    from shapely.validation import make_valid

    k = 1 / int(cfg["work_scale"])
    paths = potrace.Bitmap(~mask).trace(turdsize=int(cfg["turdsize"]), alphamax=float(cfg["alphamax"]),
                                        opticurve=bool(cfg["opticurve"]), opttolerance=float(cfg["opttolerance"]))
    geometry = None
    steps = np.linspace(0, 1, 17)[1:, None]
    for curve in paths:
        points = [(curve.start_point.x * k, curve.start_point.y * k)]
        for seg in curve.segments:
            if seg.is_corner:
                points += [(seg.c.x * k, seg.c.y * k), (seg.end_point.x * k, seg.end_point.y * k)]
            else:
                p0 = np.array(points[-1])
                c1, c2, p3 = (np.array([p.x, p.y]) * k for p in (seg.c1, seg.c2, seg.end_point))
                t = steps
                curve_points = (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * c1 + 3 * (1 - t) * t ** 2 * c2 + t ** 3 * p3
                points += [tuple(p) for p in curve_points]
        ring = make_valid(Polygon(points))
        geometry = ring if geometry is None else geometry.symmetric_difference(ring)
    return geometry


def to_svg_text(geometry, grid: int) -> str:
    from shapely.geometry import Polygon

    polygons = [geometry] if isinstance(geometry, Polygon) else [g for g in getattr(geometry, "geoms", []) if isinstance(g, Polygon)]
    d = "".join("M" + "L".join(f"{x:.4f} {y:.4f}" for x, y in ring.coords) + "Z"
                for p in polygons for ring in (p.exterior, *p.interiors))
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {grid} {grid}"><path fill-rule="evenodd" d="{d}"/></svg>'


def exact_fit_box(fitted_stroke: float, box: tuple[float, float], measured_box: tuple[float, float], target: float):
    """The box to fit the draft into so that, after the stroke becomes `target`, it fills `box`.

    Offsetting by r grows every extent by 2r = target - stroke × f, so for the
    dimension that touches the box: b·f + target - s·f = b, f = (b - target)/(b - s).
    """
    (bw, bh), (w, h) = box, measured_box
    b = bw if (bw - w) <= (bh - h) else bh
    f = (b - target) / max(b - fitted_stroke, 1e-6)
    return bw * f, bh * f


def offset_to_stroke(mask: np.ndarray, cfg: dict, grid: int, target: float, rounds: int = 3) -> np.ndarray:
    """Offset the outline (mitred) until the measured stroke reaches `target`."""
    work = int(cfg["work_scale"])
    geometry = to_geometry(mask, cfg)
    result = mask
    for _ in range(rounds):
        stroke = measure(result, work, grid).stroke
        r = (target - stroke) / 2
        if abs(r) * work < 0.5:
            break
        geometry = geometry.buffer(r, join_style="mitre", mitre_limit=float(cfg["mitre_limit"]))
        result = render_svg(to_svg_text(geometry, grid), grid * work)
    return result
