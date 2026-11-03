"""Vector pipeline: faithful trace -> clean vector -> stroke, fit and pixel alignment on the vector.

1. `faithful`: iso-contours of the grey draft at the ink threshold (marching
   squares). Edges sit between pixels where the anti-aliasing puts them; the
   pixel ruggedness is kept on purpose. This is the reference everything is
   measured against.
2. `vectorize`: per contour, find real corners; runs that are straight within
   `line_tol` become exact lines, the rest smooth cubic Béziers (Schneider's
   algorithm) within `curve_tol`; corners between lines are exact
   intersections; lines are snapped to 0/45/90° and made parallel only where
   the drawing still agrees.
3. `offset`: stroke correction as an exact mitred offset of the clean
   outline, re-fitted to lines and curves (the input is clean, so corners
   stay sharp).
4. `fit`: scale and move the vector into the glyph box, sized so the box is
   filled after the offset.
5. `hint`: TrueType-style grid fitting: whole axis-aligned edges move onto
   pixel lines; every other point, curve handles included, is interpolated
   between them (IUP), so nothing is pulled into a hook.

An outline is a list of rings; a ring is a list of segments, each an array of
points: 2 for a line, 4 for a cubic. Consecutive segments share end points.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from skimage.measure import find_contours

Ring = list  # list[np.ndarray] (segments)


# ---------------------------------------------------------------- faithful trace
def faithful(gray: np.ndarray, threshold: float = 128, min_area: float = 0.0) -> list[np.ndarray]:
    """Closed contours (x, y) in pixels of the grey image (0 = ink). Fill even-odd."""
    rings = []
    padded = np.pad(gray.astype(float), 1, constant_values=255)
    for c in find_contours(padded, threshold):
        if len(c) < 8:
            continue
        ring = np.stack([c[:, 1] - 0.5, c[:, 0] - 0.5], 1)  # padded index -> pixel-edge coordinates
        if np.allclose(ring[0], ring[-1]):
            ring = ring[:-1]
        if polygon_area(ring) >= min_area:
            rings.append(ring)
    return rings


def polygon_area(p: np.ndarray) -> float:
    x, y = p[:, 0], p[:, 1]
    return 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


# ---------------------------------------------------------------- geometry helpers
def resample(ring: np.ndarray, step: float) -> np.ndarray:
    closed = np.vstack([ring, ring[:1]])
    t = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(closed, axis=0), axis=1))])
    n = max(8, int(t[-1] / step))
    at = np.linspace(0, t[-1], n, endpoint=False)
    return np.stack([np.interp(at, t, closed[:, 0]), np.interp(at, t, closed[:, 1])], 1)


def _turn(pts: np.ndarray, w: int) -> np.ndarray:
    vin = pts - np.roll(pts, w, axis=0)
    vout = np.roll(pts, -w, axis=0) - pts
    return np.abs(np.degrees(np.arctan2(vin[:, 0] * vout[:, 1] - vin[:, 1] * vout[:, 0], (vin * vout).sum(1))))


def find_corners(pts: np.ndarray, w: int, min_turn: float) -> list[int]:
    n = len(pts)
    turn = _turn(pts, w)
    picked: list[int] = []
    for i in np.argsort(-turn):
        if turn[i] < min_turn:
            break
        if all(min((i - j) % n, (j - i) % n) > w for j in picked):
            picked.append(int(i))
    fine = _turn(pts, max(2, w // 3))  # refine each corner to its sharpest sample
    return sorted({max(((i + k) % n for k in range(-w, w + 1)), key=lambda j: fine[j]) for i in picked})


def fit_line(p: np.ndarray):
    c = p.mean(0)
    d = np.linalg.svd(p - c)[2][0]
    return c, d, float(np.abs((p - c) @ np.array([-d[1], d[0]])).max())


def intersect(c1, d1, c2, d2):
    cross = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(cross) < 1e-9:
        return None
    t = ((c2 - c1)[0] * d2[1] - (c2 - c1)[1] * d2[0]) / cross
    return c1 + d1 * t


def bezier(ctrl, t):
    t = np.asarray(t)[:, None]
    return (1 - t) ** 3 * ctrl[0] + 3 * (1 - t) ** 2 * t * ctrl[1] + 3 * (1 - t) * t ** 2 * ctrl[2] + t ** 3 * ctrl[3]


def _d1(ctrl, t):
    t = t[:, None]
    return 3 * (1 - t) ** 2 * (ctrl[1] - ctrl[0]) + 6 * (1 - t) * t * (ctrl[2] - ctrl[1]) + 3 * t ** 2 * (ctrl[3] - ctrl[2])


def _d2(ctrl, t):
    t = t[:, None]
    return 6 * (1 - t) * (ctrl[2] - 2 * ctrl[1] + ctrl[0]) + 6 * t * (ctrl[3] - 2 * ctrl[2] + ctrl[1])


# ---------------------------------------------------------------- Schneider curve fitting
def _chord(p):
    d = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))])
    return d / d[-1] if d[-1] > 0 else d


def _generate(p, u, t1, t2):
    A1 = (3 * (1 - u) ** 2 * u)[:, None] * t1
    A2 = (3 * (1 - u) * u ** 2)[:, None] * t2
    C = np.array([[np.sum(A1 * A1), np.sum(A1 * A2)], [np.sum(A1 * A2), np.sum(A2 * A2)]])
    base = ((1 - u) ** 3 + 3 * (1 - u) ** 2 * u)[:, None] * p[0] + (3 * (1 - u) * u ** 2 + u ** 3)[:, None] * p[-1]
    X = np.array([np.sum(A1 * (p - base)), np.sum(A2 * (p - base))])
    det = C[0, 0] * C[1, 1] - C[0, 1] * C[1, 0]
    seg = np.linalg.norm(p[-1] - p[0])
    a1 = a2 = seg / 3
    if abs(det) > 1e-12:
        a1 = (X[0] * C[1, 1] - X[1] * C[0, 1]) / det
        a2 = (C[0, 0] * X[1] - C[1, 0] * X[0]) / det
    if a1 < 1e-6 * seg or a2 < 1e-6 * seg:
        a1 = a2 = seg / 3
    return np.array([p[0], p[0] + t1 * a1, p[-1] + t2 * a2, p[-1]])


def _reparam(ctrl, p, u):
    for _ in range(2):
        q = bezier(ctrl, u) - p
        d1, d2 = _d1(ctrl, u), _d2(ctrl, u)
        den = (d1 * d1).sum(1) + (q * d2).sum(1)
        u = np.clip(u - np.where(np.abs(den) > 1e-12, (q * d1).sum(1) / np.where(np.abs(den) > 1e-12, den, 1), 0), 0, 1)
    return u


def fit_cubic(p, t1, t2, tol, depth=0) -> list[np.ndarray]:
    if len(p) <= 3:
        d = np.linalg.norm(p[-1] - p[0]) / 3
        return [np.array([p[0], p[0] + t1 * d, p[-1] + t2 * d, p[-1]])]
    u = _chord(p)
    ctrl = _generate(p, u, t1, t2)
    for _ in range(4):
        err = np.linalg.norm(bezier(ctrl, u) - p, axis=1)
        if err.max() <= tol:
            return [ctrl]
        u = _reparam(ctrl, p, u)
        ctrl = _generate(p, u, t1, t2)
    err = np.linalg.norm(bezier(ctrl, u) - p, axis=1)
    if err.max() <= tol or depth > 12 or len(p) < 7:
        return [ctrl]
    k = int(np.clip(np.argmax(err), 2, len(p) - 3))
    tc = p[k - 1] - p[k + 1]
    tc = tc / (np.linalg.norm(tc) + 1e-12)
    return fit_cubic(p[:k + 1], t1, tc, tol, depth + 1) + fit_cubic(p[k:], -tc, t2, tol, depth + 1)


def _tangent(p, k):
    t = p[min(k, len(p) - 1)] - p[0]
    return t / (np.linalg.norm(t) + 1e-12)


# ---------------------------------------------------------------- vectorize
VECTOR_DEFAULTS = {
    "step": 0.01,          # resampling step (units)
    "corner_scale": 0.12,  # corner detection window (units)
    "corner_deg": 32.0,    # smallest turn that counts as a corner (degrees)
    "line_tol": 0.03,      # a run is a line if every point is within this (units)
    "min_line": 0.25,      # shortest straight run (units)
    "curve_tol": 0.025,    # Bézier fitting tolerance (units)
    "snap_deg": 2.5,       # snap lines to multiples of 45° within this, if they still fit
    "parallel_deg": 2.0,   # make near-parallel lines parallel, if they still fit
    "max_extend": 0.5,     # furthest a line-line intersection may move a corner (units)
    "straight_min": 0.5,   # shortest straight stretch found inside a smooth curve (units)
}


@dataclass
class _Piece:
    kind: str
    q: np.ndarray
    c: np.ndarray | None = None
    d: np.ndarray | None = None


def _fits(piece: _Piece, d: np.ndarray, tol: float) -> bool:
    return float(np.abs((piece.q - piece.c) @ np.array([-d[1], d[0]])).max()) <= tol


def _snap(d: np.ndarray, deg: float) -> np.ndarray:
    a = np.degrees(np.arctan2(d[1], d[0]))
    for target in range(-180, 181, 45):
        if abs(a - target) <= deg:
            r = np.radians(target)
            return np.array([np.cos(r), np.sin(r)])
    return d


def _pieces(ring: np.ndarray, unit: float, o: dict) -> list[_Piece]:
    step = o["step"] * unit
    p = resample(ring, step)
    n = len(p)
    w = max(3, int(round(o["corner_scale"] * unit / step)))
    cs = find_corners(p, w, o["corner_deg"])
    if len(cs) < 2:  # a smooth closed curve: split at two far-apart points
        cs = sorted([0, int(np.argmax(np.linalg.norm(p - p[0], axis=1)))])
    out = []
    for a, b in zip(cs, cs[1:] + [cs[0] + n]):
        q = p[[k % n for k in range(a, b + 1)]]
        c, d, err = fit_line(q)
        if err <= o["line_tol"] * unit and np.linalg.norm(q[-1] - q[0]) > o["min_line"] * unit:
            out.append(_line_piece(q, unit, o))
        else:
            out.extend(_split_straight(q, unit, o))
    return _merge_lines(out, unit, o)


def _line_piece(q: np.ndarray, unit: float, o: dict) -> _Piece:
    c, d, _ = fit_line(q)
    d = d if (q[-1] - q[0]) @ d >= 0 else -d
    piece = _Piece("line", q, c, d)
    snapped = _snap(d, o["snap_deg"])
    if _fits(piece, snapped, o["line_tol"] * unit):
        piece.d = snapped
    return piece


def _straight(q: np.ndarray, tol: float, deg: float = 1.5) -> bool:
    """Straight within `tol`, and its two halves point the same way (an arc's halves do not)."""
    if fit_line(q)[2] > tol:
        return False
    h = len(q) // 2
    d1, d2 = fit_line(q[:h + 1])[1], fit_line(q[h:])[1]
    return np.degrees(np.arccos(min(1.0, abs(float(d1 @ d2))))) <= deg


def _split_straight(q: np.ndarray, unit: float, o: dict) -> list[_Piece]:
    """Straight stretches inside a smooth run (the sides of a rounded rectangle) become lines.

    A stretch counts when it is at least `straight_min` long, straight to half
    of `line_tol`, and its halves agree in direction, so arcs are not chopped.
    """
    tol = o["line_tol"] * unit / 2
    w = max(8, int(round(max(o["min_line"], o["straight_min"]) * unit / (o["step"] * unit))))
    n = len(q)
    if n < w + 4:
        return [_Piece("curve", q)]
    runs, i, stride = [], 0, max(1, w // 8)
    while i + w <= n:
        if _straight(q[i:i + w], tol):
            j = i + w
            while j + stride <= n and _straight(q[i:j + stride], tol):
                j += stride
            while i > (runs[-1][1] if runs else 0) and _straight(q[i - 1:j], tol):
                i -= 1
            runs.append((i, j))
            i = j
        else:
            i += stride
    if not runs:
        return [_Piece("curve", q)]
    pieces, last = [], 0
    for a, b in runs:
        if a - last >= 3:
            pieces.append(_Piece("curve", q[last:a + 1]))
        elif pieces and pieces[-1].kind == "curve":
            pass
        pieces.append(_line_piece(q[a:b], unit, o))
        last = b - 1
    if n - 1 - last >= 3:
        pieces.append(_Piece("curve", q[last:]))
    return pieces


def _merge_lines(pieces: list[_Piece], unit: float, o: dict) -> list[_Piece]:
    """Neighbouring lines that are one straight line (within `line_tol`) become one."""
    out: list[_Piece] = []
    for piece in pieces:
        if out and piece.kind == "line" and out[-1].kind == "line":
            joined = np.vstack([out[-1].q, piece.q[1:]])
            if _straight(joined, o["line_tol"] * unit, deg=2.0):
                out[-1] = _line_piece(joined, unit, o)
                continue
        out.append(piece)
    if len(out) > 2 and out[0].kind == "line" and out[-1].kind == "line":
        joined = np.vstack([out[-1].q, out[0].q[1:]])
        if _straight(joined, o["line_tol"] * unit, deg=2.0):
            out = [_line_piece(joined, unit, o)] + out[1:-1]
    return out


def _parallelize(rings: list[list[_Piece]], deg: float, tol: float) -> None:
    lines = [p for r in rings for p in r if p.kind == "line"]
    ang = lambda d: np.degrees(np.arctan2(d[1], d[0])) % 180  # noqa: E731
    diff = lambda a, b: min(abs(a - b), 180 - abs(a - b))  # noqa: E731
    done: set[int] = set()
    for i, f in enumerate(lines):
        if i in done:
            continue
        group = [j for j, g in enumerate(lines) if j not in done and diff(ang(f.d), ang(g.d)) <= deg]
        done.update(group)
        if len(group) < 2:
            continue
        axis = [j for j in group if min(ang(lines[j].d) % 45, 45 - ang(lines[j].d) % 45) < 1e-6]
        if axis:
            ref = lines[axis[0]].d
        else:
            ref = np.mean([lines[j].d if lines[j].d @ f.d >= 0 else -lines[j].d for j in group], axis=0)
            ref = ref / np.linalg.norm(ref)
        for j in group:
            cand = ref if lines[j].d @ ref >= 0 else -ref
            if _fits(lines[j], cand, tol):
                lines[j].d = cand


def _assemble(pieces: list[_Piece], unit: float, o: dict) -> Ring:
    m = len(pieces)
    joints = []
    for i in range(m):
        a, b = pieces[i], pieces[(i + 1) % m]
        j = a.q[-1]
        if a.kind == "line" and b.kind == "line":
            x = intersect(a.c, a.d, b.c, b.d)
            if x is not None and np.linalg.norm(x - j) < o["max_extend"] * unit:
                j = x
        elif a.kind == "line":
            j = a.c + a.d * ((j - a.c) @ a.d)
        elif b.kind == "line":
            j = b.c + b.d * ((j - b.c) @ b.d)
        joints.append(j)
    ring: Ring = []
    tol = o["curve_tol"] * unit
    smooth = lambda u, v: np.degrees(np.arccos(np.clip(u @ v, -1, 1))) < o["corner_deg"]  # noqa: E731
    for i, piece in enumerate(pieces):
        s, e = joints[i - 1], joints[i]
        if piece.kind == "line":
            ring.append(np.array([s, e]))
            continue
        q = piece.q.copy()
        q[0], q[-1] = s, e
        k = max(2, len(q) // 12)
        prev, nxt = pieces[i - 1], pieces[(i + 1) % m]
        t1, t2 = _tangent(q, k), _tangent(q[::-1], k)
        if prev.kind == "line" and smooth(prev.d, t1):  # flow out of an adjacent line along it
            t1 = prev.d
        if nxt.kind == "line" and smooth(-nxt.d, t2):
            t2 = -nxt.d
        ring.extend(fit_cubic(q, t1, t2, tol))
    return ring


def vectorize(contours: list[np.ndarray], unit: float = 1.0, opts: dict | None = None) -> list[Ring]:
    """Clean vector rings from contours; `unit` is the contour's pixels per grid unit."""
    o = {**VECTOR_DEFAULTS, **(opts or {})}
    pieces = [_pieces(c, unit, o) for c in contours]
    _parallelize(pieces, o["parallel_deg"], o["line_tol"] * unit)
    return [_assemble(p, unit, o) for p in pieces]


# ---------------------------------------------------------------- outline utilities
def sample(ring: Ring, step: float = 0.01) -> np.ndarray:
    pts = []
    for seg in ring:
        if len(seg) == 2:
            n = max(1, int(np.linalg.norm(seg[1] - seg[0]) / step))
            pts.append(seg[0] + (seg[1] - seg[0]) * np.linspace(0, 1, n, endpoint=False)[:, None])
        else:
            length = sum(np.linalg.norm(np.diff(seg, axis=0), axis=1))
            n = max(2, int(length / step))
            pts.append(bezier(seg, np.linspace(0, 1, n, endpoint=False)))
    return np.vstack(pts)


def bbox(rings: list[Ring], step: float = 0.02) -> tuple[float, float, float, float]:
    p = np.vstack([sample(r, step) for r in rings])
    return float(p[:, 0].min()), float(p[:, 1].min()), float(p[:, 0].max()), float(p[:, 1].max())


def transform(rings: list[Ring], scale: float = 1.0, dx: float = 0.0, dy: float = 0.0) -> list[Ring]:
    return [[seg * scale + np.array([dx, dy]) for seg in r] for r in rings]


def to_d(rings: list[Ring], decimals: int = 3) -> str:
    def num(v):
        s = f"{v:.{decimals}f}".rstrip("0").rstrip(".")
        return "0" if s in ("-0", "") else s
    out = []
    for r in rings:
        out.append(f"M{num(r[0][0][0])} {num(r[0][0][1])}")
        for seg in r:
            if len(seg) == 2:
                out.append(f"L{num(seg[1][0])} {num(seg[1][1])}")
            else:
                out.append("C" + " ".join(f"{num(x)} {num(y)}" for x, y in seg[1:]))
        out.append("Z")
    return "".join(out)


def to_svg(rings: list[Ring], grid: int, decimals: int = 3) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {grid} {grid}" fill="currentColor">'
            f'<path fill-rule="evenodd" d="{to_d(rings, decimals)}"/></svg>\n')


# ---------------------------------------------------------------- offset (stroke correction)
def _geometry(rings: list[Ring], step: float):
    from shapely.geometry import Polygon
    from shapely.validation import make_valid

    geom = None
    for r in rings:
        poly = make_valid(Polygon(sample(r, step)))
        geom = poly if geom is None else geom.symmetric_difference(poly)
    return geom


def _polygon_rings(geom) -> list[np.ndarray]:
    from shapely.geometry import Polygon

    polys = [geom] if isinstance(geom, Polygon) else [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]
    out = []
    for p in polys:
        for ring in (p.exterior, *p.interiors):
            c = np.array(ring.coords)[:-1]
            if len(c) >= 4 and polygon_area(c) > 1e-4:
                out.append(c)
    return out


EXACT = {"line_tol": 0.006, "curve_tol": 0.006, "min_line": 0.08, "corner_scale": 0.05, "snap_deg": 0.5, "parallel_deg": 0.5}


def _components(geom):
    from shapely.geometry import Polygon
    return [geom] if isinstance(geom, Polygon) else [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]


def thickest(poly) -> float:
    """Diameter of the largest circle that fits inside a shape (units)."""
    from shapely.ops import polylabel
    centre = polylabel(poly, tolerance=0.01)
    return 2 * poly.exterior.distance(centre) if not poly.interiors else 2 * poly.boundary.distance(centre)


def offset(rings: list[Ring], d: float, mitre_limit: float = 4.0, step: float = 0.005,
           stroke: float | None = None, solid: float = 1.6) -> list[Ring]:
    """Move the outline outward by `d` units (inward if negative), mitred corners, re-fitted exactly.

    Separate shapes without holes that are thicker than `solid` × `stroke`
    somewhere (a filled star, a dot) are fills, not strokes: they keep their
    drawn outline. Shapes with holes (a page outline, even one with a filled
    part) are strokes.
    """
    from shapely.ops import unary_union

    if abs(d) < 1e-4:
        return rings
    parts = []
    for comp in _components(_geometry(rings, step)):
        # A fill: a separate shape without holes that is thicker than a stroke junction can be.
        keep = stroke is not None and not comp.interiors and thickest(comp) > solid * stroke
        parts.append(comp if keep else comp.buffer(d, join_style="mitre", mitre_limit=mitre_limit))
    return vectorize(_polygon_rings(unary_union(parts)), 1.0, {**EXACT, "step": step})


# ---------------------------------------------------------------- hinting (IUP)
def _edges(rings: list[Ring], axis: int, tol: float, min_len: float, inside) -> list[dict]:
    """Axis-aligned line segments with the side their ink is on (+1: towards larger coordinates)."""
    other = 1 - axis
    found = []
    for ri, ring in enumerate(rings):
        for si, seg in enumerate(ring):
            if len(seg) != 2:
                continue
            a, b = seg
            if abs(b[axis] - a[axis]) <= tol and abs(b[other] - a[other]) >= min_len:
                pos = (a[axis] + b[axis]) / 2
                probe = (a + b) / 2
                probe = probe.copy(); probe[axis] = pos + 0.02
                found.append({"ring": ri, "seg": si, "pos": pos, "side": 1 if inside(probe) else -1,
                              "lo": min(a[other], b[other]), "hi": max(a[other], b[other])})
    return found


def hint(rings: list[Ring], snap: float = 0.3, min_len: float = 0.5, tol: float = 0.02, max_stem: float = 2.0) -> list[Ring]:
    """Grid-fit like a TrueType hinter.

    Axis-aligned edges move onto pixel lines as whole edges; the two edges of a
    stem (facing edges up to `max_stem` apart that overlap) move together by the
    same amount, so stem widths never change; every other point, curve handles
    included, is interpolated between the moved points around it (IUP).
    """
    from shapely.geometry import Point

    geom = _geometry(rings, 0.01)
    inside = lambda p: geom.contains(Point(float(p[0]), float(p[1])))  # noqa: E731
    flat, starts = [], []
    for ring in rings:
        pts, st, k = [], [], 0
        for seg in ring:
            st.append(k)
            pts.extend(seg[:-1])
            k += len(seg) - 1
        flat.append(np.array(pts, dtype=float))
        starts.append(st)
    for axis in (0, 1):
        edges = _edges(rings, axis, tol, min_len, inside)
        shift: dict[int, float] = {}
        paired: set[int] = set()
        for i, e in enumerate(edges):  # a stem: ink after this edge, a facing edge closing it
            if e["side"] < 0 or i in paired:
                continue
            best = None
            for j, f in enumerate(edges):
                if j in paired or j == i or f["side"] > 0 or f["pos"] <= e["pos"]:
                    continue
                if min(e["hi"], f["hi"]) - max(e["lo"], f["lo"]) <= 0:
                    continue
                w = f["pos"] - e["pos"]
                if w <= max_stem and (best is None or w < best[0]):
                    best = (w, j)
            if best:
                j = best[1]
                sh = min((round(e["pos"]) - e["pos"], round(edges[j]["pos"]) - edges[j]["pos"]), key=abs)
                if abs(sh) <= snap:
                    shift[i] = shift[j] = sh
                paired |= {i, j}
        for i, e in enumerate(edges):
            if i not in paired and abs(round(e["pos"]) - e["pos"]) <= snap:
                shift[i] = round(e["pos"]) - e["pos"]
        for ri, pts in enumerate(flat):
            n, st = len(pts), starts[ri]
            touched = {}
            for i, e in enumerate(edges):
                if e["ring"] == ri and i in shift:
                    for k in (st[e["seg"]], st[(e["seg"] + 1) % len(st)]):
                        touched[k] = e["pos"] + shift[i]
            if not touched:
                continue
            orig = pts[:, axis].copy()
            for k, v in touched.items():
                pts[k, axis] = v
            ks = sorted(touched)
            for idx, k1 in enumerate(ks):
                k2 = ks[(idx + 1) % len(ks)]
                o1, o2, n1, n2 = orig[k1], orig[k2], touched[k1], touched[k2]
                k = (k1 + 1) % n
                while k != k2:
                    o, lo, hi = orig[k], min(o1, o2), max(o1, o2)
                    if hi - lo < 1e-9:
                        pts[k, axis] = o + (n1 - o1)
                    elif o <= lo:
                        pts[k, axis] = o + ((n1 - o1) if o1 <= o2 else (n2 - o2))
                    elif o >= hi:
                        pts[k, axis] = o + ((n1 - o1) if o1 >= o2 else (n2 - o2))
                    else:
                        pts[k, axis] = n1 + (o - o1) / (o2 - o1) * (n2 - n1)
                    k = (k + 1) % n
    out = []
    for ri, ring in enumerate(rings):
        pts, st, n = flat[ri], starts[ri], len(flat[ri])
        out.append([np.array([pts[(st[si] + j) % n] for j in range(len(seg) - 1)] + [pts[st[(si + 1) % len(st)]]])
                    for si, seg in enumerate(ring)])
    return out
