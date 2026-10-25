"""Configuration loading with CLI > PSIM_ env > TOML > defaults precedence."""

from __future__ import annotations

import hashlib
import json
import os
import tomllib
from pathlib import Path
from typing import Any, Literal, Mapping
from urllib.parse import urlsplit

from pydantic import Field

from person_simulator.errors import ConfigError
from person_simulator.models import StrictModel

SECTION_KEYS: dict[str, set[str]] = {
    "model": {
        "mode",
        "provider",
        "model",
        "base_url",
        "context_window",
        "max_output_tokens",
        "output_limit_param",
        "json_object",
        "disable_thinking",
        "temperature",
    },
    "chunking": {"chunk_input_budget", "overlap_messages"},
    "retry": {"max_attempts", "connect_timeout", "read_timeout"},
    "budget": {"max_repair_attempts", "max_context_splits", "max_requests_per_run"},
    "mock": {"context_window"},
    "security": {"allow_insecure_localhost", "trust_env"},
    "simulation": {
        "host",
        "port",
        "allow_lan",
        "secure_cookies",
        "max_sessions",
        "ttl_minutes",
        "idle_minutes",
        "max_turns",
        "max_input_chars",
        "max_output_tokens",
        "requests_per_minute",
        "max_concurrency",
        "allowed_hosts",
        "blocked_terms",
        "log_metadata",
    },
}

DEFAULTS: dict[str, Any] = {
    "model.mode": "mock",
    "model.provider": "mock",
    "model.model": None,
    "model.base_url": None,
    "model.context_window": None,
    "model.max_output_tokens": 4096,
    "model.output_limit_param": "max_tokens",
    "model.json_object": False,
    "model.disable_thinking": False,
    "model.temperature": None,
    "chunking.chunk_input_budget": 6000,
    "chunking.overlap_messages": 4,
    "retry.max_attempts": 3,
    "retry.connect_timeout": 10.0,
    "retry.read_timeout": 120.0,
    "budget.max_repair_attempts": 1,
    "budget.max_context_splits": 8,
    "budget.max_requests_per_run": 500,
    "mock.context_window": 32768,
    "security.allow_insecure_localhost": False,
    "security.trust_env": False,
    "simulation.host": "127.0.0.1",
    "simulation.port": 8765,
    "simulation.allow_lan": False,
    "simulation.secure_cookies": False,
    "simulation.max_sessions": 8,
    "simulation.ttl_minutes": 30,
    "simulation.idle_minutes": 10,
    "simulation.max_turns": 30,
    "simulation.max_input_chars": 2000,
    "simulation.max_output_tokens": 1024,
    "simulation.requests_per_minute": 6,
    "simulation.max_concurrency": 2,
    "simulation.allowed_hosts": ["127.0.0.1", "localhost", "::1"],
    "simulation.blocked_terms": [],
    "simulation.log_metadata": False,
}

BOOL_PATHS = {
    "model.json_object",
    "model.disable_thinking",
    "security.allow_insecure_localhost",
    "security.trust_env",
    "simulation.allow_lan",
    "simulation.secure_cookies",
    "simulation.log_metadata",
}
INT_PATHS = {
    "model.context_window",
    "model.max_output_tokens",
    "chunking.chunk_input_budget",
    "chunking.overlap_messages",
    "retry.max_attempts",
    "budget.max_repair_attempts",
    "budget.max_context_splits",
    "budget.max_requests_per_run",
    "mock.context_window",
    "simulation.port",
    "simulation.max_sessions",
    "simulation.ttl_minutes",
    "simulation.idle_minutes",
    "simulation.max_turns",
    "simulation.max_input_chars",
    "simulation.max_output_tokens",
    "simulation.requests_per_minute",
    "simulation.max_concurrency",
}
FLOAT_PATHS = {"model.temperature", "retry.connect_timeout", "retry.read_timeout"}
LIST_PATHS = {"simulation.allowed_hosts", "simulation.blocked_terms"}

ENV_PATHS: dict[str, str] = {
    "PSIM_MODE": "model.mode",
    "PSIM_PROVIDER": "model.provider",
    "PSIM_MODEL": "model.model",
    "PSIM_BASE_URL": "model.base_url",
    "PSIM_CONTEXT_WINDOW": "model.context_window",
    "PSIM_MAX_OUTPUT_TOKENS": "model.max_output_tokens",
    "PSIM_OUTPUT_LIMIT_PARAM": "model.output_limit_param",
    "PSIM_JSON_OBJECT": "model.json_object",
    "PSIM_DISABLE_THINKING": "model.disable_thinking",
    "PSIM_TEMPERATURE": "model.temperature",
    "PSIM_CHUNK_INPUT_BUDGET": "chunking.chunk_input_budget",
    "PSIM_OVERLAP_MESSAGES": "chunking.overlap_messages",
    "PSIM_MAX_ATTEMPTS": "retry.max_attempts",
    "PSIM_CONNECT_TIMEOUT": "retry.connect_timeout",
    "PSIM_READ_TIMEOUT": "retry.read_timeout",
    "PSIM_MAX_REPAIR_ATTEMPTS": "budget.max_repair_attempts",
    "PSIM_MAX_CONTEXT_SPLITS": "budget.max_context_splits",
    "PSIM_MAX_REQUESTS_PER_RUN": "budget.max_requests_per_run",
    "PSIM_MOCK_CONTEXT_WINDOW": "mock.context_window",
    "PSIM_ALLOW_INSECURE_LOCALHOST": "security.allow_insecure_localhost",
    "PSIM_TRUST_ENV": "security.trust_env",
    "PSIM_SIM_HOST": "simulation.host",
    "PSIM_SIM_PORT": "simulation.port",
    "PSIM_SIM_ALLOW_LAN": "simulation.allow_lan",
    "PSIM_SIM_SECURE_COOKIES": "simulation.secure_cookies",
    "PSIM_SIM_MAX_SESSIONS": "simulation.max_sessions",
    "PSIM_SIM_TTL_MINUTES": "simulation.ttl_minutes",
    "PSIM_SIM_IDLE_MINUTES": "simulation.idle_minutes",
    "PSIM_SIM_MAX_TURNS": "simulation.max_turns",
    "PSIM_SIM_MAX_INPUT_CHARS": "simulation.max_input_chars",
    "PSIM_SIM_MAX_OUTPUT_TOKENS": "simulation.max_output_tokens",
    "PSIM_SIM_REQUESTS_PER_MINUTE": "simulation.requests_per_minute",
    "PSIM_SIM_MAX_CONCURRENCY": "simulation.max_concurrency",
    "PSIM_SIM_ALLOWED_HOSTS": "simulation.allowed_hosts",
    "PSIM_SIM_BLOCKED_TERMS": "simulation.blocked_terms",
    "PSIM_SIM_LOG_METADATA": "simulation.log_metadata",
}

CLI_PATHS: dict[str, str] = {
    "mode": "model.mode",
    "provider": "model.provider",
    "model": "model.model",
    "base_url": "model.base_url",
    "context_window": "model.context_window",
    "max_output_tokens": "model.max_output_tokens",
    "output_limit_param": "model.output_limit_param",
    "json_object": "model.json_object",
    "disable_thinking": "model.disable_thinking",
    "temperature": "model.temperature",
    "chunk_input_budget": "chunking.chunk_input_budget",
    "overlap_messages": "chunking.overlap_messages",
    "max_attempts": "retry.max_attempts",
    "connect_timeout": "retry.connect_timeout",
    "read_timeout": "retry.read_timeout",
    "max_repair_attempts": "budget.max_repair_attempts",
    "max_context_splits": "budget.max_context_splits",
    "max_requests_per_run": "budget.max_requests_per_run",
    "allow_insecure_localhost": "security.allow_insecure_localhost",
    "trust_env": "security.trust_env",
}


class ModelSettings(StrictModel):
    mode: Literal["mock", "api"] = "mock"
    provider: Literal["mock", "openai_chat"] = "mock"
    model: str | None = None
    base_url: str | None = None
    context_window: int | None = None
    max_output_tokens: int = Field(default=4096, gt=0)
    output_limit_param: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"
    json_object: bool = False
    disable_thinking: bool = False
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)


class ChunkSettings(StrictModel):
    chunk_input_budget: int = Field(default=6000, ge=576)
    overlap_messages: int = Field(default=4, ge=0, le=64)


class RetrySettings(StrictModel):
    max_attempts: int = Field(default=3, ge=1, le=10)
    connect_timeout: float = Field(default=10.0, gt=0)
    read_timeout: float = Field(default=120.0, gt=0)


class BudgetSettings(StrictModel):
    max_repair_attempts: int = Field(default=1, ge=0, le=3)
    max_context_splits: int = Field(default=8, ge=0, le=32)
    max_requests_per_run: int = Field(default=500, ge=1)


class MockSettings(StrictModel):
    context_window: int = Field(default=32768, gt=0)


class SecuritySettings(StrictModel):
    allow_insecure_localhost: bool = False
    trust_env: bool = False


class SimulationSettings(StrictModel):
    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=8765, ge=1, le=65535)
    allow_lan: bool = False
    secure_cookies: bool = False
    max_sessions: int = Field(default=8, ge=1, le=64)
    ttl_minutes: int = Field(default=30, ge=1)
    idle_minutes: int = Field(default=10, ge=1)
    max_turns: int = Field(default=30, ge=1)
    max_input_chars: int = Field(default=2000, ge=1)
    max_output_tokens: int = Field(default=1024, ge=1)
    requests_per_minute: int = Field(default=6, ge=1)
    max_concurrency: int = Field(default=2, ge=1, le=16)
    allowed_hosts: list[str] = Field(
        default_factory=lambda: ["127.0.0.1", "localhost", "::1"]
    )
    blocked_terms: list[str] = Field(default_factory=list)
    log_metadata: bool = False


class Settings(StrictModel):
    model: ModelSettings
    chunking: ChunkSettings
    retry: RetrySettings
    budget: BudgetSettings
    mock: MockSettings
    security: SecuritySettings
    simulation: SimulationSettings = Field(default_factory=SimulationSettings)
    api_key: str | None = Field(default=None, repr=False)
    sources: dict[str, str] = Field(default_factory=dict)
    config_path: str | None = None

    @property
    def effective_context_window(self) -> int:
        if self.model.mode == "api":
            if self.model.context_window is None:  # pragma: no cover - validated
                raise ConfigError("api 模式缺少 context_window", stage="config")
            return self.model.context_window
        return self.mock.context_window

    @property
    def is_mock(self) -> bool:
        return self.model.mode == "mock"

    @property
    def api_ready(self) -> bool:
        return self.model.mode == "api" and bool(self.api_key)

    def config_hash(self) -> str:
        # Simulation settings do not affect a modeling run; excluding them
        # keeps resume fingerprints stable for pre-0.2.0 runs.
        payload = self.model_dump(
            exclude={"api_key", "sources", "config_path", "simulation"}
        )
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def public_summary(self) -> dict[str, Any]:
        return {
            "mode": self.model.mode,
            "provider": self.model.provider,
            "model": self.model.model,
            "base_url_host": _host_only(self.model.base_url),
            "effective_context_window": self.effective_context_window,
            "max_output_tokens": self.model.max_output_tokens,
            "chunk_input_budget": self.chunking.chunk_input_budget,
            "overlap_messages": self.chunking.overlap_messages,
            "api_key_present": bool(self.api_key),
            "config_path": self.config_path,
            "sources": dict(self.sources),
        }


def _host_only(url: str | None) -> str | None:
    if not url:
        return None
    split = urlsplit(url)
    return f"{split.scheme}://{split.hostname}" if split.hostname else None


def _coerce(path: str, value: Any) -> Any:
    if value is None:
        return None
    if path in BOOL_PATHS:
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        raise ConfigError(f"{path} 需要布尔值", stage="config", hint="使用 true 或 false")
    if path in INT_PATHS:
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"{path} 需要整数", stage="config") from exc
    if path in FLOAT_PATHS:
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"{path} 需要数字", stage="config") from exc
    if path in LIST_PATHS:
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            if not value.strip():
                return []
            return [item.strip() for item in value.split(",") if item.strip()]
        raise ConfigError(
            f"{path} 需要字符串列表", stage="config", hint="使用 TOML 数组或逗号分隔字符串"
        )
    return str(value)


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise ConfigError("配置文件不存在", stage="config", hint=str(path)) from exc
    except OSError as exc:
        raise ConfigError("配置文件不可读", stage="config", hint=str(path)) from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError("配置文件不是合法 TOML", stage="config", hint=str(path)) from exc

    flat: dict[str, Any] = {}
    for section, values in data.items():
        if section not in SECTION_KEYS:
            raise ConfigError(
                "配置文件包含未知配置段",
                stage="config",
                hint=f"允许的段：{', '.join(sorted(SECTION_KEYS))}",
            )
        if not isinstance(values, dict):
            raise ConfigError(f"配置段 {section} 必须是表", stage="config")
        for key, value in values.items():
            if key not in SECTION_KEYS[section]:
                raise ConfigError(
                    "配置文件包含未知配置项",
                    stage="config",
                    hint=f"{section}.{key}",
                )
            flat[f"{section}.{key}"] = value
    return flat


def _resolve_config_path(explicit: str | Path | None, env: Mapping[str, str]) -> Path | None:
    if explicit is not None:
        return Path(explicit)
    if env.get("PSIM_CONFIG"):
        return Path(env["PSIM_CONFIG"])
    candidate = Path("config.toml")
    return candidate if candidate.exists() else None


def load_settings(
    *,
    config_path: str | Path | None = None,
    cli_overrides: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> Settings:
    environment = os.environ if env is None else env
    merged = dict(DEFAULTS)
    sources = {key: "default" for key in DEFAULTS}
    path = _resolve_config_path(config_path, environment)

    if path is not None:
        for key, value in _read_toml(path).items():
            merged[key] = _coerce(key, value)
            sources[key] = "toml"

    for env_key, key in ENV_PATHS.items():
        if env_key in environment and environment[env_key] != "":
            merged[key] = _coerce(key, environment[env_key])
            sources[key] = "env"

    for cli_key, value in (cli_overrides or {}).items():
        if value is None:
            continue
        key = CLI_PATHS.get(cli_key)
        if key is None:
            raise ConfigError("未知 CLI 配置项", stage="config", hint=cli_key)
        merged[key] = _coerce(key, value)
        sources[key] = "cli"

    model = ModelSettings(
        mode=merged["model.mode"],
        provider=merged["model.provider"],
        model=merged["model.model"],
        base_url=merged["model.base_url"],
        context_window=merged["model.context_window"],
        max_output_tokens=merged["model.max_output_tokens"],
        output_limit_param=merged["model.output_limit_param"],
        json_object=merged["model.json_object"],
        disable_thinking=merged["model.disable_thinking"],
        temperature=merged["model.temperature"],
    )
    settings = Settings(
        model=model,
        chunking=ChunkSettings(
            chunk_input_budget=merged["chunking.chunk_input_budget"],
            overlap_messages=merged["chunking.overlap_messages"],
        ),
        retry=RetrySettings(
            max_attempts=merged["retry.max_attempts"],
            connect_timeout=merged["retry.connect_timeout"],
            read_timeout=merged["retry.read_timeout"],
        ),
        budget=BudgetSettings(
            max_repair_attempts=merged["budget.max_repair_attempts"],
            max_context_splits=merged["budget.max_context_splits"],
            max_requests_per_run=merged["budget.max_requests_per_run"],
        ),
        mock=MockSettings(context_window=merged["mock.context_window"]),
        security=SecuritySettings(
            allow_insecure_localhost=merged["security.allow_insecure_localhost"],
            trust_env=merged["security.trust_env"],
        ),
        simulation=SimulationSettings(
            host=merged["simulation.host"],
            port=merged["simulation.port"],
            allow_lan=merged["simulation.allow_lan"],
            secure_cookies=merged["simulation.secure_cookies"],
            max_sessions=merged["simulation.max_sessions"],
            ttl_minutes=merged["simulation.ttl_minutes"],
            idle_minutes=merged["simulation.idle_minutes"],
            max_turns=merged["simulation.max_turns"],
            max_input_chars=merged["simulation.max_input_chars"],
            max_output_tokens=merged["simulation.max_output_tokens"],
            requests_per_minute=merged["simulation.requests_per_minute"],
            max_concurrency=merged["simulation.max_concurrency"],
            allowed_hosts=list(merged["simulation.allowed_hosts"]),
            blocked_terms=list(merged["simulation.blocked_terms"]),
            log_metadata=merged["simulation.log_metadata"],
        ),
        api_key=(environment.get("PSIM_API_KEY") or None),
        sources=sources,
        config_path=str(path) if path is not None else None,
    )
    _validate_settings(settings)
    return settings


def _validate_settings(settings: Settings) -> None:
    model = settings.model
    if model.mode == "mock":
        if model.provider != "mock":
            raise ConfigError(
                "mock 模式要求 provider=mock",
                stage="config",
                hint="将 provider 改为 mock，或显式 mode=api",
            )
        return

    if model.provider != "openai_chat":
        raise ConfigError(
            "api 模式当前仅支持 provider=openai_chat",
            stage="config",
            hint="将 provider 设为 openai_chat",
        )
    if not model.model or not model.model.strip():
        raise ConfigError("api 模式必须配置 model", stage="config")
    if not model.base_url:
        raise ConfigError("api 模式必须配置 base_url", stage="config")
    if model.context_window is None:
        raise ConfigError("api 模式必须配置 context_window", stage="config")
    if model.max_output_tokens >= model.context_window:
        raise ConfigError(
            "max_output_tokens 必须小于 context_window",
            stage="config",
            hint="降低输出上限或确认服务商上下文窗口",
        )
    _validate_base_url(model.base_url, settings.security.allow_insecure_localhost)


def _validate_base_url(base_url: str, allow_insecure_localhost: bool) -> None:
    split = urlsplit(base_url)
    if split.username or split.password:
        raise ConfigError("base_url 不得包含用户名或密码", stage="config")
    if split.query or split.fragment:
        raise ConfigError("base_url 不得包含查询参数或 fragment", stage="config")
    if split.scheme == "https":
        pass
    elif split.scheme == "http":
        host = (split.hostname or "").lower()
        loopback = host in {"127.0.0.1", "::1", "localhost"}
        if not (allow_insecure_localhost and loopback):
            raise ConfigError(
                "http 仅允许显式开启的 loopback 地址",
                stage="config",
                hint="使用 https，或设置 security.allow_insecure_localhost=true 且地址为 localhost",
            )
    else:
        raise ConfigError("base_url 必须是 http(s) URL", stage="config")
    if not split.hostname:
        raise ConfigError("base_url 缺少主机名", stage="config")
    if split.path.rstrip("/").endswith("/chat/completions"):
        raise ConfigError(
            "base_url 应是 API 根地址，不要包含 /chat/completions",
            stage="config",
            hint="例如 https://api.example.com/v1",
        )
