"""Public data models shared by every stage.

All models reject unknown fields. Evidence offsets are Unicode code-point
offsets into the original message text, left-closed/right-open.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.0"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Dimension(StrEnum):
    LANGUAGE = "language"
    BEHAVIOR = "behavior"
    THINKING = "thinking"
    EMOTION = "emotion"
    RELATIONSHIP = "relationship"
    HISTORY = "history"
    CHANGES = "changes"
    UNCERTAINTY = "uncertainty"


DIMENSIONS: tuple[Dimension, ...] = (
    Dimension.LANGUAGE,
    Dimension.BEHAVIOR,
    Dimension.THINKING,
    Dimension.EMOTION,
    Dimension.RELATIONSHIP,
    Dimension.HISTORY,
    Dimension.CHANGES,
    Dimension.UNCERTAINTY,
)


class ObservationKind(StrEnum):
    OBSERVED_PATTERN = "observed_pattern"
    REPORTED_FACT = "reported_fact"
    INFERENCE = "inference"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AnalysisStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


class QualityStatus(StrEnum):
    NOT_EVALUATED = "not_evaluated"
    INSUFFICIENT_DATA = "insufficient_data"
    EVALUATED = "evaluated"


class ExportStatus(StrEnum):
    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"


class Message(StrictModel):
    id: str
    index: int = Field(ge=0)
    speaker: str
    text: str
    timestamp: datetime | None = None
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    session_id: str

    @model_validator(mode="after")
    def _lines(self) -> "Message":
        if self.line_end < self.line_start:
            raise ValueError("line_end must be >= line_start")
        return self


class MessagePart(StrictModel):
    id: str
    message_id: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    text: str

    @model_validator(mode="after")
    def _range(self) -> "MessagePart":
        if self.end <= self.start:
            raise ValueError("part end must be greater than start")
        return self


class EvidenceRef(StrictModel):
    message_id: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def _range(self) -> "EvidenceRef":
        if self.end <= self.start:
            raise ValueError("evidence end must be greater than start")
        return self


class Scope(StrictModel):
    interlocutor: str
    message_start_id: str | None = None
    message_end_id: str | None = None
    situation: str | None = None
    time_scope: str | None = None


class Observation(StrictModel):
    id: str
    dimension: Dimension
    claim: str = Field(min_length=1)
    kind: ObservationKind
    evidence_refs: list[EvidenceRef] = Field(min_length=1)
    counter_evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    scope: Scope
    confidence: Confidence
    uncertainty: str
    source_speaker: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_uncertainty(cls, data: Any) -> Any:
        if isinstance(data, dict):
            value = data.get("uncertainty")
            if value is None:
                data["uncertainty"] = "模型未提供不确定说明"
            elif isinstance(value, list):
                data["uncertainty"] = "；".join(str(item) for item in value)
            elif not isinstance(value, str):
                data["uncertainty"] = str(value)
        return data


class SourceRange(StrictModel):
    first_message_id: str
    last_message_id: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)


class Chunk(StrictModel):
    id: str
    core_parts: list[str] = Field(min_length=1)
    context_parts: list[str] = Field(default_factory=list)
    source_range: SourceRange
    budget_estimate: int = Field(ge=0)


class PartNoObservation(StrictModel):
    part_id: str
    reason: str = Field(min_length=1)


class ExampleCandidate(StrictModel):
    message_ids: list[str] = Field(min_length=1)
    note: str | None = None


class SegmentAnalysis(StrictModel):
    schema_version: str = SCHEMA_VERSION
    chunk_id: str
    target: str
    processed_core_part_ids: list[str]
    observations: list[Observation] = Field(default_factory=list)
    processed_no_observation: list[PartNoObservation] = Field(default_factory=list)
    example_candidates: list[ExampleCandidate] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    overflow: bool = False


class Feature(StrictModel):
    id: str
    dimension: Dimension
    claim: str = Field(min_length=1)
    kind: ObservationKind
    observation_ids: list[str] = Field(min_length=1)
    counter_observation_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(min_length=1)
    confidence: Confidence
    scope: Scope
    uncertainty: str


class Coverage(StrictModel):
    source_hash: str
    total_messages: int = Field(ge=0)
    target_messages: int = Field(ge=0)
    total_chars: int = Field(ge=0)
    covered_chars: int = Field(ge=0)
    ratio: float = Field(ge=0.0, le=1.0)
    complete: bool
    core_part_ids: list[str] = Field(default_factory=list)


class ExampleLine(StrictModel):
    speaker: str
    text: str
    timestamp: datetime | None = None


class DialogueExample(StrictModel):
    id: str
    message_ids: list[str] = Field(min_length=2)
    lines: list[ExampleLine] = Field(min_length=2)
    situation: str = ""
    source: str = "original_chat"


class SelectionAudit(StrictModel):
    observation_id: str
    included: bool
    reason: str = Field(min_length=1)


class Disposition(StrictModel):
    item_id: str
    disposition: Literal["merged", "retained", "conflict", "low_support"]
    feature_id: str | None = None


class ReduceOutput(StrictModel):
    dimension: Dimension
    target: str
    features: list[Feature] = Field(default_factory=list)
    dispositions: list[Disposition] = Field(default_factory=list)


class Persona(StrictModel):
    schema_version: str = SCHEMA_VERSION
    target: str
    interlocutor: str
    source_hash: str
    coverage: Coverage
    language: list[Feature] = Field(default_factory=list)
    behavior: list[Feature] = Field(default_factory=list)
    thinking: list[Feature] = Field(default_factory=list)
    emotion: list[Feature] = Field(default_factory=list)
    relationship: list[Feature] = Field(default_factory=list)
    history: list[Feature] = Field(default_factory=list)
    changes: list[Feature] = Field(default_factory=list)
    uncertainty: list[Feature] = Field(default_factory=list)
    examples: list[DialogueExample] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    selection_audit: list[SelectionAudit] = Field(default_factory=list)


class TaskState(StrictModel):
    task_id: str
    task_type: str
    status: TaskStatus = TaskStatus.PENDING
    depends_on: list[str] = Field(default_factory=list)
    attempts: int = Field(default=0, ge=0)
    error_code: str | None = None
    error: str | None = None
    result_hash: str | None = None


class Manifest(StrictModel):
    schema_version: str = SCHEMA_VERSION
    prompt_version: str
    package_version: str
    run_id: str
    source_hash: str
    target: str
    interlocutor: str
    config_hash: str
    provider: str
    model: str | None
    is_mock: bool
    budget: dict[str, Any] = Field(default_factory=dict)
    tasks: dict[str, TaskState] = Field(default_factory=dict)
    coverage: Coverage | None = None
    analysis_status: AnalysisStatus = AnalysisStatus.PENDING
    quality_status: QualityStatus = QualityStatus.NOT_EVALUATED
    export_status: ExportStatus = ExportStatus.PENDING
    input_path: str | None = None
    created_at: datetime
    updated_at: datetime
