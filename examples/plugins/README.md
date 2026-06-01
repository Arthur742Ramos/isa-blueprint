# Plugin examples

This directory shows the smallest useful third-party plugin shape for the
experimental IsabelleBlueprint entry-point hooks.

```toml
[project.entry-points."isabelle_blueprint.status_providers"]
review-tags = "review_tags_plugin:status_annotations"
```

When installed in the same Python environment as `isabelle-blueprint`, the
sample provider emits a warning annotation for every node tagged `needs-review`.
Those annotations are collected by `isabelle-blueprint report` into
`build/plugin-annotations.json` without affecting built-in reports.

