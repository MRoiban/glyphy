"""How faithful a traced glyph is to its draft, and how even its strokes are.

Both work on centrelines (skeletons) so the intended stroke correction does not
count as unfaithfulness: a draft thickened from 0.6 to 1.0 units with every
stroke still in place has zero drift.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage
from skimage.morphology import skeletonize

from .raster import render_svg

SCALE = 32  # px per grid unit for these measurements


@dataclass
class Centreline:
    points: np.ndarray   # (n, 2) skeleton pixels, y/x
    extent: tuple        # y0, x0, y1, x1 of the skeleton

    @classmethod
    def of(cls, mask: np.ndarray) -> "Centreline":
        ys, xs = np.nonzero(skeletonize(mask))
        points = np.stack([ys, xs], 1).astype(float)
        return cls(points, (*points.min(0), *points.max(0)) if len(points) else (0, 0, 1, 1))


def drift(draft: Centreline, glyph_mask: np.ndarray) -> tuple[float, float]:
    """Mean and 95th-percentile distance (units) between the draft's and the glyph's centrelines.

    The draft's skeleton box is mapped onto the glyph's first, so fitting and
    centring do not count; what remains is shape change. `glyph_mask` must be
    rendered at SCALE px per unit.
    """
    skel = skeletonize(glyph_mask)
    ys, xs = np.nonzero(skel)
    if not len(ys) or not len(draft.points):
        return float("nan"), float("nan")
    (dy0, dx0, dy1, dx1), (gy0, gx0, gy1, gx1) = draft.extent, (ys.min(), xs.min(), ys.max(), xs.max())
    my = (draft.points[:, 0] - dy0) / max(dy1 - dy0, 1) * (gy1 - gy0) + gy0
    mx = (draft.points[:, 1] - dx0) / max(dx1 - dx0, 1) * (gx1 - gx0) + gx0
    iy = np.clip(np.round(my).astype(int), 0, skel.shape[0] - 1)
    ix = np.clip(np.round(mx).astype(int), 0, skel.shape[1] - 1)
    mapped = np.zeros_like(skel)
    mapped[iy, ix] = True
    d = np.concatenate([ndimage.distance_transform_edt(~skel)[iy, ix],
                        ndimage.distance_transform_edt(~mapped)[skel]]) / SCALE
    return float(d.mean()), float(np.percentile(d, 95))


def stroke_spread(mask: np.ndarray) -> float:
    """Interquartile range of stroke widths (units) along the centreline: 0 = perfectly even."""
    widths = 2 * ndimage.distance_transform_edt(mask)[skeletonize(mask)] / SCALE
    if not len(widths):
        return float("nan")
    low, high = np.percentile(widths, [25, 75])
    return float(high - low)


def render(svg, grid: int) -> np.ndarray:
    return render_svg(svg, grid * SCALE)
