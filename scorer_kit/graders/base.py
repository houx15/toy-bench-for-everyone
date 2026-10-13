"""Shared grader machinery: prompt templating, judge-JSON parsing, score combination."""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

from pydantic import BaseModel

from scorer_kit.schemas import Job, Message, Recipe, Task


class JudgeParseError(ValueError):
    pass


def fill(template: str, **values: str) -> str:
    """Replace ``{{name}}`` placeholders. Single braces stay literal so prompts can show JSON."""

    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in values:
            raise KeyError(f"template placeholder {{{{{key}}}}} has no value")
        return values[key]

    return re.sub(r"\{\{\s*([a-z_]+)\s*\}\}", sub, template)


def parse_judge_json(text: str) -> dict[str, Any]:
    """Pull the JSON object out of a judge reply, tolerating code fences and chatter."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = [fenced.group(1)] if fenced else []
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for c in candidates:
        try:
            data = json.loads(c)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    raise JudgeParseError(f"no JSON object found in judge reply: {text[:200]!r}")


@dataclass
class CalibrationUnit:
    """One thing both the judge and the user label, e.g. 'is claim 3 covered?'."""

    criterion: str
    key: str
    kind: Literal["categorical", "ordinal", "numeric"]
    judge_label: Any
    question: str
    allowed: list[Any] | None = None


@dataclass
class GradeContext:
    """Extra material some graders need, e.g. other models' outputs for leave-one-out baselines."""

    peer_outputs: list[str] = field(default_factory=list)


@dataclass
class Grading:
    criteria: dict[str, float]
    details: dict[str, Any] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)


def combine(recipe: Recipe, criteria: dict[str, float]) -> tuple[float, list[str]]:
    """Weighted mean over the criteria that have a value; missing ones are reported."""
    total = weight = 0.0
    missing = []
    for c in recipe.criteria:
        if c.id in criteria:
            total += c.weight * criteria[c.id]
            weight += c.weight
        elif c.weight > 0:
            missing.append(f"missing-criterion:{c.id}")
    return (total / weight if weight else 0.0), missing


class Grader:
    """One per recipe family. Subclasses define gold material, prompts, scoring and mocks."""

    name: ClassVar[str]
    gold_model: ClassVar[type[BaseModel]]

    # -- prompts

    def task_prompt_suffix(self, task: Task, recipe: Recipe) -> str:
        """Extra instructions derived from gold material (e.g. the questions to answer)."""
        return ""

    def judge_messages(self, task: Task, recipe: Recipe, output: str,
                       attachments: list[tuple[str, str]]) -> list[Message] | None:
        return None

    # -- scoring

    def grade(self, task: Task, recipe: Recipe, output: str, judge_reply: str | None,
              ctx: GradeContext) -> Grading:
        raise NotImplementedError

    def calibration_units(self, recipe: Recipe, details: dict[str, Any]) -> list[CalibrationUnit]:
        return []

    # -- offline mock support

    def mock_output(self, job: Job, skill: float, rng: random.Random) -> str:
        raise NotImplementedError

    def mock_judgement(self, job: Job, rng: random.Random) -> str:
        raise NotImplementedError


def format_anchors(recipe: Recipe, criterion_id: str) -> str:
    c = recipe.criterion(criterion_id)
    return "\n".join(f"  {k}: {v}" for k, v in c.scale.anchors.items())
