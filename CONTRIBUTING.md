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
