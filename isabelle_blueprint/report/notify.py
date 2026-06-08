"""Build and (optionally) post a blueprint status notification to a webhook.

This turns the same status metrics shown by ``status``/``badge`` into a chat
notification for Slack, Microsoft Teams, Discord, or a generic JSON webhook -
handy as the last step of a CI run ("coverage is now 72%, 3 problems").

Safety posture (this is the only command that can talk to an arbitrary network
endpoint, so it is deliberately conservative):

* **Dry-run by default.** Nothing is sent unless the caller explicitly opts in;
  the CLI prints the payload it *would* post so it can be inspected first.
* **HTTPS only** unless explicitly allowed, so a secret webhook token in the URL
  is never sent over plaintext by accident.
* **No redirects.** A webhook that 30x-redirects is treated as an error rather
  than silently following the hop to a different host.
* **Short timeout**, and the payload only ever contains aggregate counts - never
  file paths, node bodies, or other project contents.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from urllib.parse import urlparse

from isabelle_blueprint.errors import BlueprintError
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.report.metrics import StatusMetrics

SUPPORTED_FORMATS: tuple[str, ...] = ("slack", "teams", "discord", "generic")

DEFAULT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class NotificationContent:
    """The format-agnostic content of a status notification."""

    title: str
    summary: str
    lines: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        """A single plaintext block (title + bulleted lines)."""
        body = "\n".join(f"- {line}" for line in self.lines)
        return f"{self.title}\n{body}" if body else self.title


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse to follow redirects; a webhook should answer directly."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise BlueprintError(
            f"refusing to follow redirect ({code}) to {newurl!r}; "
            "point --url directly at the webhook endpoint"
        )


def build_notification(
    project: BlueprintProject,
    metrics: StatusMetrics,
    *,
    eta_days: float | None = None,
) -> NotificationContent:
    """Summarise ``metrics`` into a chat-ready notification for ``project``."""
    if metrics.coverage_percent is None:
        coverage = "n/a (no formal targets)"
    else:
        coverage = f"{metrics.coverage_percent}%"

    lines = [
        f"Coverage: {coverage}",
        f"Nodes: {metrics.node_count} "
        f"({metrics.formal_target_count} formal target(s))",
        f"Proved: {metrics.proved_count}  Found: {metrics.found_count}",
        f"Problems: {metrics.problem_count}  Stale: {metrics.stale_count}",
    ]
    if metrics.has_cycles:
        lines.append("Dependency cycle detected")
    if eta_days is not None:
        lines.append(f"Burndown ETA: ~{eta_days:.0f} day(s)")

    summary = f"{project.name}: {coverage} proved, {metrics.problem_count} problem(s)"
    title = f"IsabelleBlueprint status - {project.name}"
    return NotificationContent(title=title, summary=summary, lines=lines)


def render_payload(content: NotificationContent, fmt: str) -> dict[str, object]:
    """Render ``content`` as the JSON body for the given webhook ``fmt``."""
    if fmt == "slack":
        return {"text": content.text}
    if fmt == "discord":
        return {"content": content.text}
    if fmt == "teams":
        return {
            "@type": "MessageCard",
            "@context": "https://schema.org/extensions",
            "summary": content.summary,
            "title": content.title,
            "text": "  \n".join(content.lines),
        }
    if fmt == "generic":
        return {
            "title": content.title,
            "summary": content.summary,
            "lines": list(content.lines),
        }
    raise BlueprintError(
        f"unsupported notification format {fmt!r}; "
        f"choose one of {', '.join(SUPPORTED_FORMATS)}"
    )


def post_notification(
    url: str,
    payload: dict[str, object],
    *,
    allow_http: bool = False,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> int:
    """POST ``payload`` as JSON to ``url`` and return the HTTP status code.

    Raises :class:`BlueprintError` for a disallowed scheme, a redirect, or any
    network/HTTP failure.
    """
    scheme = urlparse(url).scheme.lower()
    if scheme == "http" and not allow_http:
        raise BlueprintError(
            "refusing to POST over plaintext http; use https "
            "or pass --allow-http to override"
        )
    if scheme not in ("https", "http"):
        raise BlueprintError(
            f"unsupported URL scheme {scheme!r}; the webhook must be http(s)"
        )

    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=timeout) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        raise BlueprintError(
            f"webhook POST failed with HTTP {exc.code}: {exc.reason}"
        ) from exc
    except urllib.error.URLError as exc:
        raise BlueprintError(f"webhook POST failed: {exc.reason}") from exc
