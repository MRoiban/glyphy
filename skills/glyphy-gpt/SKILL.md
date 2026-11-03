---
name: glyphy
description: Create custom icon glyphs that match an existing icon style (for example Codicons, Lucide, or a product's own set), using built-in image generation for drafts and Glyphy to trace, correct and verify them by measurement. Use when asked for new icons/glyphs "in the same style", for concepts an icon set lacks, or to check that icons match a reference style.
---

# Glyphy (GPT-6 family)

You make icons that match a reference style. You draw drafts with your image
generation tool; Glyphy turns them into SVGs and proves they match by
measuring them against the reference icons. Never judge a glyph by eye alone:
a glyph is done when `glyphy trace` reports PASS **and** the contact sheet reads well.

Run Glyphy with `uvx --from git+https://github.com/MRoiban/glyphy glyphy <command>`
(or `glyphy` if installed). Every command takes `-p <project folder>`.
`glyphy status -p <folder>` prints what is done and the next step.

## Inputs to get from the user

1. **Reference icons**: 10–40 SVG (preferred) or PNG files from the target set,
   one icon per file, same grid. Include a few letterforms (B, I, a numeral)
   if any requested glyph is a letter or symbol.
2. **Grid size**: units per side (Codicons 16, Lucide/Material 24). Ask if unknown.
3. **Glyph list**: a name and a one-line visual concept for each, and whether it
   is a letterform (`--kind letter`). Optionally which existing icon it replaces.

If the user gives no references, ask for them. Do not invent a style.

## Procedure

1. Set up and measure:
   ```
   glyphy init -p icons -r <reference files or folder> --grid 16
   ```
   Read the printed rules. Open `icons/out/baseline.json` if a value looks
   wrong (for example a stroke of 2.3 on a thin-line set means a few filled
   icons skewed it). Fix wrong values with `glyphy set -p icons style.stroke=1.0 --lock`.
2. Describe the glyphs, one command each:
   ```
   glyphy add -p icons moon "a crescent moon" --replaces color-mode
   glyphy add -p icons heading 'a geometric sans-serif capital "H"' --kind letter
   ```
3. Write the brief: `glyphy brief -p icons`. Then generate drafts with your
   image tool, following `icons/out/brief.md` exactly:
   - Pass `icons/out/reference-sheet.png` as a reference image.
   - One glyph per image, pure black on pure white, at the brief's size.
   - Save each image as `icons/generated/<name>-<n>.png` (n = 1, 2, …). Copy
     files there if the tool saves elsewhere; the name must match `glyphy add`.
4. Trace and measure: `glyphy trace -p icons`. Every draft gets PASS/FAIL with
   stroke, box, padding and crispness.
5. Look: `glyphy sheet -p icons`, then open `icons/out/sheet.png`. Check each
   glyph at native size (third column) beside its reference. Reject variants
   that pass but read badly (lumpy curves, merged details, unclear concept).
6. Fix what fails or reads badly, cheapest first:
   - Regenerate the draft with a sharper prompt (name the problem: "thinner",
     "more margin", "simpler: no inner detail").
   - Override one glyph: `glyphy set -p icons glyphs.<name>.stroke_target=1.0`,
     `glyphs.<name>.box=[12,14]`, `glyphs.<name>.correct=false`, `glyphs.<name>.alphamax=1.1`.
   - Re-trace only that glyph: `glyphy trace -p icons --only <name>`.
7. Choose and export:
   ```
   glyphy pick -p icons --best          # or: glyphy pick -p icons moon=2 heading=1
   glyphy export -p icons -f ts -o <app>/src/glyphs.ts    # or -f json / -f sprite
   ```
   Final SVGs are in `icons/glyphs/`. Report each glyph's numbers and the sheet path.

## Rules of thumb

- Crispness below the reference value (`style.crisp_reference`) means edges
  fall between pixels. Straight shapes should reach it; curves and diagonals
  sit lower, as in the references.
- Letterforms keep their weight inside `style.letter_stroke`. To force pixel-
  crisp letters, set `glyphs.<name>.stroke_target` to the outline stroke.
- Keep concepts simple enough for the native size: at 16 px a glyph has about
  14 pixels across. Prefer one strong shape over several small ones.
- `glyphy config -p icons --glyph <name>` shows exactly what tracing will use.
- One-off experiments: `glyphy trace --only <name> --set trace.offsets=8` (not saved).
