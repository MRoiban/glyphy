"""Picking final glyphs and exporting them for an app."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

from .config import Project


def pick(project: Project, choices: dict[str, str] | None = None, best: bool = False) -> dict:
    """Copy chosen variants to the picked directory. `best` picks the passing, most crisp variant."""
    report = json.loads((project.path("out") / "report.json").read_text())
    traced = project.path("traced")
    chosen = dict(project.picks)
    if best:
        by_glyph: dict[str, tuple] = {}
        for stem, r in report.items():
            if "error" in r or not (traced / f"{stem}.svg").exists():
                continue
            score = (r["ok"], r.get("crisp", 0))
            name = r.get("glyph", stem)
            if name not in by_glyph or score > by_glyph[name][0]:
                by_glyph[name] = (score, stem)
        chosen.update({name: stem for name, (_, stem) in by_glyph.items()})
    for name, variant in (choices or {}).items():
        chosen[name] = variant if variant.startswith(name) else f"{name}-{variant}"
    dst = project.path("picked")
    dst.mkdir(parents=True, exist_ok=True)
    for name, stem in chosen.items():
        source = traced / f"{stem}.svg"
        if not source.exists():
            raise SystemExit(f"{source} does not exist; run `glyphy trace` first.")
        shutil.copy(source, dst / f"{name}.svg")
    project.picks = chosen
    project.save()
    return chosen


def _paths(project: Project) -> dict[str, str]:
    out = {}
    for svg in sorted(project.path("picked").glob("*.svg")):
        d = re.search(r'\sd="([^"]+)"', svg.read_text())
        if d:
            out[svg.stem] = d.group(1)
    return out


def _number(v):
    # Anima writes JSON numbers the JavaScript way: 1.0 is 1.
    return int(v) if isinstance(v, float) and v.is_integer() else v


def anima_document(project: Project, name: str, d: str) -> dict:
    """A static Anima (.ani) document whose rest frame is the glyph, with Glyphy's metadata.

    Mirrors `anima new <name> --glyphy <project>` key for key, so a Glyphy export and an Anima
    scaffold of the same glyph are the same file.
    """
    info = project.glyphs.get(name, {})
    glyphy = {k: info[k] for k in ("concept", "kind") if info.get(k)}
    if project.style.get("stroke"):
        glyphy["stroke"] = _number(project.style["stroke"])
    glyph = {"source": "glyphy"}
    if project.picks.get(name):
        glyph["pick"] = project.picks[name]
    glyph["sha256"] = hashlib.sha256(d.encode()).hexdigest()
    glyph["d"] = d
    return {
        "anima": "0.1",
        "name": name,
        "title": (name.replace("-", " ")[:1].upper() + name.replace("-", " ")[1:]),
        "grid": project.grid,
        "meta": {"glyphy": glyphy},
        "colors": {"ink": "currentColor"},
        "glyphs": {name: glyph},
        "nodes": [{"id": "glyph", "type": "path", "glyph": name, "fill": {"color": "ink", "rule": "evenodd"}}],
    }


def _attr(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")


def anima_markup(doc: dict) -> str:
    """The same document as AniML (.animl), in the layout `anima fmt` produces."""
    name = doc["name"]
    glyph = doc["glyphs"][name]
    meta = json.dumps(doc["meta"], separators=(",", ":"), ensure_ascii=False)

    def element(tag: str, attrs: list[tuple[str, str]], indent: str = "  ") -> str:
        # `anima fmt` puts a value longer than 80 characters on its own continuation line, and
        # the attribute after it on the next one.
        out, continuation = f"{indent}<{tag}", False
        for key, value in attrs:
            long = len(value) > 80
            out += (f"\n{indent}    " if long or continuation else " ") + f'{key}="{_attr(value)}"'
            continuation = long
        return out + "/>"

    glyph_attrs = [("name", name), ("d", glyph["d"]), ("source", glyph["source"])]
    glyph_attrs += [(k, glyph[k]) for k in ("pick", "sha256") if k in glyph]
    head = element("anima", [("version", doc["anima"]), ("name", name), ("title", doc["title"]),
                             ("grid", str(doc["grid"]))], "")[:-2] + ">"
    meta_text = meta.replace("&", "&amp;").replace("<", "&lt;")
    return "\n".join([
        head,
        f"  <meta>{meta_text}</meta>",
        "",
        element("color", [("name", "ink"), ("value", "currentColor")]),
        "",
        element("glyph", glyph_attrs),
        "",
        element("path", [("id", "glyph"), ("glyph", name), ("fill", "ink"), ("fill-rule", "evenodd")]),
        "</anima>",
        "",
    ])


def export(project: Project, fmt: str, target: Path) -> Path:
    paths, grid = _paths(project), project.grid
    if fmt in ("ani", "animl"):
        # One Anima document per glyph: the target is a directory.
        target.mkdir(parents=True, exist_ok=True)
        for name, d in paths.items():
            doc = anima_document(project, name, d)
            text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n" if fmt == "ani" else anima_markup(doc)
            (target / f"{name}.{fmt}").write_text(text)
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        target.write_text(json.dumps({"grid": grid, "glyphs": paths}, indent=1))
    elif fmt == "ts":
        lines = ["// Generated by glyphy. Each glyph is one even-odd path on the grid below.",
                 f"export const GLYPH_GRID = {grid};", "export const GLYPH_PATHS = {",
                 *[f'  "{name}": "{d}",' for name, d in paths.items()], "} as const;",
                 "export type GlyphName = keyof typeof GLYPH_PATHS;", ""]
        target.write_text("\n".join(lines))
    elif fmt == "sprite":
        symbols = "".join(f'<symbol id="{name}" viewBox="0 0 {grid} {grid}"><path fill-rule="evenodd" d="{d}"/></symbol>'
                          for name, d in paths.items())
        target.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" style="display:none">{symbols}</svg>\n')
    else:
        raise SystemExit(f"Unknown format {fmt!r}; use ts, json, sprite, ani or animl.")
    return target
