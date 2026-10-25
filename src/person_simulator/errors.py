"""Error types and stable exit codes for person-simulator."""

from __future__ import annotations

from enum import IntEnum
from typing import Any


class ExitCode(IntEnum):
    OK = 0
    INPUT = 2
    API = 3
    PIPELINE = 4
    IO = 5
    INTERRUPTED = 130


class PersonSimError(Exception):
    """Base error carrying a safe code, stage and optional task id."""

    exit_code: int = ExitCode.PIPELINE
    error_code: str = "E_PIPELINE"

    def __init__(
        self,
        message: str,
        *,
        stage: str | None = None,
        task_id: str | None = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.stage = stage
        self.task_id = task_id
        self.hint = hint

    def __str__(self) -> str:
        parts = [self.error_code]
        if self.stage:
            parts.append(f"stage={self.stage}")
        if self.task_id:
            parts.append(f"task={self.task_id}")
        head = " ".join(parts)
        text = f"{head}: {self.message}"
        if self.hint:
            text += f" 建议：{self.hint}"
        return text

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": self.message,
            "stage": self.stage,
            "task_id": self.task_id,
            "hint": self.hint,
            "exit_code": int(self.exit_code),
        }


class InputError(PersonSimError):
    exit_code = ExitCode.INPUT
    error_code = "E_INPUT"


class ConfigError(PersonSimError):
    exit_code = ExitCode.INPUT
    error_code = "E_CONFIG"


class APIError(PersonSimError):
    exit_code = ExitCode.API
    error_code = "E_API"


class AuthenticationError(APIError):
    error_code = "E_AUTH"


class RateLimitError(APIError):
    error_code = "E_RATE_LIMIT"


class ProviderUnavailable(APIError):
    error_code = "E_PROVIDER_UNAVAILABLE"


class ContextLimitError(APIError):
    error_code = "E_CONTEXT_LIMIT"


class ResponseFormatError(APIError):
    error_code = "E_RESPONSE_FORMAT"


class OutputTruncatedError(APIError):
    error_code = "E_OUTPUT_TRUNCATED"


class TransportError(APIError):
    error_code = "E_TRANSPORT"


class PipelineError(PersonSimError):
    exit_code = ExitCode.PIPELINE
    error_code = "E_PIPELINE"


class EvidenceError(PipelineError):
    error_code = "E_EVIDENCE"


class PrivacyError(PipelineError):
    error_code = "E_PRIVACY"


class StorageError(PersonSimError):
    exit_code = ExitCode.IO
    error_code = "E_IO"


class InterruptedError(PersonSimError):
    exit_code = ExitCode.INTERRUPTED
    error_code = "E_INTERRUPTED"


class RuntimeError(PersonSimError):
    """Base class for runtime-persona loading and simulation errors."""

    exit_code = ExitCode.PIPELINE
    error_code = "E_RUNTIME"


class RunNotFoundError(RuntimeError):
    exit_code = ExitCode.INPUT
    error_code = "E_RUN_NOT_FOUND"


class RunIncompleteError(RuntimeError):
    error_code = "E_RUN_INCOMPLETE"


class RunVersionError(RuntimeError):
    exit_code = ExitCode.INPUT
    error_code = "E_RUN_VERSION"


class RunHashError(RuntimeError):
    error_code = "E_RUN_HASH"


class RunModeError(RuntimeError):
    exit_code = ExitCode.INPUT
    error_code = "E_RUN_MODE"


class InviteError(PersonSimError):
    exit_code = ExitCode.INPUT
    error_code = "E_INVITE"


class SessionError(PersonSimError):
    exit_code = ExitCode.PIPELINE
    error_code = "E_SESSION"


class SessionNotFoundError(SessionError):
    error_code = "E_SESSION_NOT_FOUND"


class SessionEndedError(SessionError):
    error_code = "E_SESSION_ENDED"


class SessionExpiredError(SessionError):
    error_code = "E_SESSION_EXPIRED"


class SessionLimitError(SessionError):
    error_code = "E_SESSION_LIMIT"


class TurnLimitError(SessionError):
    error_code = "E_TURN_LIMIT"


class SessionRateLimitError(SessionError):
    error_code = "E_SESSION_RATE_LIMIT"


class InputTooLongError(PersonSimError):
    exit_code = ExitCode.INPUT
    error_code = "E_INPUT_TOO_LONG"


class OutputBlockedError(PersonSimError):
    exit_code = ExitCode.PIPELINE
    error_code = "E_OUTPUT_BLOCKED"


class AccessDeniedError(PersonSimError):
    exit_code = ExitCode.INPUT
    error_code = "E_UNAUTHORIZED"


class ForbiddenError(PersonSimError):
    exit_code = ExitCode.INPUT
    error_code = "E_FORBIDDEN"


class ClientError(PersonSimError):
    exit_code = ExitCode.API
    error_code = "E_CLIENT"
