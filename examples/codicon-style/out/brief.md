# Glyph generation brief

Draw new icon glyphs that match the reference icons exactly in style. A later step
extracts the black ink and traces it, so contrast and clean geometry matter most.
Paths below are relative to the folder that contains glyphy.toml.

## Reference
Study this sheet of reference icons first and pass it to the image tool as a reference image if it accepts one:
out/reference-sheet.png

## Measured style rules (16×16 grid, 1024×1024 image, so 1 unit = 64 px)
- Uniform stroke: 1.0 units = 64 px. Letterforms may range 0.95–1.45 units. No thick/thin contrast.
- Icons fit a 14.0×14.0 unit live area (896 px), centred; letterforms are about 11.91 units tall.
- Keep at least 0.75 units (48 px) of empty margin on every side.
- Match the references' stroke ends, corner treatment, proportions and level of detail.
- Readable at 16 px: no detail or gap smaller than 1 unit.

## Output format (strict)
- 1024×1024 PNG, pure white background (#FFFFFF), pure black ink (#000000).
- No grey, shadows, gradients, texture, colour, frames, labels or grid lines.
- One glyph per image, centred. 2 variants per glyph (different interpretations).
- Save as generated/<name>-<n>.png with n = 1..2.

## Glyphs (name: concept)
1. heading (letterform): a geometric sans-serif capital "H"
2. math-inline (letterform): an italic lowercase "x" with a small superscript "2"
3. math-display (letterform): a capital sigma between a line above and a line below
4. comment-toggle (letterform): two forward slashes followed by a short horizontal line
5. follow-cursor: a text I-beam cursor inside four corner brackets
6. section (letterform): the section sign §
7. theme-light: a sun: a circle with 8 short rays
8. theme-dark: a crescent moon
9. dark-pages: a page outline with a folded corner whose lower-right half is solid
10. main-file: a page outline with a folded corner and a small solid star inside
11. typst-file: a page outline with a folded corner and a lowercase "t" inside

When done, list the saved files and any rule a variant breaks.
