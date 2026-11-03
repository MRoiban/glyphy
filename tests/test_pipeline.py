"""End-to-end checks on synthetic glyphs (no external icon sets needed)."""
from pathlib import Path

import numpy as np
import pytest
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


def test_offset_shifts():
    from glyphy.trace import offset_shifts
    assert offset_shifts(64, 4) == [0, -16, 16]
    assert offset_shifts(64, 1) == [0]


EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "codicon-style"


def test_defaults_reproduce_the_example():
    """The defaults are the pipeline that made Typewriter's glyphs; the example pins them."""
    from glyphy.trace import trace_file
    project = load(EXAMPLE)
    for stem in ["heading-2", "theme-light-2"]:
        svg, report = trace_file(project, EXAMPLE / "generated" / f"{stem}.png")
        picked = EXAMPLE / "glyphs" / f"{stem.rsplit('-', 1)[0]}.svg"
        assert report["ok"]
        assert not (render_svg(svg, 512) != render_svg(picked, 512)).any(), stem


def test_pick_and_export(tmp_path):
    project = make_project(tmp_path)
    main(["add", "-p", str(project.root), "box", "a square outline"])
    Image.fromarray(np.where(render_svg(outline_icon(), 1024), 0, 255).astype("uint8")).save(project.path("generated") / "box-1.png")
    trace_all(load(project.root))
    project = load(project.root)
    pick(project, best=True)
    ts = export(project, "ts", tmp_path / "glyphs.ts").read_text()
    assert '"box":' in ts and "GLYPH_GRID = 16" in ts


def test_roughness_counts_wobble_not_size():
    from glyphy.metrics import roughness
    clean = outline_icon()
    # The same square with a saw-toothed top edge.
    teeth = "".join(f"L{x + 0.25} {1.35 if i % 2 else 1}" for i, x in enumerate(np.arange(1, 15, 0.5)))
    rough = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path fill-rule="evenodd" '
             f'd="M1 1{teeth}L15 1V15H1Z M2 2.4V14H14V2.4Z"/></svg>')
    # One toothed edge among long clean ones still exceeds the roughest Codicon (0.24).
    assert roughness(clean, GRID) < 0.05
    assert roughness(rough, GRID) > 0.24


@pytest.mark.parametrize("mode", ["corners", "edges"])
def test_straight_edges_land_on_pixels(tmp_path, mode):
    from glyphy.metrics import crispness
    from glyphy.trace import to_svg
    project = make_project(tmp_path)
    cfg = {**project.settings(), "snap_mode": mode}
    # A square outline drawn slightly off the pixel grid and a little crooked.
    mask = render_svg(outline_icon(), GRID * 64)
    mask = np.roll(mask, (9, -7), axis=(0, 1))
    svg = to_svg(mask, cfg, GRID)
    assert crispness(svg, GRID) > 0.95


def test_svg_drafts_are_taken_as_drawn(tmp_path):
    project = make_project(tmp_path)
    main(["add", "-p", str(project.root), "box", "a square outline"])
    # Smaller than the live area: fitting would scale it, as-drawn must not.
    (project.path("generated") / "box-1.svg").write_text(outline_icon(inset=3.0))
    result = trace_all(load(project.root))["box-1"]
    assert result["box"] == [10.0, 10.0] and result["crisp"] == 1.0
    main(["set", "-p", str(project.root), "trace.svg_as_drawn=false"])
    result = trace_all(load(project.root))["box-1"]
    assert result["box"][0] > 13  # fitted (then thinned back to a 1-unit stroke)
