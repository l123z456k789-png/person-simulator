"""Versioned runtime persona contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal

from person_simulator.models import StrictModel

RUNTIME_SCHEMA_VERSION = "runtime-persona-1.0"


class Audience(StrEnum):
    GUEST = "guest"
    ORIGINAL = "original"


class RuntimePersona(StrictModel):
    schema_version: Literal["runtime-persona-1.0"] = RUNTIME_SCHEMA_VERSION
    run_id: str
    strategy: Literal["evidence", "whole"]
    package_version: str
    prompt_version: str
    source_hash: str
    target: str
    interlocutor: str
    system_prompt: str
    system_prompt_sha256: str
    original_system_prompt_sha256: str
    is_mock: bool
    audience: Audience = Audience.GUEST
    replay_guard: Literal["full", "prompt_only"] = "prompt_only"
    created_at: datetime


@dataclass(frozen=True)
class LoadedPersona:
    """Runtime persona plus local-only replay material.

    ``replay_messages`` is never serialized or returned to a third party. It
    exists only so the output guard can detect verbatim replay.
    """

    persona: RuntimePersona
    replay_messages: tuple[str, ...] = ()
