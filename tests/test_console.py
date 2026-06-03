from __future__ import annotations

from isabelle_blueprint import console


def teardown_function() -> None:
    # Never let colour state leak into other tests.
    console.set_enabled(False)


def test_disabled_by_default_returns_plain_text() -> None:
    console.set_enabled(False)
    assert console.error("boom") == "boom"
    assert console.paint("x", "red") == "x"


def test_enabled_wraps_in_ansi_codes() -> None:
    console.set_enabled(True)
    painted = console.error("boom")
    assert painted.startswith("\033[31m")
    assert painted.endswith("\033[0m")
    assert "boom" in painted


def test_paint_with_unknown_style_is_plain() -> None:
    console.set_enabled(True)
    assert console.paint("x", "not-a-style") == "x"


def test_configure_always_and_never() -> None:
    assert console.configure("always") is True
    assert console.is_enabled() is True
    assert console.configure("never") is False
    assert console.is_enabled() is False


def test_configure_auto_off_for_non_tty() -> None:
    import io

    # A plain StringIO is not a TTY, so auto must disable colour.
    assert console.configure("auto", stream=io.StringIO()) is False


def test_configure_auto_honours_no_color(monkeypatch) -> None:
    class _FakeTTY:
        def isatty(self) -> bool:
            return True

    monkeypatch.setenv("NO_COLOR", "1")
    assert console.configure("auto", stream=_FakeTTY()) is False
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert console.configure("auto", stream=_FakeTTY()) is True
