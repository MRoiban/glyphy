"""`glyphy inspect`: full-resolution evidence for one traced draft.

Small renders hide exactly the defects that matter in a vector, so this draws
everything at the draft's own resolution:

1. faithful trace (grey) vs clean vector (green; red where they are further
   apart than 0.03 units), with the three worst spots enlarged;
2. the final glyph mapped back onto the draft (with the pipeline's own
   transform): green where its outline sits between the draft's edge and the
   intended stroke offset, red elsewhere;
3. the final glyph large and at 16 / 32 px.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

from . import vector as V
from .config import Project
from .raster import render_svg
from .vtrace import MATCH_TOL, _render_d, stages


def _edge(m):
    return m ^ ndimage.binary_erosion(m)


def _paint(base_ink, outline, bad, box, k=1):
    x0, y0, x1, y1 = box
    rgb = np.full((y1 - y0, x1 - x0, 3), 255, np.uint8)
    cut = lambda a: a[y0:y1, x0:x1]  # noqa: E731
    rgb[cut(base_ink)] = (214, 216, 222)
    rgb[cut(_edge(base_ink))] = (120, 122, 132)
    rgb[cut(outline)] = (25, 150, 75)
    rgb[cut(bad)] = (225, 35, 45)
    img = Image.fromarray(rgb)
    return img.resize((img.width * k, img.height * k), Image.NEAREST) if k > 1 else img


def _panel(title, base, outline, bad, err, size=520, crop=72, k=3):
    ys, xs = np.nonzero(base | outline)
    pad = 24
    box = (max(0, xs.min() - pad), max(0, ys.min() - pad), min(base.shape[1], xs.max() + pad), min(base.shape[0], ys.max() + pad))
    full = _paint(base, outline, bad, box)
    full.thumbnail((size, size))
    img = Image.new("RGB", (size + 3 * (crop * k + 10) + 20, size + 30), "white")
    ImageDraw.Draw(img).text((10, 8), title, fill=(0, 0, 0))
    img.paste(full, (10, 26))
    e = np.where(bad, err, 0.0)
    for j in range(3):
        if e.max() <= 0:
            break
        yy, xx = np.unravel_index(np.argmax(e), e.shape)
        b = (max(0, xx - crop // 2), max(0, yy - crop // 2), min(base.shape[1], xx + crop // 2), min(base.shape[0], yy + crop // 2))
        img.paste(_paint(base, outline, bad, b, k), (size + 20 + j * (crop * k + 10), 26))
        e[max(0, yy - crop):yy + crop, max(0, xx - crop):xx + crop] = 0
    return img


def inspect(project: Project, stem: str) -> Path:
    path = next((p for p in project.path("generated").iterdir() if p.stem == stem), None)
    if path is None:
        raise SystemExit(f"No draft named {stem} in {project.path('generated')}.")
    st = stages(project, path)
    if st is None:
        raise SystemExit(f"{path} has no ink.")
    n, unit = st["gray"].shape[0], st["unit"]
    view = (0.0, 0.0, float(n))
    faithful = _render_d(st["faithful_d"], n, view)
    clean = _render_d(V.to_d(st["clean"], 2), n, view)
    tol = MATCH_TOL * unit
    ef, ec = _edge(faithful), _edge(clean)
    dist = ndimage.distance_transform_edt(~ef)
    bad = ec & (dist > tol)
    match_pct = 100 * (dist[ec] <= tol).mean()
    panels = [_panel(f"{stem}: faithful trace (grey) vs clean vector (green; red = more than {MATCH_TOL} units apart): {match_pct:.1f}% of the outline matches",
                     faithful, ec, bad, dist)]

    report = json.loads((project.path("out") / "report.json").read_text()).get(stem, {}) if (project.path("out") / "report.json").exists() else {}
    traced = project.path("traced") / f"{stem}.svg"
    if traced.exists() and "draft_transform" in report:
        import re
        S, tx, ty = report["draft_transform"]
        d_units = report.get("stroke_offset", 0.0)
        dpath = re.search(r' d="([^"]*)"', traced.read_text()).group(1)
        final = _render_d(dpath, n, (tx, ty, n * S))
        sd = (ndimage.distance_transform_edt(~faithful) - ndimage.distance_transform_edt(faithful)) * S  # units, + outside the draft
        e = _edge(final)
        lo, hi = min(0.0, d_units) - 0.02, max(0.0, d_units) + 0.02
        excess = np.where(e, np.maximum(sd - hi, 0) + np.maximum(lo - sd, 0), 0.0)
        bad2 = excess > 0.03
        share = 100 * bad2[e].mean()
        panels.append(_panel(f"final glyph over the draft: green within the intended stroke change ({d_units:+.3f} units per side), red beyond: {share:.1f}% (sharp tips extend by design)",
                             faithful, e, bad2, excess))
        big = Image.new("RGB", (panels[0].width, 300), "white")
        draw = ImageDraw.Draw(big)
        draw.text((10, 8), "final glyph: large, 32 px, 16 px", fill=(0, 0, 0))
        big.paste(Image.fromarray(render_svg(traced, 260, gray=True).astype("uint8")).convert("RGB"), (10, 30))
        big.paste(Image.fromarray(render_svg(traced, 32, gray=True).astype("uint8")).convert("RGB").resize((128, 128), Image.NEAREST), (290, 30))
        big.paste(Image.fromarray(render_svg(traced, 16, gray=True).astype("uint8")).convert("RGB").resize((128, 128), Image.NEAREST), (430, 30))
        panels.append(big)
    sheet = Image.new("RGB", (max(p.width for p in panels), sum(p.height for p in panels)), "white")
    y = 0
    for p in panels:
        sheet.paste(p, (0, y)); y += p.height
    out = project.path("out") / "inspect"
    out.mkdir(parents=True, exist_ok=True)
    sheet.save(out / f"{stem}.png")
    return out / f"{stem}.png"
