"""Contact sheet: draft | traced (large) | traced (native size, enlarged) | reference | numbers."""
from __future__ import annotations

import json

import numpy as np
from PIL import Image, ImageDraw

from .config import Project
from .raster import glyph_files, load_mask, render_svg


def _tile(mask: np.ndarray, size: int) -> Image.Image:
    return Image.fromarray(np.where(mask, 0, 255).astype("uint8")).resize((size, size), Image.NEAREST)


def _large(svg_path, size: int) -> Image.Image:
    # Anti-aliased: nearest-neighbour scaling invents stairs on diagonals that are not in the SVG.
    return Image.fromarray(render_svg(svg_path, size, gray=True).astype("uint8"))


def _native(svg_path, grid: int, size: int) -> Image.Image:
    gray = render_svg(svg_path, grid, gray=True)
    return Image.fromarray(gray.astype("uint8")).resize((size, size), Image.NEAREST)


def contact_sheet(project: Project) -> str:
    grid = project.grid
    report = json.loads((project.path("out") / "report.json").read_text())
    traced = {p.stem: p for p in project.path("traced").glob("*.svg")}
    drafts = {p.stem: p for p in glyph_files(project.path("generated"))}
    refs = {p.stem: p for p in glyph_files(project.path("reference"))}
    stems = sorted(traced)
    t, row = 72, 96
    sheet = Image.new("L", (4 * (t + 16) + 360, 40 + row * max(1, len(stems))), 255)
    draw = ImageDraw.Draw(sheet)
    for x, label in zip([8, 96, 184, 272, 360], ["draft", "traced", f"traced @{grid}px", "reference", "measurements"]):
        draw.text((x, 12), label, fill=0)
    for i, stem in enumerate(stems):
        y = 36 + i * row
        r = report.get(stem, {})
        if stem in drafts:
            sheet.paste(_tile(load_mask(drafts[stem], 256), t), (8, y))
        sheet.paste(_large(traced[stem], t), (96, y))
        sheet.paste(_native(traced[stem], grid, t), (184, y))
        replaces = project.glyphs.get(r.get("glyph", stem.rsplit("-", 1)[0]), {}).get("replaces")
        if replaces and replaces in refs:
            sheet.paste(_native(refs[replaces], grid, t) if refs[replaces].suffix == ".svg" else _tile(load_mask(refs[replaces], grid), t), (272, y))
        status = "PASS" if r.get("ok") else "FAIL"
        draw.text((360, y + 2), f"{stem}  {status}", fill=0)
        if "stroke" in r:
            draw.text((360, y + 20), f"stroke {r['raw_stroke']:.2f} -> {r['stroke']:.2f} (target {r['stroke_target']:.2f})", fill=0)
            draw.text((360, y + 38), f"box {r['box'][0]:.1f} x {r['box'][1]:.1f}  pad {r['min_pad']:.2f}  crisp {r['crisp']:.2f}", fill=0)
            if "vector_match" in r:
                draw.text((360, y + 56), f"vector {r['vector_match']:.1%} of draft outline  crisp 2x {r.get('crisp_2x', 0):.2f}  {r['segments']} segments", fill=0)
            elif "roughness" in r:
                draw.text((360, y + 56), f"rough {r['roughness']:.2f}  crisp 2x {r.get('crisp_2x', 0):.2f}  drift {r.get('drift', 0):.2f}", fill=0)
        if replaces:
            draw.text((360, y + 74), f"replaces {replaces}", fill=100)
    path = project.path("out") / "sheet.png"
    sheet.save(path)
    return str(path)
