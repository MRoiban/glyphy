"""Turning SVG and PNG files into binary ink masks on the glyph grid."""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

SVG_SUFFIXES = {".svg"}
RASTER_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def svg_bytes(source: str | Path | bytes) -> bytes:
    if isinstance(source, bytes):
        data = source
    elif isinstance(source, Path) or not str(source).lstrip().startswith("<"):
        data = Path(source).read_bytes()
    else:
        data = str(source).encode()
    # currentColor has no value outside a page; render it as black ink.
    return data.replace(b"currentColor", b"#000")


def render_svg(source: str | Path | bytes, size: int, gray: bool = False) -> np.ndarray:
    """Render an SVG to `size`×`size` pixels on white; returns a mask (or gray levels)."""
    import cairosvg

    png = cairosvg.svg2png(bytestring=svg_bytes(source), output_width=size, output_height=size, background_color="white")
    pixels = np.array(Image.open(io.BytesIO(png)).convert("L"))
    return pixels if gray else pixels < 128


def load_raster(path: str | Path, size: int | None = None) -> np.ndarray:
    """Black-on-white image → ink mask. Specks smaller than 1/2000 of the image are dropped."""
    img = Image.open(path).convert("L")
    if size:
        img = img.resize((size, size), Image.LANCZOS)
    pixels = np.array(img, dtype=float)
    mask = pixels < 128
    labels, count = ndimage.label(mask)
    if count:
        sizes = ndimage.sum(mask, labels, range(1, count + 1))
        mask = np.isin(labels, np.nonzero(sizes >= mask.size / 2000)[0] + 1)
    return mask


def load_mask(path: str | Path, size: int) -> np.ndarray:
    """Any supported glyph file as a `size`×`size` ink mask."""
    path = Path(path)
    if path.suffix.lower() in SVG_SUFFIXES:
        return render_svg(path, size)
    return load_raster(path, size)


def glyph_files(directory: str | Path) -> list[Path]:
    directory = Path(directory)
    return sorted(p for p in directory.iterdir() if p.suffix.lower() in SVG_SUFFIXES | RASTER_SUFFIXES)
