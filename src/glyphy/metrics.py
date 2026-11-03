"""Glyph measurements in grid units.

The same functions measure the reference icons (to learn the style) and the
traced glyphs (to check them), so a rule and its check can never disagree.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from scipy import ndimage
from skimage.morphology import skeletonize

from .raster import render_svg


@dataclass
class Metrics:
    stroke: float          # median stroke width (2 × distance to the edge along the skeleton)
    width: float           # ink bounding box
    height: float
    pad_left: float
    pad_right: float
    pad_top: float
    pad_bottom: float
    coverage: float        # share of the grid covered by ink
    components: int        # separate ink shapes
    holes: int             # enclosed counters

    @property
    def min_pad(self) -> float:
        return min(self.pad_left, self.pad_right, self.pad_top, self.pad_bottom)

    @property
    def centring(self) -> float:
        return abs(self.pad_left - self.pad_right) + abs(self.pad_top - self.pad_bottom)

    def as_dict(self) -> dict:
        return {k: round(v, 3) if isinstance(v, float) else v for k, v in asdict(self).items()}


def measure(mask: np.ndarray, scale: float, grid: int) -> Metrics | None:
    """Measure an ink mask rendered at `scale` pixels per grid unit."""
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    dist = ndimage.distance_transform_edt(mask)
    widths = 2 * dist[skeletonize(mask)]
    if len(widths):
        # Corners and junctions inflate the distance; the central band is the true stroke.
        lo, hi = np.percentile(widths, [20, 80])
        core = widths[(widths >= lo) & (widths <= hi)]
        stroke = float(np.median(core if len(core) else widths) / scale)
    else:
        stroke = float("nan")
    holes = ndimage.label(~mask)[1] - 1
    return Metrics(
        stroke=stroke,
        width=float((x1 - x0) / scale), height=float((y1 - y0) / scale),
        pad_left=float(x0 / scale), pad_right=float(grid - x1 / scale),
        pad_top=float(y0 / scale), pad_bottom=float(grid - y1 / scale),
        coverage=float(mask.mean()),
        components=int(ndimage.label(mask)[1]), holes=int(max(0, holes)),
    )


def measure_svg(svg, grid: int, scale: int = 32) -> Metrics | None:
    return measure(render_svg(svg, grid * scale), scale, grid)


def crispness(svg, grid: int) -> float:
    """Share of inked pixels that are solid at the native size (1 px per grid unit).

    Edges between pixels render grey; icons drawn on the pixel grid stay crisp.
    """
    gray = render_svg(svg, grid, gray=True).astype(float)
    ink = gray < 230
    return float((gray[ink] < 64).mean()) if ink.any() else 0.0
