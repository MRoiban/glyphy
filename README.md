# Glyphy

Make icon glyphs that match an existing icon style, and prove they match.

Glyphy measures a reference icon set (stroke width, live area, padding,
letterform rules), writes a brief an image model can follow, then turns the
model's black-on-white drafts into clean SVG glyphs: it traces each draft
faithfully, rebuilds the outline from exact lines and smooth curves, corrects
the stroke weight and fits the glyph to the icon grid, all on the vector, never
on pixels. Every step is measured at the draft's full resolution, so the final
SVG is held to the drawing at any size, not only at 16 px.

![Drafts, traced glyphs at both sizes, reference icons and measurements](examples/codicon-style/out/sheet.png)

It is built for AI agents (one command per step, `glyphy status` says what is
next, skills for GPT-6 and Claude 5.5 models) without taking control away from
people: every rule and knob is in one file and can be pinned, overridden per
glyph, overridden for one run, or driven from Python.

## Install

```sh
uvx --from git+https://github.com/MRoiban/glyphy glyphy --help      # run without installing
uv tool install git+https://github.com/MRoiban/glyphy                # or install the `glyphy` command
pip install git+https://github.com/MRoiban/glyphy                    # or into any environment
```

Python ≥ 3.11 and the Cairo library (present on most Linux/macOS systems;
`brew install cairo` or `apt install libcairo2` otherwise).

## Quick start

```sh
glyphy init -p my-icons -r path/to/reference-icons/   # copy references, measure the style
glyphy add -p my-icons moon "a crescent moon"
glyphy add -p my-icons heading 'a capital "H"' --kind letter
glyphy brief -p my-icons                               # → my-icons/out/brief.md
# Generate drafts from the brief with an image model; save them as
#   my-icons/generated/<name>-<n>.png   (black ink on white)
glyphy trace -p my-icons                               # trace, vectorise, correct, fit, measure
glyphy sheet -p my-icons                               # → my-icons/out/sheet.png
glyphy inspect -p my-icons moon-1                      # → out/inspect/moon-1.png: full-resolution evidence
glyphy pick  -p my-icons --best                        # or: glyphy pick moon=2 heading=1
glyphy export -p my-icons -f ts -o src/glyphs.ts       # or -f json / -f sprite
glyphy export -p my-icons -f animl -o anim/            # one Anima document per glyph (-f ani for JSON)
glyphy status -p my-icons                              # where am I, what's next
```

## How it works

1. **Measure the references** (`glyphy measure`). Each reference is rendered at
   32 px per grid unit. Stroke width is twice the median distance from the
   skeleton to the edge; the ink box, padding, letterform weights and
   crispness are recorded. Medians become the rules (`out/baseline.json`
   keeps every number). On Codicons this finds a 1.0-unit stroke, a 14×14 live
   area, 1-unit padding and 1.2-unit letterforms.
2. **Brief** (`glyphy brief`). The rules in pixels at the image size, the
   output format and the glyph list, for the image model. Pass
   `out/reference-sheet.png` to it as a style reference.
3. **Trace** (`glyphy trace`), per draft:
   1. *Faithful trace*: the outline of the grey draft at the ink threshold
      (marching squares), so edges sit between pixels where the anti-aliasing
      puts them. It covers the draft's pixels to 99.98%, ruggedness included.
   2. *Vectorise*: find the real corners; runs that are straight within
      `line_tol` become exact lines, the rest smooth cubic Béziers (Schneider's
      curve fitting) within `curve_tol`; corners between lines become exact
      intersections; lines snap to 0/45/90° and near-parallel lines become
      parallel only where the drawing still agrees. Reported as
      `vector_match`: the share of the outline within 0.03 units of the
      faithful trace, at the draft's resolution (99.6–100% on the example).
   3. *Stroke weight*: the clean outline is offset by half the stroke error
      with mitred corners and re-fitted; corners stay sharp because the input
      is exact. Separate solid shapes (a filled star, a dot) keep their size.
   4. *Fit*: the vector is scaled and moved into the glyph box, sized so the
      box is exactly filled after the offset. Nothing is resampled.
   5. *Pixels*: the whole glyph is shifted by the sub-unit offset that is
      crispest at 16 and 32 px (no distortion). Optional TrueType-style hinting
      (`trace.hint`) moves whole horizontal/vertical edges onto pixel lines,
      stem pairs together, and interpolates the rest; it is off by default
      because it buys little crispness and moves outlines off the drawing.
   6. *Check*: the result is re-rendered and measured with the same code as the
      references (stroke, box, padding, centring, crispness at 1× and 2×).
4. **Inspect** (`glyphy inspect`). Full-resolution evidence per draft: the
   faithful trace against the clean vector, and the final glyph mapped back
   onto the draft, each with the worst spots enlarged. Small renders hide the
   defects that matter in a vector; this is the view to judge a glyph by.
5. **Review** (`glyphy sheet`): draft, traced glyph large and at 16 px, the
   icon it replaces, and its numbers.

## Profiles

The vector pipeline is the default. Two older pixel pipelines remain available
as profiles. Measured on the example's 22 drafts, with the final glyph mapped
back onto its draft at the draft's resolution (1254 px):

| | outline beyond the intended stroke change | worst point (typical) | crisp at 16 px |
|---|---|---|---|
| `vector` (default) | **0.8%** | **0.06 units** | 0.45 |
| `refined` (pixels) | 18.2% | 0.20 units | 0.51 |
| `classic` (pixels) | 36.8% | 0.32 units | 0.53 |

The pixel pipelines correct the stroke by growing or shrinking pixels and snap
corners one by one, which buys crispness at 16 px at the cost of hooks, bevels
and wobble at every larger size. The vector pipeline keeps the drawing: what
remains beyond the stroke change is the extension of sharp mitred tips, which a
thicker stroke has by geometry.

```sh
glyphy init -p icons -r refs/ --profile classic   # or later:
glyphy set -p icons --profile vector
```

A profile only writes settings into `glyphy.toml`; change any of them afterwards.

## Configuration

Everything lives in `glyphy.toml`:

| Section | What it holds |
|---|---|
| `[style]` | The rules. `stroke`, `letter_stroke` (accepted range), `letter_stroke_target`, `live`, `letter_height`, `pad_min`, `crisp_reference` and `roughness_reference` are written by `glyphy measure` unless listed in `locked`. `grid`, `stroke_tolerance`, `centring_max` (0.5) and `roughness_max` (0 = report only) are yours. |
| `[trace]` | `method` (`vector`/`raster`). Shared: `threshold`, `speck` (units²), `fit`, `correct`, `stroke_epsilon`, `offsets`, `weight_crisp_2x`, `decimals`. Vector: `corner_deg`, `corner_scale`, `line_tol`, `min_line`, `curve_tol`, `snap_deg`, `parallel_deg`, `max_extend`, `vector_mitre_limit`, `hint`, `snap` (hinting reach), `hint_min_len`. Raster: `work_scale`, `stroke_shape`, `rounds`, `smooth`, `svg_as_drawn`, `snap_mode`, `straighten`, `centring_weight`, `choose` and `weight_*`, potrace's `turdsize`, `alphamax`, `opticurve`, `opttolerance`. |
| `[brief]` | `variants`, `image_size`, `notes`, and `template` (your own brief). |
| `[paths]` | Folder names for references, drafts, traced files, picks and reports. |
| `[glyphs.<name>]` | `concept`, `kind` (`icon`/`letter`), `replaces`, plus any `[style]`/`[trace]` key for this glyph alone, and `box = [w, h]` or `stroke_target`. |
| `[picks]` | The chosen variant per glyph. |

Each traced glyph's entry in `out/report.json` has its rules (`stroke`, `box`,
`min_pad`, `centring`, each with `_ok`), `crisp` / `crisp_2x`, and for the
vector method `vector_match`, `vector_worst` (units), `segments`,
`stroke_offset` and `draft_transform` (draft pixels → glyph units).

## Control for power users

The defaults are a starting point, never a cage:

```sh
glyphy set style.stroke=1.5 --lock                  # pin a rule; `measure` will keep it
glyphy set trace.line_tol=0.02 trace.corner_deg=25  # tighten what counts as straight / a corner
glyphy set glyphs.moon.curve_tol=0.015              # follow one glyph's curves more closely
glyphy set glyphs.heading.stroke_target=1.0         # force a stroke for one glyph
glyphy set trace.hint=true                          # grid-fit edges for maximum 16 px crispness
glyphy trace --only moon --set trace.offsets=8      # one run, not saved
glyphy config --glyph moon                          # the exact settings tracing will use
glyphy set brief.template=my-brief.md               # your own brief, with {placeholders}
```

Template placeholders: `grid`, `image_size`, `unit_px`, `variants`,
`reference_sheet`, `generated_dir`, `stroke`, `stroke_px`, `letter_stroke_min`,
`letter_stroke_max`, `live`, `live_px`, `letter_height`, `pad_min`, `pad_px`,
`notes`, `glyph_list`, `default_brief`.

From Python, every stage is a function:

```python
from pathlib import Path
from glyphy import load, trace_file
from glyphy import vector as V
from glyphy.vtrace import stages

project = load("my-icons")
draft = Path("my-icons/generated/moon-1.png")
svg, report = trace_file(project, draft, {"curve_tol": 0.015})

st = stages(project, draft)                    # faithful contours + clean vector, in draft pixels
rings = V.transform(st["clean"], 1 / st["unit"])   # into grid units
rings = V.offset(rings, 0.1)                    # 0.1 units bolder, mitred
print(V.to_svg(rings, project.grid))
```

## Animating glyphs with Anima

`glyphy export -f animl -o DIR` (or `-f ani`) writes one Anima
document per picked glyph: a static icon whose rest frame is the glyph, carrying its concept,
kind, the style's stroke, the picked variant and a SHA-256 of the path. The files are exactly what
`anima new <name> --glyphy <project>` writes, so either tool can start the animation.
From Python: `anima_document(project, name, d)` and `anima_markup(doc)`.

## Agents

- `skills/glyphy-gpt/` — for GPT-6 family models (Codex), which can generate images.
- `skills/glyphy-claude/` — for Claude 5.5 family models, which cannot generate
  images and either delegate generation or draft SVG on the grid.

Install a skill by copying its folder into the agent's skills directory
(`~/.codex/skills/` or `~/.claude/skills/`). `AGENTS.md` describes the repository
for agents working on Glyphy itself.

## Example

`examples/codicon-style/` is a complete project: 30 Codicons as references,
11 new glyphs (heading, maths, comment, follow cursor, section, sun, moon, dark
pages, main file, Typst file) with two drafts each from GPT-6.1 Terra's image
generation, traced with the vector pipeline, picked and exported, with
`out/inspect/` evidence for every pick. A test retraces the picks and expects
the committed glyphs pixel for pixel.

## Licence

MIT. The Codicons in `examples/codicon-style/reference` are © Microsoft, CC BY 4.0
(see `examples/codicon-style/NOTICE`).
