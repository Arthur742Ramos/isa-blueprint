# Contributing to IsabelleBlueprint

Thanks for helping make IsabelleBlueprint better for Isabelle/HOL projects.

## Development setup

Use Python 3.11 or newer. From a fresh checkout:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

If you work on the VS Code extension, also install its dependencies:

```bash
cd vscode
npm ci
```

## Quality gates

Run the same checks that CI runs before opening a pull request:

```bash
python -m ruff check .
python -m ruff format --check .
python -m mypy isabelle_blueprint
python -m pytest tests/ -q
```

Use `python -m ruff format .` to apply the canonical Python formatting before
re-running the check. The coverage job also exercises branch coverage and emits
`coverage.xml`; reproduce its threshold locally with:

```bash
python -m pytest tests/ --cov=isabelle_blueprint --cov-branch \
  --cov-report=term-missing --cov-report=xml:coverage.xml --cov-fail-under=87
```

For the extension:

```bash
cd vscode
npm run compile
```

## Isabelle verification coverage

The package CI runs unit tests, a built-wheel CLI suite, and example smoke checks.
It does not install Isabelle: the smoke `check` and `compat` commands exercise
graceful degradation when the executable is missing. Passing package CI does
not certify any example or downstream formalization with Isabelle's kernel.

The separate `Isabelle kernel` job installs checksum-pinned Isabelle2025-2 on
a hosted Linux runner. Its small fixture checks a complete proof (`proved`),
`sorry` (`tainted`), a missing fact (`not_found`, with other facts unverified),
and failed/missing status exports. It also edits source, ML, ROOT metadata,
and settings to exercise cache invalidation, including a source edit followed
by an independent session rebuild. These fixtures validate the integration;
each downstream project still needs its own successful build.

For a real verification run, install the project's configured Isabelle release
and session dependencies, then run:

```bash
isabelle-blueprint compat PATH_TO_PROJECT
isabelle-blueprint check PATH_TO_PROJECT
```

Inspect `build/check_report.json`: a fresh successful build has `ran: true`,
`isabelle_available: true`, `return_code: 0`, and a populated `invoked_command`.
With proof-status checking enabled, each trusted fact must also have
`proof_status: "proved"` and no oracles. Use a non-incremental run for fresh
evidence; `--incremental` may reuse earlier proof records without a new build.
Incremental reuse requires a successful native Isabelle dependency query and
matching source/configuration digests for all referenced sessions and their
imports, plus installation/settings identity. A missing executable or failed
query disables Python cache reuse. On unsupported Isabelle Scala APIs the
normal check still runs, using Isabelle's own build cache.
Each uncached proof-status check refreshes the wrapper and removes the previous
TSV before building. Missing or contradictory export records never justify
`proved`; a successful existence check without valid proof evidence is `found`.
A failed build leaves facts whose existence was not determined `named`; only
explicit missing-fact diagnostics justify `not_found`.

This wrapper verifies blueprint fact references. AFP readiness additionally
requires building the complete entry, including its document, with the target
Isabelle/AFP release and checking AFP packaging requirements.

## Releases

To publish a new release, update both version declarations in the same commit:

- `pyproject.toml` `[project].version`
- `isabelle_blueprint/__init__.py` `__version__`

When that commit reaches `main`, the `publish` workflow detects the
`pyproject.toml` version change, runs the release quality gates, creates the
matching `vX.Y.Z` tag with `GITHUB_TOKEN`, publishes to PyPI through the `pypi`
trusted-publishing environment, and creates or updates the GitHub Release with
the built distributions.

Manual `vX.Y.Z` tag pushes are still supported, but the tag version must match
`pyproject.toml`. The PyPI trusted publisher must allow this repository's
`.github/workflows/publish.yml` workflow and the `pypi` environment.

## Compatibility expectations

The v1.0 CLI surface, generated JSON file shapes, and GitHub Action output keys
are frozen public contracts. Additive improvements are welcome, but avoid
renaming commands, changing default behavior, removing fields, or changing the
meaning of existing report outputs without planning a 2.0 change.

When in doubt, prefer an opt-in flag, a new output field, or a new file over a
breaking change to an existing contract.

## Pull requests

Please keep pull requests focused and include:

- A short explanation of the user-visible change.
- Tests or fixtures for behavior changes.
- Confirmation that ruff, mypy, and pytest pass locally.
- Notes for any intentional compatibility impact.
