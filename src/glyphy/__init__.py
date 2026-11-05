"""Glyphy: icon glyphs that match a reference style, verified by measurement.

Python API (the CLI is a thin layer over these):

    from glyphy import load, measure_references, write_brief, trace_all, trace_file, check_svg
    project = load("my-icons")            # glyphy.toml
    project.style["stroke"] = 1.5         # anything is editable in memory
    measure_references(project)           # learn rules from reference icons
    svg, report = trace_file(project, Path("generated/moon-1.png"), {"alphamax": 1.1})

Lower-level pieces: glyphy.vector (faithful, vectorize, offset, hint, to_svg),
glyphy.vtrace.trace_vector / stages, glyphy.inspect.inspect, glyphy.metrics.measure /
crispness, glyphy.trace.normalise / to_svg / check, glyphy.raster.render_svg.
"""
__version__ = "0.2.0"

from .brief import write_brief
from .config import Project, apply_setting, load
from .export import anima_document, anima_markup, export, pick
from .metrics import Metrics, crispness, measure, measure_svg
from .style import measure_references
from .trace import check_svg, normalise, to_svg, trace_all, trace_file

__all__ = [
    "Project", "load", "apply_setting", "measure_references", "write_brief", "trace_all", "trace_file",
    "check_svg", "normalise", "to_svg", "pick", "export", "anima_document", "anima_markup", "Metrics", "measure", "measure_svg", "crispness",
]
