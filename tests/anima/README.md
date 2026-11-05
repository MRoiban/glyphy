# Anima golden files

Written by the Anima CLI (MRoiban/anima at `61655d2`) for every picked glyph of
`examples/codicon-style`:

```sh
anima new <name> --glyphy examples/codicon-style -o tests/anima/<name>.animl
anima new <name> --glyphy examples/codicon-style --ani -o tests/anima/<name>.ani
```

`glyphy export -f animl` and `-f ani` must reproduce them byte for byte
(`test_anima_export_matches_the_anima_cli`), so a Glyphy export and an Anima
scaffold of the same glyph are the same file.
