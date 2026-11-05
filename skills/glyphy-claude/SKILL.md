---
name: glyphy
description: Create custom icon glyphs that match an existing icon style (Codicons, Lucide, a product's own set) and verify them by measurement with Glyphy. Covers measuring the reference style, producing drafts (delegated to an image model, or drafted as SVG on the icon grid), tracing them into clean vectors with corrected stroke weight, and reviewing them at full resolution against the drafts and the references. Use when asked for new icons "in the same style", for concepts an icon set lacks, or to check that icons match a style.
---

# Glyphy (Claude 5.5 family)

Glyphy makes new icons match an existing set and proves it. It learns the
style's rules from reference icons (stroke width, live area, padding,
letterform weight), then traces each draft faithfully, rebuilds the outline
from exact lines and smooth curves, corrects the stroke weight on that vector
and fits it to the icon grid, measuring every stage at the draft's full
resolution. Your job is the judgement around it: picking good references,
checking the measured rules make sense, producing drafts, and deciding which
results read well. A glyph is finished when it passes **and** its inspect
image shows the outline sitting on the drawing, **and** it looks right beside
its neighbours.

Run Glyphy with `uvx --from git+https://github.com/MRoiban/glyphy glyphy <command>`
(or `glyphy` if installed). Every command takes `-p <project folder>`;
`glyphy status -p <folder>` tells you where things stand.

## 1. Gather the inputs

- **Reference icons** (needed): 10–40 SVGs (PNG works too) from the target set,
  one per file, on the same grid. The references *are* the style, so choose
  ones typical of it: outline icons for an outline set, and a few letterforms
  (B, I, a numeral) if you will make letters or symbols.
- **Grid** (units per side): 16 for Codicons, 24 for Lucide and Material.
- **Glyphs**: a name, a one-line concept that describes the *drawing* (not the
  feature: "a crescent moon", not "dark mode"), whether it is a letterform, and
  optionally the icon it replaces so the sheet shows them side by side.

## 2. Measure the style and check the rules

```
glyphy init -p icons -r <reference files or folder> --grid 16
```

Read the rules it prints and sanity-check them against the reference sheet
(`icons/out/reference-sheet.png`, which you can view):

| Rule | Meaning | Typical (Codicons) |
|---|---|---|
| `stroke` | outline stroke width, grid units | 1.0 |
| `letter_stroke` | accepted range for letterforms | 0.95–1.45 |
| `letter_stroke_target` | weight letterforms are corrected towards | 1.2 |
| `live` | largest side of an icon's ink | 14 of 16 |
| `letter_height` | letterforms fit a square this tall (whole units) | 12 |
| `pad_min` | smallest margin allowed | 0.75 |

If a value contradicts what you see (for example the set is clearly 1-unit
line icons but `stroke` came out 1.6 because several references are filled),
remove the odd references and re-run `glyphy measure`, or pin the value:
`glyphy set -p icons style.stroke=1.0 --lock`. Locked values survive measurement.

## 3. Describe the glyphs

```
glyphy add -p icons moon "a crescent moon" --replaces color-mode
glyphy add -p icons heading 'a geometric sans-serif capital "H"' --kind letter
glyphy brief -p icons
```

`icons/out/brief.md` is a complete, self-contained prompt built from the
measured rules: sizes in pixels, output format, file names, the glyph list.

## 4. Produce drafts

You cannot generate raster images yourself, so use one of these routes. Prefer
the first: the pipeline is built for image-model drafts.

**A. Delegate to an image-capable agent or tool.** If you can start a
sub-agent on a model with image generation (for example GPT-6 on Codex) or the
user has an image tool, hand over `out/brief.md` verbatim together with the
absolute path of `out/reference-sheet.png`, and ask for files at
`generated/<name>-<n>.png`. Ask for clean, large drawings; Glyphy corrects
stroke weight, size and position itself but keeps the shape. Two variants per
glyph gives you a choice.

**B. Draft SVG on the grid yourself.** Write `generated/<name>-<n>.svg` with
`viewBox="0 0 <grid> <grid>"`, black on white, strokes or filled outlines.
Glyphy renders it at high resolution and runs it through the same pipeline, so
straight edges come out as exact lines and curves as Béziers. Keep to what reads
at native size: about `grid − 2` pixels across. For SVGs that are already final,
use `glyphy check -p icons <files>` instead (it exits 1 if any fails).

## 5. Trace, inspect, review

```
glyphy trace -p icons
glyphy inspect -p icons            # every traced draft, or name stems
glyphy sheet -p icons
```

`trace` prints PASS/FAIL per draft with stroke (raw → corrected), box, padding,
crispness, `vector` (share of the draft's outline the clean vector matches
within 0.03 units at the draft's resolution; expect 99%+) and the segment count.
`out/report.json` has every number.

View `out/inspect/<stem>.png` for each candidate. It is drawn at the draft's own
resolution because small renders hide exactly the defects that matter:
- top: faithful trace (grey) vs clean vector (green, red where they differ);
- middle: final glyph mapped onto the draft, red where it moved beyond the
  intended stroke change (sharp mitred tips extend a little by geometry);
- bottom: the glyph large and at 32 / 16 px.

Then view `out/sheet.png` to judge the glyphs beside the icons they replace.
Remedies, one glyph at a time:

- **A corner rounded off, or a curve given a corner**: `glyphy set glyphs.<name>.corner_deg=25`
  (lower finds more corners) or `=40` (fewer).
- **A gentle curve straightened, or a line left wavy**: lower or raise
  `glyphs.<name>.line_tol` (straightness tolerance, units).
- **A curve drifting off the drawing**: lower `glyphs.<name>.curve_tol`.
- **Wrong weight**: `glyphs.<name>.stroke_target`; **wrong size**: `glyphs.<name>.box=[w,h]`.
- **The drawing itself is off** (lumpy, too detailed, wrong concept): get a new draft;
  Glyphy is faithful to what it is given.

Re-run `glyphy trace -p icons --only <name>` after each change.
`glyphy config -p icons --glyph <name>` shows the exact settings in effect.

## 6. Choose and deliver

```
glyphy pick -p icons --best            # passing + crispest per glyph
glyphy pick -p icons heading=2         # or choose by eye
glyphy export -p icons -f ts -o <app>/src/glyphs.ts    # -f json, -f sprite
glyphy export -p icons -f animl -o <app>/anim/          # animate with Anima: one .animl per glyph
```

Final SVGs are in `icons/glyphs/`. Tell the user which variant you chose for
each glyph and why, with its numbers, and point them to the sheet and inspect
images. When wiring glyphs into an app, check them in place: CSS such as
`svg { fill: none }` in a base stylesheet overrides the `fill` attribute, so give
the icon class `fill: currentColor` explicitly.

## Power users

Every rule and knob is in `glyphy.toml` and can be set globally (`glyphy set
section.key=value`), per glyph (`glyphs.<name>.<key>`), for one run (`--set`
on trace, brief and check), pinned against measurement (`--lock`), or driven
from Python (`glyphy.vector`, `glyphy.vtrace.stages`). The older pixel
pipelines are profiles (`--profile classic|refined`); `trace.hint=true` grid-fits
edges for maximum 16 px crispness. Read the README's configuration section
before inventing a workaround.
