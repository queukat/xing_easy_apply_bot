from __future__ import annotations

import importlib

import pytest


def test_entrypoint_modules_importable() -> None:
    for name in ("xingbot", "xingbot.browser", "xingbot.auto_run", "xingbot.cli"):
        importlib.import_module(name)


def test_auto_run_help() -> None:
    mod = importlib.import_module("xingbot.auto_run")
    with pytest.raises(SystemExit) as exc:
        mod.main(["--help"])
    assert exc.value.code == 0


def test_cli_help() -> None:
    mod = importlib.import_module("xingbot.cli")
    with pytest.raises(SystemExit) as exc:
        mod.main(["--help"])
    assert exc.value.code == 0

