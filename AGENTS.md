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

After changing measurement or tracing, re-run the example and look at
`examples/codicon-style/out/sheet.png`: all 11 glyphs should still pass, and
the native-size column should still look crisp. Commit the regenerated example
outputs together with the change.

## Code map

| Path | What it owns |
|---|---|
| `src/glyphy/raster.py` | SVG/PNG → boolean ink masks (Cairo), file discovery |
| `src/glyphy/metrics.py` | `Metrics` and `measure`: stroke (skeleton × distance transform), box, padding, centring, crispness |
| `src/glyphy/config.py` | Defaults, `glyphy.toml` load/save, `Project.settings(glyph)` merging, `apply_setting` |
| `src/glyphy/style.py` | Reference measurement → `[style]` rules (respects `locked`), baseline and reference sheet |
| `src/glyphy/brief.py` | The generation brief and the custom-template context |
| `src/glyphy/trace.py` | Ink mask → fit → stroke correction → potrace → snap → offset search → check |
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
- Keep the skills in `skills/` in step with the CLI: a renamed flag or key
  must be renamed there too.
- Comments explain why, not what.
