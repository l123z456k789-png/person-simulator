from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from person_simulator.config import Settings, load_settings


def write_chat(tmp_path: Path, text: str, name: str = "chat.txt") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def make_settings(**overrides) -> Settings:
    return load_settings(config_path=None, cli_overrides=overrides, env={})


@pytest.fixture
def settings() -> Settings:
    return make_settings()
