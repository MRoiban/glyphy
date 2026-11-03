"""glyphy.toml: the project file. Measured values live beside hand-set ones."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import tomli_w

FILE = "glyphy.toml"

DEFAULT_STYLE = {
    "grid": 16,              # units per side of the icon canvas (Codicons, Lucide: 16 / 24)
    "stroke": 1.0,           # measured: outline stroke width in grid units
    "stroke_tolerance": 0.12,
    "letter_stroke": [0.95, 1.45],  # measured: stroke range accepted for letterforms
    "letter_stroke_target": 1.2,    # measured: letterforms are corrected towards this stroke
    "live": 14.0,            # measured: largest ink box side for icons
    "letter_height": 12.0,   # measured: letterform height (letterforms fit this square)
    "pad_min": 0.75,         # measured: smallest padding allowed
    "centring_max": 0.5,     # |pad_l - pad_r| + |pad_t - pad_b|
    "crisp_reference": 0.59, # measured: median crispness of the references (informational)
    "roughness_reference": 0.24,  # measured: wobble of the roughest reference (informational)
    "roughness_max": 0.0,    # fail glyphs rougher than this (0 = report only)
    "locked": [],            # style keys `glyphy measure` must not overwrite
}

# Vectorisation knobs. Any of them can also be set per glyph in [glyphs.<name>].
DEFAULT_TRACE = {
    "work_scale": 64,        # px per grid unit while normalising and tracing
    "threshold": 128,        # gray level below which a draft pixel counts as ink
    "speck": 0.25,           # drop ink blobs smaller than this many square units
    "fit": True,             # scale and centre the draft into the target box
    "correct": True,         # erode/dilate towards the target stroke
    "stroke_shape": "cross", # "cross": 3×3 cross steps; "round": exact distance (rounds grown corners)
    "rounds": 5,             # fit/correct iterations
    "stroke_epsilon": 0.04,  # stop correcting within this many units of the target
    "smooth": 0.0,           # blur radius (units) to iron out noisy drafts before tracing (0 = off)
    "svg_as_drawn": True,    # SVG drafts are exact: skip fit, correction, smoothing and offsets
    "snap_mode": "corners",  # "corners": snap straight corners; "edges": straighten axis edges, snap only those
    "snap": 0.3,             # move points within this many units of a whole pixel onto it (0 = off)
    "straighten": 4.0,       # "edges" mode: edges within this many degrees of an axis become exact
    "offsets": 4,            # sub-pixel offset steps per unit tried for crispness (1 = off)
    "centring_weight": 0.0,  # offset choice: crispness minus this × off-centring (units)
    "turdsize": 16,          # potrace: ignore specks up to this many px
    "alphamax": 0.9,         # potrace: corner threshold (0 = all corners, 1.33 = all curves)
    "opticurve": True,       # potrace: join curve segments
    "opttolerance": 0.2,     # potrace: curve-joining tolerance
    "decimals": 3,           # coordinate precision in the SVG
}

DEFAULT_BRIEF = {
    "variants": 2,
    "image_size": 1024,
    "notes": "",       # appended to the generated brief
    "template": "",    # path to your own brief (Python format string); see glyphy.brief.CONTEXT_KEYS
}

DEFAULT_PATHS = {
    "reference": "reference",   # icons in the target style (SVG or PNG)
    "generated": "generated",   # image-model drafts: <name>-<n>.png (or hand-drawn .svg)
    "traced": "traced",         # vectorised, corrected drafts
    "picked": "glyphs",         # the chosen final SVGs
    "out": "out",               # reports, sheets, briefs
}


@dataclass
class Project:
    root: Path
    style: dict = field(default_factory=lambda: dict(DEFAULT_STYLE))
    paths: dict = field(default_factory=lambda: dict(DEFAULT_PATHS))
    glyphs: dict = field(default_factory=dict)   # name -> {concept, kind, replaces?}
    picks: dict = field(default_factory=dict)    # name -> variant stem
    trace: dict = field(default_factory=lambda: dict(DEFAULT_TRACE))
    brief: dict = field(default_factory=lambda: dict(DEFAULT_BRIEF))

    def path(self, key: str) -> Path:
        return self.root / self.paths[key]

    @property
    def grid(self) -> int:
        return int(self.style["grid"])

    def settings(self, name: str | None = None) -> dict:
        """Effective style + trace settings, with a glyph's own overrides on top."""
        merged = {**self.style, **self.trace}
        if name:
            merged.update({k: v for k, v in self.glyphs.get(name, {}).items() if k not in ("concept", "replaces")})
        return merged

    def save(self) -> None:
        data = {"style": self.style, "trace": self.trace, "paths": self.paths, "brief": self.brief, "glyphs": self.glyphs, "picks": self.picks}
        (self.root / FILE).write_text(HEADER + tomli_w.dumps(data))


HEADER = """# Glyphy project. `glyphy measure` rewrites the measured [style] values from the
# reference icons, except keys listed in style.locked. Everything is editable;
# any [style] or [trace] key can be overridden per glyph in [glyphs.<name>].
# Units are grid units unless noted.
"""


def load(root: str | Path = ".") -> Project:
    root = Path(root).resolve()
    file = root / FILE
    if not file.exists():
        raise SystemExit(f"No {FILE} in {root}. Run `glyphy init` first.")
    data = tomllib.loads(file.read_text())
    return Project(
        root=root,
        style={**DEFAULT_STYLE, **data.get("style", {})},
        trace={**DEFAULT_TRACE, **data.get("trace", {})},
        paths={**DEFAULT_PATHS, **data.get("paths", {})},
        glyphs=data.get("glyphs", {}),
        picks=data.get("picks", {}),
        brief={**DEFAULT_BRIEF, **data.get("brief", {})},
    )


def parse_value(text: str):
    """TOML literal if it parses (1.2, true, [1, 2], "x"), else the raw string."""
    try:
        return tomllib.loads(f"v = {text}")["v"]
    except tomllib.TOMLDecodeError:
        return text


def apply_setting(project: Project, assignment: str) -> tuple[str, object]:
    """Apply `section.key=value` (or `glyphs.<name>.key=value`) to the project in memory."""
    if "=" not in assignment:
        raise SystemExit(f"Expected key=value, got {assignment!r}.")
    key, raw = assignment.split("=", 1)
    value = parse_value(raw.strip())
    parts = key.strip().split(".")
    sections = {"style": project.style, "trace": project.trace, "paths": project.paths, "brief": project.brief}
    if parts[0] == "glyphs" and len(parts) == 3:
        project.glyphs.setdefault(parts[1], {"concept": parts[1], "kind": "icon"})[parts[2]] = value
    elif len(parts) == 2 and parts[0] in sections:
        sections[parts[0]][parts[1]] = value
    elif len(parts) == 1:
        # Bare keys go to whichever section defines them.
        for section in (project.style, project.trace, project.brief):
            if parts[0] in section:
                section[parts[0]] = value
                break
        else:
            raise SystemExit(f"Unknown setting {parts[0]!r}; use style.<key>, trace.<key>, brief.<key> or glyphs.<name>.<key>.")
    else:
        raise SystemExit(f"Cannot set {key!r}.")
    return key.strip(), value
