"""The generation brief: everything an image model needs, from the measured style."""
from __future__ import annotations

from pathlib import Path

from .config import Project

# Placeholders available to a custom template (brief.template = "my-brief.md"),
# written as Python format fields: {grid}, {stroke_px}, {glyph_list}, ...
CONTEXT_KEYS = [
    "grid", "image_size", "unit_px", "variants", "reference_sheet", "generated_dir",
    "stroke", "stroke_px", "letter_stroke_min", "letter_stroke_max", "live", "live_px",
    "letter_height", "pad_min", "pad_px", "notes", "glyph_list", "default_brief",
]


def context(project: Project, default_brief: str = "") -> dict:
    s, b, grid = project.style, project.brief, project.grid
    px = int(b["image_size"]) / grid
    glyph_list = "\n".join(f"{i}. {name}{' (letterform)' if g.get('kind') == 'letter' else ''}: {g['concept']}"
                            for i, (name, g) in enumerate(project.glyphs.items(), 1))
    return {
        "grid": grid, "image_size": int(b["image_size"]), "unit_px": round(px), "variants": b["variants"],
        "reference_sheet": str(Path(project.paths["out"]) / "reference-sheet.png"), "generated_dir": project.paths["generated"],
        "stroke": s["stroke"], "stroke_px": round(s["stroke"] * px), "letter_stroke_min": s["letter_stroke"][0],
        "letter_stroke_max": s["letter_stroke"][1], "live": s["live"], "live_px": round(s["live"] * px),
        "letter_height": s["letter_height"], "pad_min": s["pad_min"], "pad_px": round(s["pad_min"] * px),
        "notes": b.get("notes", ""), "glyph_list": glyph_list, "default_brief": default_brief,
    }


def write_brief(project: Project) -> str:
    s, b, grid = project.style, project.brief, project.grid
    size = int(b["image_size"])
    px = size / grid
    # Relative paths keep the brief valid wherever the project folder lives.
    sheet = Path(project.paths["out"]) / "reference-sheet.png"
    generated = Path(project.paths["generated"])
    lines = [
        "# Glyph generation brief",
        "",
        "Draw new icon glyphs that match the reference icons exactly in style. A later step",
        "extracts the black ink and traces it, so contrast and clean geometry matter most.",
        "Paths below are relative to the folder that contains glyphy.toml.",
        "",
        "## Reference",
        f"Study this sheet of reference icons first and pass it to the image tool as a reference image if it accepts one:",
        f"{sheet}",
        "",
        f"## Measured style rules ({grid}×{grid} grid, {size}×{size} image, so 1 unit = {px:.0f} px)",
        f"- Uniform stroke: {s['stroke']} units = {s['stroke'] * px:.0f} px. Letterforms may range "
        f"{s['letter_stroke'][0]}–{s['letter_stroke'][1]} units. No thick/thin contrast.",
        f"- Icons fit a {s['live']}×{s['live']} unit live area ({s['live'] * px:.0f} px), centred; "
        f"letterforms are about {s['letter_height']} units tall.",
        f"- Keep at least {s['pad_min']} units ({s['pad_min'] * px:.0f} px) of empty margin on every side.",
        "- Match the references' stroke ends, corner treatment, proportions and level of detail.",
        f"- Readable at {grid} px: no detail or gap smaller than 1 unit.",
        "",
        "## Output format (strict)",
        f"- {size}×{size} PNG, pure white background (#FFFFFF), pure black ink (#000000).",
        "- No grey, shadows, gradients, texture, colour, frames, labels or grid lines.",
        f"- One glyph per image, centred. {b['variants']} variants per glyph (different interpretations).",
        f"- Save as {generated}/<name>-<n>.png with n = 1..{b['variants']}.",
    ]
    if b.get("notes"):
        lines += ["", "## Notes", b["notes"]]
    lines += ["", "## Glyphs (name: concept)"]
    for i, (name, g) in enumerate(project.glyphs.items(), 1):
        kind = " (letterform)" if g.get("kind") == "letter" else ""
        lines.append(f"{i}. {name}{kind}: {g['concept']}")
    lines += ["", "When done, list the saved files and any rule a variant breaks."]
    text = "\n".join(lines) + "\n"
    if b.get("template"):
        template = Path(b["template"])
        template = template if template.is_absolute() else project.root / template
        # A custom template replaces the default; {default_brief} embeds it if wanted.
        text = template.read_text().format(**context(project, text))
    out = project.path("out")
    out.mkdir(parents=True, exist_ok=True)
    (out / "brief.md").write_text(text)
    return text
