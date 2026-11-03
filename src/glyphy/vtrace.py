"""`trace.method = "vector"`: draft -> faithful trace -> clean vector -> stroke -> box -> pixels.

Every step after the faithful trace works on exact lines and curves, never on
pixels, and the report says how close each stage stayed to the one before:
`vector_match` (clean vector vs faithful trace, at the draft's resolution) and
`hint_match` (pixel-aligned vs unaligned glyph, at 64 px per unit).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

from . import vector as V
from .config import Project
from .metrics import crispness, measure, measure_svg, roughness
from .raster import RASTER_SUFFIXES, render_svg
from .trace import box_for, check, glyph_name, stroke_target

MATCH_TOL = 0.03  # units: outlines closer than this count as matching


def _render_d(d: str, size: int, view: tuple[float, float, float]) -> np.ndarray:
    x, y, span = view
    return render_svg(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x} {y} {span} {span}">'
                      f'<path fill-rule="evenodd" d="{d}"/></svg>', size)


def _edge(m: np.ndarray) -> np.ndarray:
    return m ^ ndimage.binary_erosion(m)


def outline_match(a: np.ndarray, b: np.ndarray, tol_px: float) -> tuple[float, float]:
    """F-score of outlines within `tol_px` of each other, and the furthest a's outline strays (px)."""
    ea, eb = _edge(a), _edge(b)
    if not ea.any() or not eb.any():
        return 0.0, float("inf")
    da, db = ndimage.distance_transform_edt(~ea), ndimage.distance_transform_edt(~eb)
    pa, pb = (db[ea] <= tol_px).mean(), (da[eb] <= tol_px).mean()
    return float(2 * pa * pb / (pa + pb)) if pa + pb else 0.0, float(db[ea].max())


def _draft_gray(path: Path, grid: int) -> np.ndarray:
    if path.suffix.lower() in RASTER_SUFFIXES:
        return np.array(Image.open(path).convert("L"), dtype=float)
    return render_svg(path, grid * 128, gray=True).astype(float)


def _vector_opts(cfg: dict) -> dict:
    return {k: float(cfg[k]) for k in V.VECTOR_DEFAULTS if k in cfg}


def stages(project: Project, path: Path, overrides: dict | None = None) -> dict | None:
    """Stages 1-2 (faithful trace, clean vector) in the draft's pixel frame; None if the draft has no ink."""
    name = glyph_name(path.stem)
    cfg = {**project.settings(name), **(overrides or {})}
    cfg.setdefault("kind", "icon")
    gray = _draft_gray(path, project.grid)
    ink = gray < float(cfg["threshold"])
    if not ink.any():
        return None
    box = box_for(cfg)
    ys, xs = np.nonzero(ink)
    unit = max((xs.max() - xs.min() + 1) / box[0], (ys.max() - ys.min() + 1) / box[1])  # draft px per final unit
    contours = V.faithful(gray, float(cfg["threshold"]), min_area=float(cfg["speck"]) * unit ** 2)
    clean = V.vectorize(contours, unit, _vector_opts(cfg))
    faithful_d = "".join("M" + "L".join(f"{x:.2f} {y:.2f}" for x, y in c) + "Z" for c in contours)
    return {"name": name, "cfg": cfg, "gray": gray, "box": box, "unit": unit, "contours": contours, "clean": clean, "faithful_d": faithful_d}


def trace_vector(project: Project, path: Path, overrides: dict | None = None) -> tuple[str, dict]:
    st = stages(project, path, overrides)
    if st is None:
        return "", {"glyph": glyph_name(path.stem), "ok": False, "error": "no ink found"}
    name, cfg, gray, box, unit, clean = st["name"], st["cfg"], st["gray"], st["box"], st["unit"], st["clean"]
    grid = project.grid

    # 1-2. faithful trace and clean vector, compared at the draft's resolution
    n = gray.shape[0]
    view = (0.0, 0.0, float(n))
    vector_match, vector_worst = outline_match(_render_d(V.to_d(clean, 2), n, view), _render_d(st["faithful_d"], n, view), MATCH_TOL * unit)

    # 3. into grid units, sized so the box is filled once the stroke is corrected
    cb = V.bbox(clean, 0.5)  # draft pixels
    x0, y0, x1, y1 = cb
    s0 = min(box[0] / (x1 - x0), box[1] / (y1 - y0))
    rings = V.transform(clean, s0, grid / 2 - (x0 + x1) / 2 * s0, grid / 2 - (y0 + y1) / 2 * s0)
    work = int(cfg["work_scale"])
    m = measure(render_svg(V.to_svg(rings, grid), grid * work), work, grid)
    raw = m.stroke
    target = stroke_target(cfg, raw)
    if cfg["correct"]:
        b = box[0] if (box[0] - m.width) <= (box[1] - m.height) else box[1]
        f = (b - target) / max(b - raw, 1e-6) if cfg["fit"] else 1.0
        rings = V.transform(rings, f, grid / 2 * (1 - f), grid / 2 * (1 - f))
        mitre = float(cfg["vector_mitre_limit"])
        base = rings
        d = (target - raw * f) / 2
        rings = V.offset(base, d, mitre, stroke=raw * f)
        for _ in range(2):  # measurement and offset agree to a few hundredths; close the gap from the base
            got = measure(render_svg(V.to_svg(rings, grid), grid * work), work, grid).stroke
            if abs(got - target) <= float(cfg["stroke_epsilon"]) / 2:
                break
            d += (target - got) / 2
            rings = V.offset(base, d, mitre, stroke=raw * f)
    else:
        f, d = 1.0, 0.0
    x0, y0, x1, y1 = V.bbox(rings)
    # Offsetting sharp corners can overshoot the box by a few hundredths: scale back (stroke changes < 1%).
    k = min(1.0, box[0] / (x1 - x0), box[1] / (y1 - y0)) if cfg["fit"] else 1.0
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rings = V.transform(rings, k, grid / 2 - cx * k, grid / 2 - cy * k)
    # draft px -> glyph units, composed from every transform above (offsets are about the same centre)
    S = s0 * f * k
    T0 = np.array([grid / 2 - (cb[0] + cb[2]) / 2 * s0, grid / 2 - (cb[1] + cb[3]) / 2 * s0])
    T1 = T0 * f + grid / 2 * (1 - f)
    T2 = T1 * k + np.array([grid / 2 - cx * k, grid / 2 - cy * k])

    # 4. pixel alignment: a whole-glyph shift first (no distortion), then optional edge hinting
    steps = max(1, int(cfg["offsets"]))
    shifts = sorted({round(k / steps - 0.5, 4) for k in range(steps)} | {0.0}, key=abs)
    best = None
    for dy in shifts:
        for dx in shifts:
            cand = V.transform(rings, 1.0, dx, dy)
            svg = V.to_svg(cand, grid, int(cfg["decimals"]))
            mm = measure_svg(svg, grid)
            if mm is None:
                continue
            ok = check(mm, cfg, target)["ok"]
            score = (ok, round(crispness(svg, grid) + float(cfg["weight_crisp_2x"]) * crispness(svg, grid, 2), 3))
            if best is None or score > best[0]:
                best = (score, cand, (dx, dy))
    _, rings, (dx, dy) = best
    hint_match = 1.0
    if cfg["hint"]:
        hinted = V.hint(rings, float(cfg["snap"]), float(cfg["hint_min_len"]))
        scale = 64
        full = (0.0, 0.0, float(grid))
        hint_match, _ = outline_match(_render_d(V.to_d(hinted), grid * scale, full), _render_d(V.to_d(rings), grid * scale, full), MATCH_TOL * scale)
        rings = hinted

    svg = V.to_svg(rings, grid, int(cfg["decimals"]))
    mm = measure_svg(svg, grid)
    result = {**check(mm, cfg, target, roughness(svg, grid)),
              "crisp": round(crispness(svg, grid), 2), "crisp_2x": round(crispness(svg, grid, 2), 2),
              "vector_match": round(vector_match, 4), "vector_worst": round(vector_worst / unit, 3),
              "hint_match": round(hint_match, 4), "offset": [dx, dy],
              "draft_transform": [S, float(T2[0] + dx), float(T2[1] + dy)], "stroke_offset": round(d * k, 4),
              "segments": sum(len(r) for r in rings)}
    return svg, {"glyph": name, "raw_stroke": round(raw, 3), **result, "bytes": len(svg)}
