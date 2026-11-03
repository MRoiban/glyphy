"""Draft image → style-conformant SVG, verified by measurement.

The defaults reproduce the pipeline that made Typewriter's glyphs. Per draft
(every number comes from `Project.settings(glyph)`, so any step can be tuned
globally in [trace]/[style] or for one glyph in [glyphs.<name>]):

1. Ink mask at the draft's own resolution (`threshold`, `speck` in units²).
2. Fit into the target box (`fit`; icons: live × live, letterforms: a
   letter_height square, both in whole units; a glyph may set `box = [w, h]`).
3. Correct the stroke from measurement (`correct`, `rounds`, `stroke_epsilon`,
   `stroke_shape`); letterforms aim at the references' letter stroke, and a
   glyph may force `stroke_target`.
4. Optionally iron out draft noise (`smooth`, off by default).
5. Trace with potrace (`turdsize`, `alphamax`, `opticurve`, `opttolerance`),
   move straight corners onto whole pixels (`snap`, `snap_mode`), try
   sub-pixel offsets and keep the crispest result that passes (`offsets`).
6. Re-render and measure with the same code as the references.

SVG drafts drawn on the grid can be taken as drawn instead (`svg_as_drawn`):
only steps 5 and 6 apply, without the offset search.

The functions are public so they can be composed differently from Python.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

from .config import Project
from .fidelity import Centreline, drift, render as render_fidelity, stroke_spread
from .metrics import Metrics, crispness, measure, measure_svg, roughness
from .raster import RASTER_SUFFIXES, glyph_files, render_svg


def glyph_name(stem: str) -> str:
    """`heading-2` → `heading`; a stem without a numeric suffix is its own name."""
    head, _, tail = stem.rpartition("-")
    return head if head and tail.isdigit() else stem


def box_for(cfg: dict) -> tuple[float, float]:
    if "box" in cfg:
        return float(cfg["box"][0]), float(cfg["box"][1])
    if cfg.get("kind") == "letter":
        # Letterforms sit in a square as tall as the references' letters, in whole units
        # so their edges can meet pixel lines.
        side = float(max(1, round(float(cfg["letter_height"]))))
        return side, side
    return float(cfg["live"]), float(cfg["live"])


def stroke_target(cfg: dict, measured: float) -> float:
    if "stroke_target" in cfg:
        return float(cfg["stroke_target"])
    if cfg.get("kind") == "letter":
        return float(cfg["letter_stroke_target"])
    return float(cfg["stroke"])


def ink_mask(path: Path, cfg: dict, grid: int) -> np.ndarray:
    """Ink at the draft's own resolution; `fit` resamples it once, from the full detail."""
    size = grid * int(cfg["work_scale"])
    if path.suffix.lower() not in RASTER_SUFFIXES:
        return render_svg(path, size)
    pixels = np.array(Image.open(path).convert("L"), dtype=float)
    mask = pixels < float(cfg["threshold"])
    labels, count = ndimage.label(mask)
    if count:
        sizes = ndimage.sum(mask, labels, range(1, count + 1))
        unit_px = pixels.shape[0] / grid
        mask = np.isin(labels, np.nonzero(sizes >= float(cfg["speck"]) * unit_px ** 2)[0] + 1)
    if not cfg["fit"] and mask.shape != (size, size):
        mask = np.array(Image.fromarray((mask * 255).astype("uint8")).resize((size, size), Image.LANCZOS)) > 127
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


def adjust_stroke(mask: np.ndarray, grid: int, work: int, target: float, shape: str = "cross") -> np.ndarray:
    """Grow or shrink the ink by half the stroke error.

    "cross" (default) repeats a 3×3 cross erosion/dilation; "round" uses exact
    Euclidean distance, which rounds outer corners when growing.
    """
    radius = (target - measure(mask, work, grid).stroke) / 2 * work
    if not np.isfinite(radius) or abs(radius) < 1:
        return mask
    if shape == "round":
        if radius > 0:
            return ndimage.distance_transform_edt(~mask) <= radius
        return ndimage.distance_transform_edt(mask) > -radius
    op = ndimage.binary_dilation if radius > 0 else ndimage.binary_erosion
    return op(mask, ndimage.generate_binary_structure(2, 1), iterations=int(round(abs(radius))))


def smooth(mask: np.ndarray, radius: float, work: int) -> np.ndarray:
    """Blur and re-threshold: removes wobble narrower than `radius` units, keeps edges in place."""
    if radius <= 0:
        return mask
    return ndimage.gaussian_filter(mask.astype(float), radius * work) > 0.5


def normalise(mask: np.ndarray, cfg: dict, grid: int) -> tuple[np.ndarray, float, float]:
    """Fit and correct until stroke and box both hold. Returns (mask, raw stroke, target)."""
    work, box = int(cfg["work_scale"]), box_for(cfg)
    current = fit(mask, grid, work, *box) if cfg["fit"] else mask
    m = measure(current, work, grid)
    raw = m.stroke
    target = stroke_target(cfg, raw)
    if not cfg["correct"]:
        return current, raw, target
    if cfg["stroke_shape"] == "mitre":
        from .outline import exact_fit_box, offset_to_stroke
        if cfg["fit"]:
            current = fit(mask, grid, work, *exact_fit_box(raw, box, (m.width, m.height), target))
        return offset_to_stroke(current, cfg, grid, target), raw, target
    for _ in range(int(cfg["rounds"])):
        current = adjust_stroke(current, grid, work, target, str(cfg["stroke_shape"]))
        m = measure(current, work, grid)
        if cfg["fit"] and max(m.width - box[0], m.height - box[1]) > 0.05:
            current = fit(current, grid, work, *box)
            m = measure(current, work, grid)
        if abs(m.stroke - target) <= float(cfg["stroke_epsilon"]):
            break
    return current, raw, target


def _corner_snapped_path(curve, k: float, snap: float, num) -> list[str]:
    """Snap every straight corner near a whole pixel onto it; curve ends stay put."""
    def snapped(v: float) -> float:
        nearest = round(v)
        return float(nearest) if abs(v - nearest) <= snap else v

    start = (curve.start_point.x * k, curve.start_point.y * k)
    sx, sy = snapped(start[0]), snapped(start[1])
    prev_shift = (sx - start[0], sy - start[1])
    parts = [f"M{num(sx)} {num(sy)}"]
    for seg in curve.segments:
        end = (seg.end_point.x * k, seg.end_point.y * k)
        # Snapping curve endpoints makes round shapes lumpy; only straight runs snap.
        ex, ey = (snapped(end[0]), snapped(end[1])) if seg.is_corner else end
        shift = (ex - end[0], ey - end[1])
        if seg.is_corner:
            parts.append(f"L{num(snapped(seg.c.x * k))} {num(snapped(seg.c.y * k))}L{num(ex)} {num(ey)}")
        else:
            # Handles move with the endpoint they belong to, so snapped curves keep their tangents.
            c1 = (seg.c1.x * k + prev_shift[0], seg.c1.y * k + prev_shift[1])
            c2 = (seg.c2.x * k + shift[0], seg.c2.y * k + shift[1])
            parts.append(f"C{num(c1[0])} {num(c1[1])} {num(c2[0])} {num(c2[1])} {num(ex)} {num(ey)}")
        prev_shift = shift
    parts.append("Z")
    return parts


def to_svg(mask: np.ndarray, cfg: dict, grid: int) -> str:
    """Trace a mask at `work_scale` px per unit into a filled-path SVG on the grid.

    `snap_mode = "corners"` (default) snaps straight corners near whole pixels.
    `"edges"` first makes near-horizontal/vertical edges exact (`straighten`
    degrees), then moves only those edges onto pixel lines.
    """
    import potrace

    work, decimals = int(cfg["work_scale"]), int(cfg["decimals"])
    snap, slope = float(cfg["snap"]), np.tan(np.radians(float(cfg["straighten"])))

    def num(v: float) -> str:
        return f"{v:.{decimals}f}".rstrip("0").rstrip(".") if decimals else str(round(v))

    # potracer treats dark (low) values as ink, like a scanned page.
    paths = potrace.Bitmap(~mask).trace(turdsize=int(cfg["turdsize"]), alphamax=float(cfg["alphamax"]),
                                        opticurve=bool(cfg["opticurve"]), opttolerance=float(cfg["opttolerance"]))
    k = 1 / work
    parts = []
    for curve in paths:
        if cfg["snap_mode"] != "edges":
            parts += _corner_snapped_path(curve, k, snap, num)
            continue
        # Nodes of the closed outline; the last segment ends where the outline starts.
        pts = [[curve.start_point.x * k, curve.start_point.y * k]]
        ops = []  # ("L", i) or ("C", c1, c2, i): from the previous node to node i
        for seg in curve.segments:
            if seg.is_corner:
                pts.append([seg.c.x * k, seg.c.y * k])
                ops.append(("L", len(pts) - 1))
            end = len(pts)
            pts.append([seg.end_point.x * k, seg.end_point.y * k])
            ops.append(("L", end) if seg.is_corner else
                       ("C", (seg.c1.x * k, seg.c1.y * k), (seg.c2.x * k, seg.c2.y * k), end))
        last = len(pts) - 1
        idx = lambda i: 0 if i == last else i  # noqa: E731
        pts = np.array(pts[:-1])
        original = pts.copy()
        vertical, horizontal = np.zeros(len(pts), bool), np.zeros(len(pts), bool)
        prev = 0
        # Straighten near-axis lines, then move only those edges onto pixel lines, so a
        # corner potrace finds inside a curve is never pulled sideways into a tooth.
        for op in ops:
            i = idx(op[-1])
            if op[0] == "L" and i != prev:
                dx, dy = pts[i] - pts[prev]
                if abs(dx) <= slope * abs(dy):
                    pts[[prev, i], 0] = pts[[prev, i], 0].mean()
                    vertical[[prev, i]] = True
                elif abs(dy) <= slope * abs(dx):
                    pts[[prev, i], 1] = pts[[prev, i], 1].mean()
                    horizontal[[prev, i]] = True
            prev = i
        for axis, flags in ((0, vertical), (1, horizontal)):
            near = np.round(pts[:, axis])
            move = flags & (np.abs(pts[:, axis] - near) <= snap)
            pts[move, axis] = near[move]
        shift = pts - original
        parts.append(f"M{num(pts[0][0])} {num(pts[0][1])}")
        prev = 0
        for op in ops:
            i = idx(op[-1])
            if op[0] == "L":
                parts.append(f"L{num(pts[i][0])} {num(pts[i][1])}")
            else:
                # Control points travel with their end nodes so curves keep their shape.
                c1 = (op[1][0] + shift[prev][0], op[1][1] + shift[prev][1])
                c2 = (op[2][0] + shift[i][0], op[2][1] + shift[i][1])
                parts.append(f"C{num(c1[0])} {num(c1[1])} {num(c2[0])} {num(c2[1])} {num(pts[i][0])} {num(pts[i][1])}")
            prev = i
        parts.append("Z")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {grid} {grid}" fill="currentColor">'
            f'<path fill-rule="evenodd" d="{"".join(parts)}"/></svg>\n')


def check(m: Metrics, cfg: dict, target: float, rough: float | None = None) -> dict:
    if cfg.get("kind") == "letter" and "stroke_target" not in cfg:
        low, high = cfg["letter_stroke"]
        stroke_ok = low <= m.stroke <= high
    else:
        stroke_ok = abs(m.stroke - target) <= float(cfg["stroke_tolerance"])
    # The fitting box is a target; the rule is the live area (or a larger custom box).
    box = box_for(cfg)
    limit = (max(box[0], float(cfg["live"])), max(box[1], float(cfg["live"])))
    result = {
        "kind": cfg.get("kind", "icon"), "stroke": round(m.stroke, 3), "stroke_target": round(target, 3), "stroke_ok": bool(stroke_ok),
        "box": [round(m.width, 2), round(m.height, 2)], "box_ok": bool(max(m.width - limit[0], m.height - limit[1]) <= 0.05),
        "min_pad": round(m.min_pad, 2), "pad_ok": bool(m.min_pad >= float(cfg["pad_min"]) - 0.01),
        "centring": round(m.centring, 2), "centring_ok": bool(m.centring <= float(cfg["centring_max"])),
    }
    keys = ["stroke_ok", "box_ok", "pad_ok", "centring_ok"]
    if rough is not None:
        result["roughness"] = round(rough, 3)
        if float(cfg["roughness_max"]) > 0:
            result["roughness_ok"] = bool(rough <= float(cfg["roughness_max"]))
            keys.append("roughness_ok")
    result["ok"] = all(result[k] for k in keys)
    return result


def check_svg(project: Project, svg, kind: str | None = None, overrides: dict | None = None) -> dict:
    """Check a finished SVG (hand-drawn or traced) against the style."""
    name = glyph_name(Path(svg).stem) if isinstance(svg, Path) else None
    cfg = {**project.settings(name), **({"kind": kind} if kind else {}), **(overrides or {})}
    cfg.setdefault("kind", "icon")
    m = measure_svg(svg, project.grid)
    if m is None:
        return {"ok": False, "error": "no ink"}
    return {**check(m, cfg, stroke_target(cfg, m.stroke), roughness(svg, project.grid)), **_crisp(svg, project.grid)}


def _crisp(svg, grid: int) -> dict:
    # At 2× (high-density screens) a glyph that is only crisp at 1× shows its true edges.
    return {"crisp": round(crispness(svg, grid), 2), "crisp_2x": round(crispness(svg, grid, 2), 2)}


def offset_shifts(work: int, offsets: int) -> list[int]:
    """Pixel shifts tried per axis: no shift first, then steps of 1/offsets unit
    around it (4 → 0, -0.25, +0.25 units; 8 → 0, -0.375 … +0.375)."""
    step = max(1, work // max(1, offsets))
    shifts = [d - work // 2 if d else 0 for d in range(0, work, step)]
    return list(dict.fromkeys(shifts))


def trace_file(project: Project, path: Path, overrides: dict | None = None) -> tuple[str, dict]:
    name = glyph_name(path.stem)
    cfg = {**project.settings(name), **(overrides or {})}
    cfg.setdefault("kind", "icon")
    grid, work = project.grid, int(cfg["work_scale"])
    mask = ink_mask(path, cfg, grid)
    if not mask.any():
        return "", {"glyph": name, "ok": False, "error": "no ink found"}
    as_drawn = path.suffix.lower() not in RASTER_SUFFIXES and bool(cfg["svg_as_drawn"])
    if as_drawn:
        normal, raw = mask, measure(mask, work, grid).stroke
        target = stroke_target(cfg, raw)
    else:
        normal, raw, target = normalise(mask, cfg, grid)
        normal = smooth(normal, float(cfg["smooth"]), work)
    offsets = 1 if as_drawn else max(1, int(cfg["offsets"]))
    shifts = offset_shifts(work, offsets)
    centreline = Centreline.of(fit(mask, grid, 32, *box_for(cfg)))
    balanced = cfg["choose"] == "balanced" and not as_drawn
    snap = float(cfg["snap"])
    # "balanced" also searches snap strength and mode, since snapping trades crispness for faithfulness.
    variants = ([("corners", 0.0)] + [(mode, s) for mode in ("corners", "edges") for s in sorted({snap / 2, snap}) if s > 0]
                if balanced else [(cfg["snap_mode"], snap)])
    best = None
    for mode, s in variants:
        c = {**cfg, "snap_mode": mode, "snap": s}
        for dy in shifts:
            for dx in shifts:
                svg = to_svg(np.roll(normal, (dy, dx), axis=(0, 1)), c, grid)
                m = measure_svg(svg, grid)
                if m is None:
                    continue
                result = check(m, c, target)
                crisp = crispness(svg, grid)
                if balanced:
                    value = choice_value(svg, grid, c, centreline, crisp)
                else:
                    # Prefer crisp edges, but not at any cost in centring. Crispness is compared
                    # at two decimals, so near-ties go to the first (least shifted) offset.
                    value = round(crisp, 2) - float(cfg["centring_weight"]) * result["centring"]
                score = (result["ok"], value)
                if best is None or score > best[0]:
                    best = (score, svg, m, c, (dy, dx))
    if best is None:
        return "", {"glyph": name, "ok": False, "error": "tracing produced no ink"}
    _, svg, m, c, (dy, dx) = best
    rendered = render_fidelity(svg, grid)
    mean_drift, drift95 = drift(centreline, rendered)
    result = {**check(m, c, target, roughness(svg, grid)), **_crisp(svg, grid),
              "drift": round(drift95, 3), "drift_mean": round(mean_drift, 3), "stroke_spread": round(stroke_spread(rendered), 3),
              "snap": c["snap"], "snap_mode": c["snap_mode"], "offset": [round(dx / work, 3), round(dy / work, 3)]}
    return svg, {"glyph": name, "raw_stroke": round(raw, 3), **result, "bytes": len(svg)}


def choice_value(svg: str, grid: int, cfg: dict, centreline: Centreline, crisp: float | None = None) -> float:
    """The "balanced" score: crispness at 1× and 2×, minus drift from the draft, uneven
    strokes and wobble beyond the roughest reference. Weights are `weight_*` settings."""
    rendered = render_fidelity(svg, grid)
    crisp = crispness(svg, grid) if crisp is None else crisp
    excess = max(0.0, roughness(svg, grid) - float(cfg["roughness_reference"]))
    return (crisp + float(cfg["weight_crisp_2x"]) * crispness(svg, grid, 2)
            - float(cfg["weight_drift"]) * drift(centreline, rendered)[1]
            - float(cfg["weight_spread"]) * stroke_spread(rendered)
            - float(cfg["weight_rough"]) * excess)


def _trace_one(job):
    project, path, overrides = job
    return path, *trace_file(project, path, overrides)


def trace_all(project: Project, only: list[str] | None = None, overrides: dict | None = None,
              jobs: int | None = None) -> dict:
    """Trace every draft (or `only` these glyphs/stems), `jobs` drafts at a time (default: all CPU cores)."""
    import os
    from concurrent.futures import ProcessPoolExecutor

    src, dst = project.path("generated"), project.path("traced")
    dst.mkdir(parents=True, exist_ok=True)
    out = project.path("out")
    out.mkdir(parents=True, exist_ok=True)
    report_file = out / "report.json"
    report = json.loads(report_file.read_text()) if report_file.exists() else {}
    paths = [p for p in glyph_files(src) if not only or glyph_name(p.stem) in only or p.stem in only]
    work = [(project, p, overrides) for p in paths]
    jobs = max(1, min(jobs or os.cpu_count() or 1, len(work)))
    if jobs == 1:
        results = map(_trace_one, work)
    else:
        pool = ProcessPoolExecutor(jobs)
        results = pool.map(_trace_one, work)
    for path, svg, result in results:
        if svg:
            (dst / f"{path.stem}.svg").write_text(svg)
        report[path.stem] = result
    if jobs > 1:
        pool.shutdown()
    report_file.write_text(json.dumps(report, indent=1))
    return report
