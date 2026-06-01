"""Example IsabelleBlueprint status-provider plugin."""

from __future__ import annotations


def status_annotations(project):
    """Annotate nodes tagged ``needs-review``."""

    for node in project.nodes:
        if "needs-review" in getattr(node, "tags", []):
            yield {
                "node_id": node.id,
                "severity": "warning",
                "message": "Node is tagged needs-review.",
            }
