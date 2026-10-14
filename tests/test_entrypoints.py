import os
import re
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"


def test_main_runs_headless_and_quits_on_event(monkeypatch):
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    import pygame

    calls = {"n": 0}

    def fake_get():
        calls["n"] += 1
        if calls["n"] < 3:
            return []
        return [pygame.event.Event(pygame.QUIT)]

    monkeypatch.setattr(pygame.event, "get", fake_get)
    runpy.run_path(str(ROOT / "main.py"), run_name="__main__")
    assert calls["n"] == 3


def test_run_preview_ui_delegates_to_launch_ui(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import tools.preview_app as preview_app

    monkeypatch.setattr(preview_app, "launch_ui", lambda **_: 7)
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(ROOT / "run_preview_ui.py"), run_name="__main__")
    assert exc.value.code == 7


def test_threshold_policy_runs_on_simulator():
    from algo import ThresholdHoldPolicy, run_batch, run_episode
    from sim import State

    episode = run_episode(ThresholdHoldPolicy(seed=1), tier=1)
    assert episode.state == State.SUCCESS
    batch = run_batch(ThresholdHoldPolicy(seed=1), episodes=3, tier=1)
    assert batch.episodes == 3
    assert batch.wins == 3


def _imports_of(package: str) -> set[str]:
    found: set[str] = set()
    pattern = re.compile(r"^\s*(?:from|import)\s+([A-Za-z_][\w]*)", re.M)
    for path in (SRC / package).rglob("*.py"):
        if "tests" in path.relative_to(SRC).parts:
            continue
        found.update(pattern.findall(path.read_text(encoding="utf-8")))
    return found


@pytest.mark.parametrize("package", ["sim", "ui", "algo"])
def test_simulator_side_does_not_import_autofish(package):
    assert not _imports_of(package) & {"autofish", "tools"}


def test_autofish_does_not_import_simulator_or_shell():
    assert not _imports_of("autofish") & {"sim", "ui", "algo", "tools"}
