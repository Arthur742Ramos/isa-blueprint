"""Project templates used by ``isabelle-blueprint init``."""

from __future__ import annotations

from dataclasses import dataclass

from isabelle_blueprint.parser.latex import render_latex_blueprint
from isabelle_blueprint.parser.markdown import parse_blueprint_text


@dataclass(frozen=True)
class ProjectTemplate:
    """Files written by the project initialiser."""

    name: str
    description: str
    blueprint: str
    config: str
    workflow: str


def blueprint_filename(format: str) -> str:
    """Return the default blueprint filename for an authoring format."""
    return "blueprint.tex" if format == "latex" else "blueprint.md"


def render_template_blueprint(template: ProjectTemplate, *, format: str = "markdown") -> str:
    """Render ``template`` in Markdown or LaTeX authoring syntax."""
    if format == "latex":
        project = parse_blueprint_text(
            template.blueprint,
            source=f"{template.name}-template.md",
            project_name=_template_title(template.blueprint),
        )
        return render_latex_blueprint(project)
    return template.blueprint


def render_template_config(template: ProjectTemplate, *, format: str = "markdown") -> str:
    """Render the template config with the matching blueprint filename."""
    if format == "latex":
        return template.config.replace('blueprint = "blueprint.md"', 'blueprint = "blueprint.tex"')
    return template.config


def _template_title(markdown: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return "My blueprint"


_BASE_WORKFLOW = """name: blueprint
on:
  push:
  pull_request:
permissions:
  contents: read
jobs:
  blueprint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10  # v6
      - uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405  # v6
        with:
          python-version: "3.11"
      - run: pip install isabelle-blueprint
      - run: isabelle-blueprint check .
      - run: isabelle-blueprint gate .
      - run: isabelle-blueprint compat .
      - run: isabelle-blueprint graph .
      - run: isabelle-blueprint web .
      - run: isabelle-blueprint report .
      - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a  # v7
        with:
          name: blueprint-site
          path: site
"""

_AGENT_WORKFLOW = """name: blueprint
on:
  push:
  pull_request:
permissions:
  contents: read
jobs:
  blueprint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10  # v6
      - uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405  # v6
        with:
          python-version: "3.11"
      - run: pip install isabelle-blueprint
      - run: isabelle-blueprint check .
      - run: isabelle-blueprint gate .
      - run: isabelle-blueprint tasks . --github-issues
      - run: isabelle-blueprint web .
      - run: isabelle-blueprint report .
      - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a  # v7
        with:
          name: blueprint-agent-pack
          path: |
            build/tasks.json
            build/tasks.md
            build/prompts
            build/github-issues.json
            site
"""

_DEFAULT_CONFIG = """[project]
name = "My blueprint"
blueprint = "blueprint.md"

[isabelle]
# session = "My_Session"
# executable = "isabelle"
# version = "Isabelle2025-2"
# timeout = 600  # max seconds for `isabelle build`/`dump`; omit to wait indefinitely

[afp]
# root = "/path/to/afp"
# entry = "My_AFP_Entry"
# required = false

[output]
build_dir = "build"
site_dir = "site"
"""

_AFP_CONFIG = """[project]
name = "AFP blueprint"
blueprint = "blueprint.md"

[isabelle]
session = "My_AFP_Session"
# executable = "isabelle"
# version = "Isabelle2025-2"
# timeout = 600

[afp]
root = "/path/to/afp"
entry = "My_AFP_Entry"
required = true

[output]
build_dir = "build"
site_dir = "site"
"""

_MINIMAL_BLUEPRINT = """# My blueprint

Welcome! Edit this file and replace the placeholder nodes below.
Tip: run `isabelle-blueprint new theorem my-id` to scaffold more nodes.

::: definition {#example-def}
title: Example definition
isabelle: Main.True
status: stub

Describe what is being defined.
:::

::: theorem {#example-thm}
title: Example theorem
isabelle: My_Theory.example_lemma
uses:
  - example-def
status: stub

State the result.

## Proof

Sketch the proof.
:::
"""

_AFP_BLUEPRINT = """# AFP-backed blueprint

Use this template when the formal facts live in an AFP entry.

::: definition {#entry-context}
title: AFP entry context
isabelle: My_AFP_Theory.some_definition
status: stub

Describe the objects imported from the AFP entry.
:::

::: theorem {#main-result}
title: Main AFP-backed result
isabelle: My_AFP_Theory.main_result
uses:
  - entry-context
status: stub

State the theorem that should be checked against the AFP session.

## Proof

Sketch how the AFP facts are used.
:::
"""

_RESEARCH_BLUEPRINT = """# Research-paper blueprint

Track definitions, lemmas, and theorems in the same order as the paper.

::: definition {#core-definition}
title: Core definition
status: written

Record the central definition from the paper.
:::

::: lemma {#technical-lemma}
title: Technical lemma
uses:
  - core-definition
status: stub

State the technical lemma.

## Proof

Outline the proof strategy and references to the paper.
:::

::: theorem {#main-theorem}
title: Main theorem
uses:
  - technical-lemma
status: stub

State the headline theorem.

## Proof

Describe the proof dependencies and remaining formalization work.
:::
"""

_COURSE_BLUEPRINT = """# Course-notes blueprint

Use this template to track lecture notes, exercises, and their formal facts.

::: definition {#lecture-definition}
title: Lecture definition
status: written

Introduce the definition from the notes.
:::

::: example {#worked-example}
title: Worked example
uses:
  - lecture-definition
status: written

Describe the worked example students should understand.
:::

::: theorem {#exercise-result}
title: Exercise result
uses:
  - worked-example
status: stub

State the exercise target.

## Proof

Sketch the intended solution.
:::
"""

_AGENT_BLUEPRINT = """# Agent-ready blueprint

This template highlights unblocked proof tasks for humans or coding agents.

::: definition {#foundation}
title: Foundation
isabelle: My_Theory.foundation
status:
  blueprint: written
  formal: found

Describe the already-available foundation fact.
:::

::: lemma {#next-lemma}
title: Next lemma
isabelle: My_Theory.next_lemma
uses:
  - foundation
status: written

State the smallest unblocked task.

## Proof

Give the agent enough proof hints to start.
:::
"""

TEMPLATES: dict[str, ProjectTemplate] = {
    "minimal": ProjectTemplate(
        name="minimal",
        description="Small starter with one definition and one theorem.",
        blueprint=_MINIMAL_BLUEPRINT,
        config=_DEFAULT_CONFIG,
        workflow=_BASE_WORKFLOW,
    ),
    "afp": ProjectTemplate(
        name="afp",
        description="Starter wired for an AFP-backed Isabelle session.",
        blueprint=_AFP_BLUEPRINT,
        config=_AFP_CONFIG,
        workflow=_BASE_WORKFLOW,
    ),
    "research-paper": ProjectTemplate(
        name="research-paper",
        description="Definition/lemma/theorem outline for paper formalizations.",
        blueprint=_RESEARCH_BLUEPRINT,
        config=_DEFAULT_CONFIG,
        workflow=_BASE_WORKFLOW,
    ),
    "course-notes": ProjectTemplate(
        name="course-notes",
        description="Lecture-note and exercise oriented starter.",
        blueprint=_COURSE_BLUEPRINT,
        config=_DEFAULT_CONFIG,
        workflow=_BASE_WORKFLOW,
    ),
    "agent-ready": ProjectTemplate(
        name="agent-ready",
        description="Starter that emits agent task packs in CI.",
        blueprint=_AGENT_BLUEPRINT,
        config=_DEFAULT_CONFIG,
        workflow=_AGENT_WORKFLOW,
    ),
}
