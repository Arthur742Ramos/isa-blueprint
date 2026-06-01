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
python -m mypy isabelle_blueprint
python -m pytest tests/ -q
```

For the extension:

```bash
cd vscode
npm run compile
```

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

