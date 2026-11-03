"""glyphy command line. Run `glyphy status` at any point to see the next step."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import __version__
from .config import FILE, Project, apply_setting, load
from .raster import glyph_files


def cmd_init(args) -> None:
    root = Path(args.project).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if (root / FILE).exists() and not args.force:
        raise SystemExit(f"{root / FILE} already exists (use --force to overwrite).")
    project = Project(root=root)
    project.style["grid"] = args.grid
    for key in ["reference", "generated", "traced", "picked", "out"]:
        project.path(key).mkdir(parents=True, exist_ok=True)
    copied = 0
    for source in args.reference or []:
        source = Path(source)
        files = glyph_files(source) if source.is_dir() else [source]
        for file in files:
            shutil.copy(file, project.path("reference") / file.name)
            copied += 1
    project.save()
    print(f"Created {root / FILE} with {copied} reference icon(s) in {project.path('reference')}.")
    if copied:
        cmd_measure(argparse.Namespace(project=str(root), json=False))
    else:
        print("Add reference icons to the reference folder, then run `glyphy measure`.")


def cmd_measure(args) -> None:
    from .style import measure_references
    project = load(args.project)
    baseline = measure_references(project)
    project.save()
    if args.json:
        print(json.dumps({k: v for k, v in baseline.items() if k != "icons_measured"}, indent=1))
        return
    s = project.style
    print(f"Measured {baseline['icons']} reference icons on a {project.grid}-unit grid:")
    print(f"  stroke        {s['stroke']} units (p10–p90 {baseline['stroke']['p10']}–{baseline['stroke']['p90']})")
    print(f"  letter stroke {s['letter_stroke'][0]}–{s['letter_stroke'][1]} units ({baseline['letterforms']['count']} letterforms found)")
    print(f"  letter target {s['letter_stroke_target']} units, letter height {s['letter_height']}")
    print(f"  live area     {s['live']} × {s['live']} units, min padding {s['pad_min']}")
    if baseline.get("crispness"):
        print(f"  crispness     {s['crisp_reference']} (share of solid pixels at {project.grid} px)")
        print(f"  roughness     {s['roughness_reference']} wobbles per unit of outline (roughest reference)")
    print(f"Wrote {project.path('out') / 'baseline.json'} and reference-sheet.png; rules saved in {FILE}.")


def cmd_add(args) -> None:
    project = load(args.project)
    entry = {"concept": args.concept, "kind": args.kind}
    if args.replaces:
        entry["replaces"] = args.replaces
    project.glyphs[args.name] = entry
    project.save()
    print(f"Added {args.name} ({args.kind}): {args.concept}")


def overrides(project: Project, assignments: list[str] | None) -> dict:
    """One-off key=value overrides for this run only (not saved)."""
    flat: dict = {}
    for assignment in assignments or []:
        key, value = apply_setting(project, assignment)
        # glyphs.<name>.<key> is already applied to that glyph alone.
        if not key.startswith("glyphs."):
            flat[key.split(".")[-1]] = value
    return flat


def cmd_set(args) -> None:
    project = load(args.project)
    for assignment in args.assignments:
        key, value = apply_setting(project, assignment)
        bare = key.split(".")[-1]
        if args.lock and (key.startswith("style.") or bare in project.style) and bare not in project.style["locked"]:
            project.style["locked"].append(bare)
        print(f"{key} = {value!r}{' (locked)' if args.lock else ''}")
    project.save()


def cmd_config(args) -> None:
    project = load(args.project)
    if args.glyph:
        print(json.dumps(project.settings(args.glyph), indent=1))
    else:
        print(json.dumps({"style": project.style, "trace": project.trace, "brief": project.brief,
                          "paths": project.paths, "glyphs": project.glyphs, "picks": project.picks}, indent=1))


def cmd_brief(args) -> None:
    from .brief import write_brief
    project = load(args.project)
    overrides(project, args.set)
    if not project.glyphs:
        raise SystemExit("No glyphs yet. Add some with `glyphy add <name> \"<concept>\"`.")
    text = write_brief(project)
    print(text if args.print else f"Wrote {project.path('out') / 'brief.md'}. Give it to an image model; drafts go in {project.path('generated')}.")


def cmd_trace(args) -> None:
    from .trace import trace_all
    project = load(args.project)
    extra = overrides(project, args.set)
    if args.offsets is not None:
        extra["offsets"] = args.offsets
    report = trace_all(project, args.only, extra)
    if args.json:
        print(json.dumps(report, indent=1))
        return
    for stem, r in sorted(report.items()):
        if "error" in r:
            print(f"{stem:24} ERROR {r['error']}")
            continue
        print(f"{stem:24} {'PASS' if r['ok'] else 'FAIL'}  stroke {r['raw_stroke']:.2f}→{r['stroke']:.2f} (target {r['stroke_target']:.2f})"
              f"  box {r['box'][0]:.1f}×{r['box'][1]:.1f}  pad {r['min_pad']:.2f}  crisp {r['crisp']:.2f}/{r.get('crisp_2x', 0):.2f}"
              f"  rough {r.get('roughness', 0):.2f}{'' if r.get('roughness_ok', True) else ' (too rough)'}")
    passed = sum(1 for r in report.values() if r.get("ok"))
    print(f"{passed}/{len(report)} pass. Next: `glyphy sheet` to look at them, then `glyphy pick`.")


def cmd_check(args) -> None:
    from .trace import check_svg
    project = load(args.project)
    extra = overrides(project, args.set)
    results = {Path(f).name: check_svg(project, Path(f), args.kind, extra) for f in args.files}
    print(json.dumps(results, indent=1))
    if not all(r.get("ok") for r in results.values()):
        sys.exit(1)


def cmd_sheet(args) -> None:
    from .sheet import contact_sheet
    print(f"Wrote {contact_sheet(load(args.project))}")


def cmd_pick(args) -> None:
    from .export import pick
    project = load(args.project)
    choices = dict(c.split("=", 1) for c in args.choices)
    chosen = pick(project, choices, best=args.best)
    for name, stem in chosen.items():
        print(f"{name:20} ← {stem}")
    print(f"Copied to {project.path('picked')}.")


def cmd_export(args) -> None:
    from .export import export
    project = load(args.project)
    print(f"Wrote {export(project, args.format, Path(args.output))}")


def cmd_status(args) -> None:
    project = load(args.project)
    refs = glyph_files(project.path("reference"))
    drafts = glyph_files(project.path("generated"))
    traced = list(project.path("traced").glob("*.svg"))
    measured = (project.path("out") / "baseline.json").exists()
    steps = [
        (bool(refs), f"Add reference icons (SVG/PNG) to {project.path('reference')}"),
        (measured, "Run `glyphy measure` to derive the style rules"),
        (bool(project.glyphs), "Describe glyphs: `glyphy add <name> \"<concept>\" [--kind letter]`"),
        ((project.path("out") / "brief.md").exists(), "Run `glyphy brief`, then generate drafts from out/brief.md"),
        (bool(drafts), f"Save drafts as {project.path('generated')}/<name>-<n>.png"),
        (len(traced) >= len(drafts) > 0, "Run `glyphy trace`, then `glyphy sheet`"),
        (bool(project.picks), "Run `glyphy pick --best` (or name=variant) and `glyphy export`"),
    ]
    print(f"{project.root / FILE}: {len(refs)} references, {len(project.glyphs)} glyphs, {len(drafts)} drafts, {len(traced)} traced, {len(project.picks)} picked")
    for done, text in steps:
        print(f"  [{'x' if done else ' '}] {text}")
    pending = next((text for done, text in steps if not done), None)
    print(f"Next: {pending}" if pending else "Done. Re-run any step after changing inputs.")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="glyphy", description="Icon glyphs that match a reference style, verified by measurement.")
    parser.add_argument("--version", action="version", version=f"glyphy {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def command(name, func, help):
        p = sub.add_parser(name, help=help, description=help)
        p.add_argument("--project", "-p", default=".", help="project folder (default: current folder)")
        p.set_defaults(func=func)
        return p

    p = command("init", cmd_init, "Create glyphy.toml and folders; copy reference icons and measure them.")
    p.add_argument("--reference", "-r", nargs="*", help="reference icon files or folders (SVG/PNG)")
    p.add_argument("--grid", type=int, default=16, help="grid units per side of the icon canvas (default 16)")
    p.add_argument("--force", action="store_true")
    p = command("measure", cmd_measure, "Measure the reference icons and write the style rules.")
    p.add_argument("--json", action="store_true")
    p = command("add", cmd_add, "Add or update a glyph to generate.")
    p.add_argument("name")
    p.add_argument("concept", help="what to draw, e.g. 'a crescent moon'")
    p.add_argument("--kind", choices=["icon", "letter"], default="icon", help="letter: letterform rules (height, stroke range)")
    p.add_argument("--replaces", help="reference icon it replaces, shown beside it on the sheet")
    p = command("brief", cmd_brief, "Write out/brief.md, the prompt for the image model.")
    p.add_argument("--print", action="store_true", help="print the brief instead of only writing it")
    p.add_argument("--set", nargs="*", metavar="KEY=VALUE", help="one-off overrides, e.g. brief.variants=4")
    p = command("trace", cmd_trace, "Vectorise drafts, correct them to the style and measure them.")
    p.add_argument("--only", nargs="*", help="glyph names (or stems) to trace")
    p.add_argument("--offsets", type=int, help="shorthand for --set trace.offsets=N")
    p.add_argument("--set", nargs="*", metavar="KEY=VALUE", help="one-off overrides, e.g. trace.alphamax=1.1 style.stroke=1.5")
    p.add_argument("--json", action="store_true")
    p = command("check", cmd_check, "Measure finished SVGs (e.g. hand-drawn) against the style. Exit 1 if any fails.")
    p.add_argument("files", nargs="+")
    p.add_argument("--kind", choices=["icon", "letter"], help="default: the glyph's kind, else icon")
    p.add_argument("--set", nargs="*", metavar="KEY=VALUE", help="one-off overrides for the check")
    p = command("sheet", cmd_sheet, "Draw out/sheet.png: drafts, traced glyphs at both sizes, references, numbers.")
    p = command("pick", cmd_pick, "Choose final variants: name=2 … or --best.")
    p.add_argument("choices", nargs="*", help="name=variant pairs, e.g. heading=2")
    p.add_argument("--best", action="store_true", help="pick the passing, most crisp variant of each glyph")
    p = command("export", cmd_export, "Export picked glyphs as a TS module, JSON or SVG sprite.")
    p.add_argument("--format", "-f", choices=["ts", "json", "sprite"], default="ts")
    p.add_argument("--output", "-o", required=True)
    command("status", cmd_status, "Show progress and the next step.")
    p = command("set", cmd_set, "Change any setting: style.stroke=1.5, trace.alphamax=1.1, glyphs.heading.kind=letter.")
    p.add_argument("assignments", nargs="+", metavar="KEY=VALUE")
    p.add_argument("--lock", action="store_true", help="also pin style keys so `glyphy measure` keeps them")
    p = command("config", cmd_config, "Print the project settings, or the effective settings for one glyph.")
    p.add_argument("--glyph", help="show style + trace + this glyph's overrides, as tracing will use them")

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
