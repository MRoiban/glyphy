---
name: glyphy
description: Create custom icon glyphs that match an existing icon style (for example Codicons, Lucide, or a product's own set), using built-in image generation for drafts and Glyphy to trace them into clean vectors, correct their stroke weight and verify them by measurement. Use when asked for new icons/glyphs "in the same style", for concepts an icon set lacks, or to check that icons match a reference style.
---

# Glyphy (GPT-6 family)

You make icons that match a reference style. You draw drafts with your image
generation tool; Glyphy traces each draft faithfully, rebuilds it from exact
lines and smooth curves, corrects the stroke weight and fits it to the icon
grid, then measures it against the reference icons. A glyph is done when
`glyphy trace` reports PASS **and** its `glyphy inspect` image shows the final
outline sitting on the drawing at full size.

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
   - One glyph per image, pure black on pure white, at the brief's size, large
     in the frame. Clean edges matter more than exact stroke width: Glyphy
     corrects the weight, but it keeps the shape you draw.
   - Save each image as `icons/generated/<name>-<n>.png` (n = 1, 2, …). Copy
     files there if the tool saves elsewhere; the name must match `glyphy add`.
4. Trace: `glyphy trace -p icons`. Every draft gets PASS/FAIL with stroke, box,
   padding, crispness, `vector` (how much of the draft's outline the clean
   vector matches; expect 99%+) and its segment count.
5. Look at full size: `glyphy inspect -p icons <name>-<n>` writes
   `icons/out/inspect/<name>-<n>.png`. Top: the faithful trace (grey) against
   the clean vector (green; red where they differ by more than 0.03 units).
   Middle: the final glyph mapped back onto the draft (red where it moved
   beyond the intended stroke change; mitred tips extend a little by design).
   Then `glyphy sheet -p icons` for all glyphs side by side with the icons they
   replace. Reject variants that pass but read badly.
6. Fix what fails or reads badly, cheapest first:
   - Regenerate the draft with a sharper prompt (name the problem: "simpler",
     "more margin", "straighter lines").
   - A corner missed or invented: `glyphy set -p icons glyphs.<name>.corner_deg=25` (lower finds more corners).
   - A slightly curved line kept curved: raise `glyphs.<name>.line_tol`; a curve flattened: lower `curve_tol`.
   - Force a stroke: `glyphs.<name>.stroke_target=1.0`; a box: `glyphs.<name>.box=[12,14]`.
   - Re-trace only that glyph: `glyphy trace -p icons --only <name>`.
7. Choose and export:
   ```
   glyphy pick -p icons --best          # or: glyphy pick -p icons moon=2 heading=1
   glyphy export -p icons -f ts -o <app>/src/glyphs.ts    # or -f json / -f sprite
   ```
   Final SVGs are in `icons/glyphs/`. Report each glyph's numbers, the sheet and
   the inspect images.

## Rules of thumb

- Judge glyphs at full size (`inspect`), not at 16 px: small renders hide hooks,
  bevels and wobble that show everywhere else.
- `crisp` (16 px) and `crisp_2x` (32 px) are information. `trace.hint=true`
  raises them a little by moving edges onto pixel lines; it is off by default
  because it moves outlines off the drawing.
- Letterforms fit a `letter_height` square and are corrected towards
  `style.letter_stroke_target`, the references' typical letter weight.
- Keep concepts simple enough for the native size: at 16 px a glyph has about
  14 pixels across. Prefer one strong shape over several small ones.
- `glyphy config -p icons --glyph <name>` shows exactly what tracing will use.
