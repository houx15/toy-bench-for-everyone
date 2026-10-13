"""Pydantic schemas for the kit's plain files: profile, tasks, recipes, run records.

Everything a user edits is YAML validated by these models, so mistakes surface at
load time with a readable message instead of halfway through a paid run.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")

BucketType = Literal["model-dependent", "public-benchmark", "product-dependent", "high-stakes"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _check_id(value: str) -> str:
    if not ID_PATTERN.match(value):
        raise ValueError(f"id {value!r} must be lowercase letters, digits and dashes")
    return value


# ---------------------------------------------------------------- profile


class Bucket(Strict):
    id: str
    name: str
    type: BucketType = "model-dependent"
    usage_share: float = Field(ge=0, le=1, description="Share of the user's real usage, 0-1.")
    description: str = ""

    _id = field_validator("id")(_check_id)


class Profile(Strict):
    """my-kit/profile.yaml: who the kit belongs to and how their usage splits."""

    kit_version: str = "0.1.0"
    owner: str | None = None
    created: date | None = None
    buckets: list[Bucket] = Field(min_length=1)
    current_favorite: str | None = Field(
        default=None, description="Model label the radar compares new models against."
    )
    context_pack: str | None = Field(
        default=None,
        description="Optional text file (relative to the kit) given identically to every model.",
    )

    @model_validator(mode="after")
    def _buckets_consistent(self) -> Profile:
        ids = [b.id for b in self.buckets]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate bucket ids in {ids}")
        total = sum(b.usage_share for b in self.buckets)
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"bucket usage_share values must sum to 1, got {total:.3f}")
        return self

    def bucket(self, bucket_id: str) -> Bucket:
        for b in self.buckets:
            if b.id == bucket_id:
                return b
        raise KeyError(bucket_id)


# ---------------------------------------------------------------- tasks


class TaskInput(Strict):
    prompt: str = Field(min_length=1)
    attachments: list[str] = Field(
        default_factory=list,
        description="Text files relative to the task file. Every model receives identical text.",
    )

    @field_validator("attachments")
    @classmethod
    def _text_only(cls, paths: list[str]) -> list[str]:
        for p in paths:
            if not p.lower().endswith((".txt", ".md")):
                raise ValueError(
                    f"attachment {p!r}: only .txt/.md are supported so every model sees the "
                    "same text; convert PDFs to text once during setup"
                )
        return paths


class Task(Strict):
    """my-kit/tasks/<id>.yaml"""

    id: str
    title: str = ""
    bucket: str
    recipe: str
    input: TaskInput
    gold: dict[str, Any] = Field(
        default_factory=dict, description="Recipe-specific gold material, validated by the recipe."
    )
    weight: float = Field(default=1.0, gt=0, description="Weight within its bucket.")
    source: str = Field(default="", description="Where in the user's history this task came from.")

    _id = field_validator("id")(_check_id)


# ---------------------------------------------------------------- recipes


class Scale(Strict):
    kind: Literal["binary", "ordinal", "numeric"]
    min: float = 0
    max: float = 1
    anchors: dict[str, str] = Field(
        default_factory=dict, description="Scale point -> anchor description shown to judges and users."
    )

    @model_validator(mode="after")
    def _range(self) -> Scale:
        if self.max <= self.min:
            raise ValueError("scale max must exceed min")
        return self

    def normalize(self, value: float) -> float:
        clipped = min(max(value, self.min), self.max)
        return (clipped - self.min) / (self.max - self.min)


class Criterion(Strict):
    id: str
    name: str
    weight: float = Field(ge=0)
    source: Literal["auto", "judge", "user"]
    scale: Scale
    description: str = ""


class JudgeSpec(Strict):
    system: str
    prompt: str = Field(description="Template; {placeholders} are filled by the recipe's grader.")


class CalibrationSpec(Strict):
    sample_size: int = Field(default=20, ge=5)
    min_kappa: float = Field(default=0.6, description="Provisional; see open questions in CLAUDE.md.")
    min_correlation: float = 0.6


class Recipe(Strict):
    """recipes/<id>.yaml: how one task type is measured, fixed before any model runs."""

    id: str
    name: str
    description: str = ""
    grader: str = Field(description="Key in scorer_kit.graders.REGISTRY.")
    response_format: str = Field(
        default="", description="Appended to every task prompt so outputs are checkable."
    )
    criteria: list[Criterion] = Field(min_length=1)
    automatic_checks: dict[str, str] = Field(
        default_factory=dict, description="Check name -> what it measures (documentation)."
    )
    params: dict[str, Any] = Field(default_factory=dict, description="Grader tuning knobs.")
    judge: JudgeSpec | None = None
    calibration: CalibrationSpec = Field(default_factory=CalibrationSpec)

    _id = field_validator("id")(_check_id)

    @model_validator(mode="after")
    def _criteria_consistent(self) -> Recipe:
        ids = [c.id for c in self.criteria]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate criterion ids in {ids}")
        if sum(c.weight for c in self.criteria) <= 0:
            raise ValueError("criterion weights must not all be zero")
        if any(c.source == "judge" for c in self.criteria) and self.judge is None:
            raise ValueError("recipe has judge criteria but no judge prompt")
        return self

    def criterion(self, criterion_id: str) -> Criterion:
        for c in self.criteria:
            if c.id == criterion_id:
                return c
        raise KeyError(criterion_id)


# ---------------------------------------------------------------- run records


class Message(Strict):
    role: Literal["system", "user", "assistant"]
    content: str


class Job(Strict):
    """One model call. Executed by an API backend, or handed off to a chat app as files."""

    id: str
    kind: Literal["task", "judge"]
    model: str
    messages: list[Message]
    meta: dict[str, Any] = Field(default_factory=dict)


class CallResult(Strict):
    text: str = ""
    status: Literal["ok", "error", "pending"] = "ok"
    error: str | None = None
    latency_s: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    backend: str = ""
    created: datetime = Field(default_factory=datetime.now)


class OutputRecord(Strict):
    """results/<run>/outputs/<model>/<task>__r<k>.json"""

    run_id: str
    task_id: str
    model: str
    repeat: int
    result: CallResult


class GradeRecord(Strict):
    """results/<run>/grades/<model>/<task>__r<k>.json — criterion scores normalized to 0-1."""

    run_id: str
    task_id: str
    model: str
    repeat: int
    recipe: str
    judge_model: str | None = None
    criteria: dict[str, float]
    score: float
    details: dict[str, Any] = Field(default_factory=dict)
    flags: list[str] = Field(default_factory=list)


class RunConfig(Strict):
    """results/<run>/run.yaml"""

    run_id: str
    kit: str
    models: list[str] = Field(min_length=1)
    judges: list[str] = Field(default_factory=list)
    repeats: int = Field(default=3, ge=1)
    tasks: list[str] = Field(default_factory=list)
    created: datetime = Field(default_factory=datetime.now)
