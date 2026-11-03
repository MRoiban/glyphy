"""End-to-end checks on synthetic glyphs (no external icon sets needed)."""
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

from glyphy import load, measure_references, measure_svg, trace_all
from glyphy.cli import main
from glyphy.config import Project, apply_setting
from glyphy.export import export, pick
from glyphy.raster import render_svg

GRID = 16


def outline_icon(stroke: float = 1.0, inset: float = 1.0) -> str:
    """A square outline icon: 14×14 live area, uniform stroke."""
    a, b = inset, GRID - inset
    c, d = a + stroke, b - stroke
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {GRID} {GRID}"><path fill-rule="evenodd" '
            f'd="M{a} {a}H{b}V{b}H{a}Z M{c} {c}V{d}H{d}V{c}Z"/></svg>')


def plus_icon() -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {GRID} {GRID}">'
            f'<path d="M7.5 1h1v6.5H15v1H8.5V15h-1V8.5H1v-1h6.5z"/></svg>')


def make_project(tmp_path: Path) -> Project:
    refs = tmp_path / "refs"
    refs.mkdir()
    for i in range(3):
        (refs / f"square{i}.svg").write_text(outline_icon())
    (refs / "plus.svg").write_text(plus_icon())
    main(["init", "-p", str(tmp_path / "proj"), "-r", str(refs)])
    return load(tmp_path / "proj")


def test_measure_learns_stroke_and_live_area(tmp_path):
    project = make_project(tmp_path)
    assert abs(project.style["stroke"] - 1.0) < 0.08
    assert abs(project.style["live"] - 14.0) < 0.1
    assert (project.path("out") / "reference-sheet.png").exists()


def test_locked_keys_survive_measurement(tmp_path):
    project = make_project(tmp_path)
    main(["set", "-p", str(project.root), "style.stroke=1.5", "--lock"])
    project = load(project.root)
    measure_references(project)
    assert project.style["stroke"] == 1.5
    assert "stroke" in project.style["locked"]


def test_one_off_overrides_are_not_saved(tmp_path):
    project = make_project(tmp_path)
    apply_setting(project, "trace.alphamax=1.2")
    assert project.trace["alphamax"] == 1.2
    assert load(project.root).trace["alphamax"] == 0.9


def test_trace_corrects_a_thick_draft(tmp_path):
    project = make_project(tmp_path)
    main(["add", "-p", str(project.root), "box", "a square outline"])
    # A draft drawn too heavy (about 1.8 units) and off-centre, as an image model might.
    mask = render_svg(outline_icon(stroke=1.0, inset=2.0), 1024)
    mask = ndimage.binary_dilation(mask, iterations=26)
    mask = np.roll(mask, (60, -40), axis=(0, 1))
    Image.fromarray(np.where(mask, 0, 255).astype("uint8")).save(project.path("generated") / "box-1.png")

    report = trace_all(load(project.root))
    result = report["box-1"]
    assert result["raw_stroke"] > 1.5
    assert result["ok"], result
    assert abs(result["stroke"] - 1.0) <= 0.12
    svg = (project.path("traced") / "box-1.svg").read_text()
    m = measure_svg(svg, GRID)
    assert m.min_pad >= project.style["pad_min"] - 0.01


def test_offsets_cover_half_a_unit():
    # Regression: 4 offsets once tried {0, -0.25, 0, +0.25} and never -0.5.
    work, offsets = 64, 4
    shifts = [round(k * work / offsets) - work // 2 for k in range(offsets)]
    assert shifts == [-32, -16, 0, 16]


def test_pick_and_export(tmp_path):
    project = make_project(tmp_path)
    main(["add", "-p", str(project.root), "box", "a square outline"])
    Image.fromarray(np.where(render_svg(outline_icon(), 1024), 0, 255).astype("uint8")).save(project.path("generated") / "box-1.png")
    trace_all(load(project.root))
    project = load(project.root)
    pick(project, best=True)
    ts = export(project, "ts", tmp_path / "glyphs.ts").read_text()
    assert '"box":' in ts and "GLYPH_GRID = 16" in ts
