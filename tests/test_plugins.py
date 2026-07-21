"""Tests for the plugin discovery layer."""

from __future__ import annotations

import warnings
from dataclasses import dataclass

from isabelle_blueprint import plugins as plugins_mod
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import BlueprintStatus, FormalStatus


@dataclass
class _FakeEntryPoint:
    name: str
    _value: object
    _raises: type[BaseException] | None = None
    dist: object | None = None

    def load(self):
        if self._raises is not None:
            raise self._raises("boom")
        return self._value


def _project() -> BlueprintProject:
    node = BlueprintNode(
        id="def-a",
        kind=NodeKind.DEFINITION,
        title="A",
        statement="def of A",
        isabelle=IsabelleRef(fact="Demo.a_def"),
        status=NodeStatus(blueprint=BlueprintStatus.WRITTEN, formal=FormalStatus.NAMED),
    )
    return BlueprintProject.from_nodes("smoke", [node], sources=["smoke.md"])


def test_discover_returns_loaded_plugins(monkeypatch):
    def good(project):
        return [{"node_id": project.nodes[0].id, "data": {"hello": "world"}}]

    def fake_select(group: str):
        assert group == plugins_mod.STATUS_PROVIDER_GROUP
        return [_FakeEntryPoint(name="good", _value=good)]

    monkeypatch.setattr(plugins_mod, "_iter_entry_points", fake_select)
    loaded = plugins_mod.discover_status_providers()
    assert [p.name for p in loaded] == ["good"]
    assert loaded[0].callable_ is good


def test_discover_skips_failing_load(monkeypatch):
    def fake_select(group: str):
        return [
            _FakeEntryPoint(name="broken", _value=None, _raises=ValueError),
            _FakeEntryPoint(name="ok", _value=lambda _: []),
        ]

    monkeypatch.setattr(plugins_mod, "_iter_entry_points", fake_select)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        loaded = plugins_mod.discover_status_providers()
    assert [p.name for p in loaded] == ["ok"]
    assert any("broken" in str(w.message) for w in caught)


def test_discover_skips_non_callable(monkeypatch):
    def fake_select(group: str):
        return [_FakeEntryPoint(name="not-callable", _value="hello")]

    monkeypatch.setattr(plugins_mod, "_iter_entry_points", fake_select)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        loaded = plugins_mod.discover_status_providers()
    assert loaded == []
    assert any("not callable" in str(w.message) for w in caught)


def test_run_status_providers_collects_annotations():
    def provider(project):
        yield {"node_id": project.nodes[0].id, "data": {"score": 1.0}}
        yield {"node_id": project.nodes[0].id, "data": {"score": 2.0}}

    plugin = plugins_mod.LoadedPlugin(name="p1", dist=None, callable_=provider)
    out = plugins_mod.run_status_providers(_project(), [plugin])
    assert len(out) == 2
    assert all(item["plugin"] == "p1" for item in out)


def test_run_status_providers_isolates_errors():
    def boom(project):
        raise RuntimeError("nope")

    def good(project):
        return [{"node_id": project.nodes[0].id, "data": {"ok": True}}]

    plugins = [
        plugins_mod.LoadedPlugin(name="boom", dist=None, callable_=boom),
        plugins_mod.LoadedPlugin(name="good", dist=None, callable_=good),
    ]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        out = plugins_mod.run_status_providers(_project(), plugins)
    assert [a["plugin"] for a in out] == ["good"]
    assert any("boom" in str(w.message) for w in caught)


def test_run_status_providers_handles_non_iterable():
    def bad(project):
        return 42  # not iterable

    plugin = plugins_mod.LoadedPlugin(name="bad", dist=None, callable_=bad)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        out = plugins_mod.run_status_providers(_project(), [plugin])
    assert out == []
    assert any("did not return an iterable" in str(w.message) for w in caught)


def test_run_status_providers_skips_none():
    def empty(project):
        return None

    plugin = plugins_mod.LoadedPlugin(name="empty", dist=None, callable_=empty)
    out = plugins_mod.run_status_providers(_project(), [plugin])
    assert out == []


def test_run_report_renderers_collects_artifacts(tmp_path):
    def renderer(project, output_dir):
        path = output_dir / "custom.html"
        path.write_text(project.name, encoding="utf-8")
        return path

    plugin = plugins_mod.LoadedPlugin(name="html", dist=None, callable_=renderer)

    artifacts = plugins_mod.run_report_renderers(_project(), tmp_path, [plugin])

    assert artifacts == [{"path": str(tmp_path / "custom.html"), "plugin": "html"}]


def test_run_node_kind_plugins_collects_kinds():
    def provider():
        return [{"name": "exercise"}]

    plugin = plugins_mod.LoadedPlugin(name="kinds", dist=None, callable_=provider)

    kinds = plugins_mod.run_node_kind_plugins([plugin])

    assert kinds == [{"name": "exercise", "plugin": "kinds"}]
