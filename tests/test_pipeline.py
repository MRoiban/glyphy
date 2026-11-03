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


def make_project(tmp_path: Path, method: str | None = None) -> Project:
    refs = tmp_path / "refs"
    refs.mkdir()
    for i in range(3):
        (refs / f"square{i}.svg").write_text(outline_icon())
    (refs / "plus.svg").write_text(plus_icon())
    main(["init", "-p", str(tmp_path / "proj"), "-r", str(refs)])
    if method:
        main(["set", "-p", str(tmp_path / "proj"), f'trace.method="{method}"'])
    return load(tmp_path / "proj")


def save_draft(project: Project, name: str, svg: str, size: int = 1024) -> None:
    """An anti-aliased black-on-white PNG draft, like an image model's."""
    Image.fromarray(render_svg(svg, size, gray=True).astype("uint8")).save(project.path("generated") / f"{name}.png")


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


@pytest.mark.parametrize("method", ["raster", "vector"])
def test_trace_corrects_a_thick_draft(tmp_path, method):
    project = make_project(tmp_path, method)
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


def test_defaults_reproduce_the_example(tmp_path):
    """The defaults are the pipeline that made Typewriter's glyphs; the example pins them."""
    import shutil
    project_dir = tmp_path / "example"
    shutil.copytree(EXAMPLE, project_dir, ignore=shutil.ignore_patterns("traced", "report.json"))
    project = load(project_dir)
    report = trace_all(project, only=list(project.picks.values()))
    for name, stem in project.picks.items():
        assert report[stem]["ok"], stem
        traced = render_svg(project.path("traced") / f"{stem}.svg", 512)
        assert not (traced != render_svg(EXAMPLE / "glyphs" / f"{name}.svg", 512)).any(), stem


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
    project = make_project(tmp_path, "raster")
    cfg = {**project.settings(), "snap_mode": mode}
    # A square outline drawn slightly off the pixel grid and a little crooked.
    mask = render_svg(outline_icon(), GRID * 64)
    mask = np.roll(mask, (9, -7), axis=(0, 1))
    svg = to_svg(mask, cfg, GRID)
    assert crispness(svg, GRID) > 0.95


def test_svg_drafts_are_taken_as_drawn(tmp_path):
    project = make_project(tmp_path, "raster")
    main(["add", "-p", str(project.root), "box", "a square outline"])
    # Smaller than the live area: fitting would scale it, as-drawn must not.
    (project.path("generated") / "box-1.svg").write_text(outline_icon(inset=3.0))
    result = trace_all(load(project.root))["box-1"]
    assert result["box"] == [10.0, 10.0] and result["crisp"] == 1.0
    main(["set", "-p", str(project.root), "trace.svg_as_drawn=false"])
    result = trace_all(load(project.root))["box-1"]
    assert result["box"][0] > 13  # fitted (then thinned back to a 1-unit stroke)


def test_mitre_correction_keeps_corners_square(tmp_path):
    from glyphy.metrics import crispness
    project = make_project(tmp_path)
    main(["add", "-p", str(project.root), "box", "a square outline"])
    main(["set", "-p", str(project.root), "--profile", "refined", "trace.offsets=1"])
    # A thin draft (0.6 units): growing pixels rounds its corners, offsetting the outline must not.
    Image.fromarray(np.where(render_svg(outline_icon(stroke=0.6), 1024), 0, 255).astype("uint8")).save(
        project.path("generated") / "box-1.png")
    result = trace_all(load(project.root), jobs=1)["box-1"]
    assert result["ok"], result
    assert abs(result["stroke"] - 1.0) <= 0.05
    assert result["drift"] < 0.1 and result["stroke_spread"] < 0.1
    assert crispness(project.path("traced") / "box-1.svg", GRID) > 0.9


def test_profiles_are_plain_settings(tmp_path):
    from glyphy.config import PROFILES
    project = make_project(tmp_path)
    main(["set", "-p", str(project.root), "--profile", "refined"])
    assert all(load(project.root).trace[k] == v for k, v in PROFILES["refined"].items())
    main(["set", "-p", str(project.root), "--profile", "classic", "trace.straighten=6"])
    trace = load(project.root).trace
    assert trace["choose"] == "crisp" and trace["straighten"] == 6



# ---------------------------------------------------------------- vector method
def parallelogram(width: float = 0.6) -> str:
    """A slanted stroke with flat-cut ends, like a slash."""
    hw = width / 2 / np.sin(np.arctan2(10, 4))  # horizontal half-width for a perpendicular `width`
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {GRID} {GRID}">'
            f'<path d="M{6 - hw} 13H{6 + hw}L{10 + hw} 3H{10 - hw}Z"/></svg>')


def test_faithful_trace_matches_the_pixels():
    from glyphy import vector as V
    gray = render_svg(parallelogram(1.0), 1024, gray=True).astype(float)
    rings = V.faithful(gray)
    d = "".join("M" + "L".join(f"{x} {y}" for x, y in r) + "Z" for r in rings)
    traced = render_svg(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024"><path d="{d}"/></svg>', 1024)
    ink = gray < 128
    assert (traced & ink).sum() / (traced | ink).sum() > 0.999


def test_vector_traces_a_square_outline_as_eight_lines(tmp_path):
    project = make_project(tmp_path)  # vector is the default method
    main(["add", "-p", str(project.root), "box", "a square outline"])
    save_draft(project, "box-1", outline_icon(stroke=0.7, inset=3.0))
    result = trace_all(load(project.root), jobs=1)["box-1"]
    assert result["ok"], result
    assert result["segments"] == 8 and result["vector_match"] > 0.99
    assert abs(result["stroke"] - 1.0) <= 0.05 and result["crisp"] > 0.9
    assert "C" not in (project.path("traced") / "box-1.svg").read_text().split(' d="')[1]


def test_vector_keeps_slants_parallel_and_ends_flat(tmp_path):
    import re
    project = make_project(tmp_path)
    main(["add", "-p", str(project.root), "slash", "a forward slash"])
    save_draft(project, "slash-1", parallelogram(0.6))
    result = trace_all(load(project.root), jobs=1)["slash-1"]
    assert result["ok"] and result["segments"] == 4, result
    d = (project.path("traced") / "slash-1.svg").read_text().split(' d="')[1]
    pts = np.array([[float(a), float(b)] for a, b in re.findall(r"(-?[\d.]+) (-?[\d.]+)", d)])[:4]
    sides = [pts[(i + 1) % 4] - pts[i] for i in range(4)]
    cross = lambda u, v: abs(u[0] * v[1] - u[1] * v[0]) / (np.linalg.norm(u) * np.linalg.norm(v))  # noqa: E731
    assert cross(sides[0], sides[2]) < 1e-3 and cross(sides[1], sides[3]) < 1e-3  # still a parallelogram
    assert min(abs(s[1]) for s in sides) < 1e-3  # the end cuts stay horizontal


def test_offset_thickens_strokes_but_keeps_fills():
    from shapely.geometry import Polygon
    from glyphy import vector as V
    ring = lambda pts: [np.array([pts[i], pts[(i + 1) % len(pts)]]) for i in range(len(pts))]  # noqa: E731
    outline = [ring([(1, 1), (15, 1), (15, 15), (1, 15)]), ring([(2, 2), (2, 14), (14, 14), (14, 2)])]  # 1-unit frame
    fill = [ring([(6, 6), (10, 6), (10, 10), (6, 10)])]  # a solid 4×4 block
    area = lambda rings: V._geometry(rings, 0.01).area  # noqa: E731
    thick = V.offset(outline + fill, 0.1, stroke=1.0)
    frame, block = sorted(V._components(V._geometry(thick, 0.01)), key=lambda g: -g.area)
    assert abs(block.area - 16.0) < 0.05  # the fill keeps its size
    assert abs(frame.area - area(outline) - 0.1 * (56 + 48)) < 0.3  # the frame grew by 0.1 on every side
