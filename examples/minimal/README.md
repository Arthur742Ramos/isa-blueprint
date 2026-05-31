# Minimal IsabelleBlueprint example

A three-node arithmetic demo. Run from the repo root:

```
isabelle-blueprint check examples/minimal
isabelle-blueprint compat examples/minimal
isabelle-blueprint graph examples/minimal
isabelle-blueprint tasks examples/minimal
isabelle-blueprint web   examples/minimal
isabelle-blueprint report examples/minimal
```

Generated artifacts land in `examples/minimal/build/` and
`examples/minimal/site/`. Both directories are excluded from version control.

If `isabelle` is not on your `PATH`, every node is reported as
**named** (we know the fact-name was claimed, but have not built the
session). With Isabelle available, lemmas that build successfully are
upgraded to **proved** when no `sorry`/oracle dependency is detected.
