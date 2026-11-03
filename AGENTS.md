# Working on Glyphy

Glyphy measures a reference icon style and turns image-model drafts into SVG
glyphs that obey it. Read `README.md` for the workflow and configuration. The
skills in `skills/` are for agents *using* Glyphy; this file is for agents
changing it.

## Commands

```sh
uv venv && uv pip install -e '.[test]'
.venv/bin/python -m pytest -q          # must pass before reporting work done
.venv/bin/glyphy status -p examples/codicon-style
.venv/bin/glyphy trace -p examples/codicon-style && .venv/bin/glyphy sheet -p examples/codicon-style
```

The default settings are the pipeline that made Typewriter's glyphs, and the
example pins them: `test_defaults_reproduce_the_example` retraces drafts and
expects the committed glyphs pixel for pixel. A new idea goes in behind a
setting that is off by default; change a default only when the example's sheet
(`examples/codicon-style/out/sheet.png`) is visibly better and the numbers
agree, then regenerate and commit the example with the change.

## Code map

| Path | What it owns |
|---|---|
| `src/glyphy/raster.py` | SVG/PNG → boolean ink masks (Cairo), file discovery |
| `src/glyphy/metrics.py` | `Metrics` and `measure`: stroke (skeleton × distance transform), box, padding, centring; `crispness`, `roughness` |
| `src/glyphy/config.py` | Defaults, `glyphy.toml` load/save, `Project.settings(glyph)` merging, `apply_setting` |
| `src/glyphy/style.py` | Reference measurement → `[style]` rules (respects `locked`), baseline and reference sheet |
| `src/glyphy/brief.py` | The generation brief and the custom-template context |
| `src/glyphy/trace.py` | Ink mask → fit → stroke correction → potrace → snap → offset search → check |
| `src/glyphy/outline.py` | `stroke_shape = "mitre"`: outline offsetting with shapely, exact one-step fit |
| `src/glyphy/fidelity.py` | Centreline drift from the draft, stroke spread |
| `src/glyphy/sheet.py` | Contact sheet |
| `src/glyphy/export.py` | Picking and export (TypeScript, JSON, SVG sprite) |
| `src/glyphy/cli.py` | The `glyphy` command; every subcommand is a thin wrapper over the modules |

## Rules

- References and results are measured by the same code. Never add a check that
  measures traced glyphs differently from references.
- Every number the pipeline uses comes from `Project.settings()`, so any of it
  can be overridden globally, per glyph or for one run. Do not hard-code a
  threshold in a function; add a key to `DEFAULT_STYLE`/`DEFAULT_TRACE` and
  document it in the README's configuration table.
- New CLI behaviour must also be reachable from Python (public functions).
- `glyphy measure` must not overwrite keys listed in `style.locked`.
- Profiles (`config.PROFILES`) are plain bundles of settings. Judge a tracing change
  by the profile comparison in the README: rerun both profiles on the example and
  update the table.
- Keep the skills in `skills/` in step with the CLI: a renamed flag or key
  must be renamed there too.
- Comments explain why, not what.
