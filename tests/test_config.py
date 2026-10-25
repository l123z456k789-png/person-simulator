from __future__ import annotations

import tomllib

import pytest

from person_simulator.config import load_settings
from person_simulator.errors import ConfigError


def _write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def test_precedence_cli_env_toml_default(tmp_path):
    config = _write(tmp_path / "config.toml", "[chunking]\nchunk_input_budget = 700\n")
    settings = load_settings(
        config_path=config,
        cli_overrides={"chunk_input_budget": 900},
        env={"PSIM_CHUNK_INPUT_BUDGET": "800"},
    )
    assert settings.chunking.chunk_input_budget == 900
    assert settings.sources["chunking.chunk_input_budget"] == "cli"

    settings = load_settings(
        config_path=config,
        cli_overrides={},
        env={"PSIM_CHUNK_INPUT_BUDGET": "800"},
    )
    assert settings.chunking.chunk_input_budget == 800

    settings = load_settings(config_path=config, cli_overrides={}, env={})
    assert settings.chunking.chunk_input_budget == 700

    settings = load_settings(config_path=None, cli_overrides={}, env={})
    assert settings.chunking.chunk_input_budget == 6000


def test_api_key_only_from_environment(tmp_path):
    config = _write(
        tmp_path / "config.toml",
        """
[model]
mode = "api"
provider = "openai_chat"
model = "test-model"
base_url = "https://api.example.com/v1"
context_window = 32768
""",
    )
    settings = load_settings(config_path=config, env={"PSIM_API_KEY": "sk-secret"})
    assert settings.api_key == "sk-secret"
    assert "sk-secret" not in repr(settings)


def test_toml_rejects_api_key_key(tmp_path):
    config = _write(tmp_path / "config.toml", "[model]\napi_key = \"sk-x\"\n")
    with pytest.raises(ConfigError):
        load_settings(config_path=config, env={})


def test_config_hash_excludes_key(tmp_path):
    config = _write(
        tmp_path / "config.toml",
        """
[model]
mode = "api"
provider = "openai_chat"
model = "test-model"
base_url = "https://api.example.com/v1"
context_window = 32768
""",
    )
    first = load_settings(config_path=config, env={"PSIM_API_KEY": "one"})
    second = load_settings(config_path=config, env={"PSIM_API_KEY": "two"})
    assert first.config_hash() == second.config_hash()


def test_unknown_section_and_key_rejected(tmp_path):
    with pytest.raises(ConfigError):
        load_settings(config_path=_write(tmp_path / "a.toml", "[unknown]\nx = 1\n"), env={})
    with pytest.raises(ConfigError):
        load_settings(config_path=_write(tmp_path / "b.toml", "[model]\nunknown = 1\n"), env={})


def test_api_requires_model_url_context(tmp_path):
    config = _write(tmp_path / "config.toml", "[model]\nmode = \"api\"\nprovider = \"openai_chat\"\n")
    with pytest.raises(ConfigError):
        load_settings(config_path=config, env={"PSIM_API_KEY": "x"})


def test_insecure_localhost_rules(tmp_path):
    base = """
[model]
mode = "api"
provider = "openai_chat"
model = "test"
context_window = 32768
base_url = "{url}"
"""
    config = _write(tmp_path / "config.toml", base.format(url="http://127.0.0.1:8000/v1"))
    with pytest.raises(ConfigError):
        load_settings(config_path=config, env={"PSIM_API_KEY": "x"})
    settings = load_settings(
        config_path=config,
        env={"PSIM_API_KEY": "x"},
        cli_overrides={"allow_insecure_localhost": True},
    )
    assert settings.model.base_url == "http://127.0.0.1:8000/v1"

    config = _write(tmp_path / "bad.toml", base.format(url="http://example.com/v1"))
    with pytest.raises(ConfigError):
        load_settings(
            config_path=config,
            env={"PSIM_API_KEY": "x"},
            cli_overrides={"allow_insecure_localhost": True},
        )


def test_url_rejects_credentials_query_and_chat_path(tmp_path):
    template = """
[model]
mode = "api"
provider = "openai_chat"
model = "test"
context_window = 32768
base_url = "{url}"
"""
    for url in (
        "https://user:pass@api.example.com/v1",
        "https://api.example.com/v1?key=abc",
        "https://api.example.com/v1/chat/completions",
    ):
        config = _write(tmp_path / "config.toml", template.format(url=url))
        with pytest.raises(ConfigError):
            load_settings(config_path=config, env={"PSIM_API_KEY": "x"})


def test_mock_mode_rejects_openai_provider(tmp_path):
    config = _write(
        tmp_path / "config.toml",
        "[model]\nmode = \"mock\"\nprovider = \"openai_chat\"\n",
    )
    with pytest.raises(ConfigError):
        load_settings(config_path=config, env={})
