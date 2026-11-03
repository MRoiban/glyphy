---
name: glyphy
description: Create custom icon glyphs that match an existing icon style (Codicons, Lucide, a product's own set) and verify them by measurement with Glyphy. Covers measuring the reference style, producing drafts (delegated to an image model, or drafted as SVG on the icon grid), tracing and correcting them, and reviewing them against the references. Use when asked for new icons "in the same style", for concepts an icon set lacks, or to check that icons match a style.
---

# Glyphy (Claude 5.5 family)

Glyphy makes new icons match an existing set and proves it. It learns the
style's rules from reference icons (stroke width, live area, padding, pixel
crispness, letterform weight), then takes rough drafts and turns them into
SVGs that obey those rules, measuring each result with the same code it used on
the references. Your job is the judgement around it: picking good references,
checking the measured rules make sense, producing drafts, and deciding which
results actually read well. A glyph is finished when it passes **and** looks
right beside its neighbours at the native size.

Run Glyphy with `uvx --from git+https://github.com/MRoiban/glyphy glyphy <command>`
(or `glyphy` if installed). Every command takes `-p <project folder>`;
`glyphy status -p <folder>` tells you where things stand.

## 1. Gather the inputs

- **Reference icons** (needed): 10–40 SVGs (PNG works too) from the target set,
  one per file, on the same grid. The references *are* the style, so choose
  ones typical of it: outline icons for an outline set, and a few letterforms
  (B, I, a numeral) if you will make letters or symbols. A couple of filled or
  unusual icons are fine; medians absorb them.
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
| `pad_min` | smallest margin allowed | 0.75 |
| `letter_height` | letterforms fit a square this tall (whole units) | 12 |
| `crisp_reference` | share of solid pixels at native size | 0.6 |
| `roughness_reference` | outline wobble of the roughest reference (report only) | 0.24 |

`centring_max` (0.5) and `roughness_max` (0 = report only) are rules you set,
not measured.

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
the first: the default pipeline is tuned on image-model drafts, and it is what
made the example glyphs.

**A. Delegate to an image-capable agent or tool.** If you can start a
sub-agent on a model with image generation (for example GPT-6 on Codex) or the
user has an image tool, hand over `out/brief.md` verbatim together with the
absolute path of `out/reference-sheet.png`, and ask for files at
`generated/<name>-<n>.png`. Ask it to report deviations, not to fix them; Glyphy fixes
stroke, size and position itself. Two variants per glyph gives you a choice.

**B. Draft SVG on the grid yourself.** You write precise SVG well, and Glyphy
treats SVG drafts exactly like images. For each glyph, write
`generated/<name>-<n>.svg` with `viewBox="0 0 <grid> <grid>"`:
- Draw with `stroke="#000" stroke-width="<style.stroke>" fill="none"` and
  `stroke-linecap`/`stroke-linejoin` matching what you see in the references,
  or as filled outlines. Black on white only.
- Put straight edges on whole or half units so a 1-unit stroke covers whole
  pixels: a horizontal 1-unit line belongs at `y = n + 0.5`.
- Stay inside the live area (`live` × `live`, centred) and keep `pad_min` margin.
- Keep it to what reads at native size: about `grid − 2` pixels across.
Then trace them like any draft. They are taken as drawn (`trace.svg_as_drawn`):
Glyphy converts strokes into the filled-path form icon sets use and measures
them, without refitting or correcting. For SVGs that are already final, use
`glyphy check -p icons <files>` instead (it exits 1 if any fails).

## 5. Trace, measure, review

```
glyphy trace -p icons
glyphy sheet -p icons
```

`trace` prints PASS/FAIL per draft with stroke (raw → corrected), box, padding
and crispness; `out/report.json` has every number. Then view `out/sheet.png`:
draft, traced glyph large, traced glyph at native size, the reference it
replaces, and the numbers. Judge the native-size column. Measurements tell you
a glyph follows the rules; only looking tells you it communicates its concept
and sits comfortably beside the references. Common problems and remedies:

- **Grey, blurry edges** (low crispness on a straight shape). Re-trace with more
  offsets (`--set trace.offsets=8`), or for letters force the outline stroke
  (`glyphy set glyphs.<name>.stroke_target=1.0`) so edges can land on pixels.
- **Too heavy or too light after correction**: check the draft's raw stroke. A
  very heavy draft thinned a lot can leave stubs. Regenerate or redraw rather
  than over-correct.
- **Too small or oddly placed**: per-glyph `box=[w,h]` sets the target box;
  `fit=false` keeps the draft's own geometry.
- **Lumpy curves or teeth on curves**: `glyphs.<name>.snap_mode="edges"` snaps
  only straight axis edges; `glyphs.<name>.snap=0` turns snapping off; a higher
  `alphamax` gives smoother potrace curves.
- **Wobbly outline from a noisy draft** (high `rough` in the report, compared
  with `style.roughness_reference`): `glyphs.<name>.smooth=0.08` irons it out
  before tracing, or regenerate the draft.

The defaults are tuned; change one glyph's settings to fix a defect you can name,
not the global ones.

Change one thing at a time and re-run `glyphy trace -p icons --only <name>`.
`glyphy config -p icons --glyph <name>` shows the exact settings in effect.

## 6. Choose and deliver

```
glyphy pick -p icons --best            # passing + crispest + best centred per glyph
glyphy pick -p icons heading=2         # or choose by eye
glyphy export -p icons -f ts -o <app>/src/glyphs.ts    # -f json, -f sprite
```

Final SVGs are in `icons/glyphs/`. Tell the user which variant you chose for
each glyph and why, with its numbers, and point them to `out/sheet.png`. When
wiring glyphs into an app, check them in place: CSS such as `svg { fill: none }`
in a base stylesheet overrides the `fill` attribute, so give the icon class
`fill: currentColor` explicitly.

## Power users

Every rule and knob is in `glyphy.toml` and can be set globally (`glyphy set
section.key=value`), per glyph (`glyphs.<name>.<key>`), for one run (`--set`
on trace, brief and check), pinned against measurement (`--lock`), or driven
from Python (`from glyphy import load, trace_file, check_svg`). A custom brief
template is `brief.template`. Read the README's configuration section before
inventing a workaround.
