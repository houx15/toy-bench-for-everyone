"""Paper digest: fact-heavy. Gold claims written by the user, prewritten why/limitation
questions, an anchored scale for the questions the model raises, and a hallucination check
against the source text."""

from __future__ import annotations

import json
import random
from typing import Any

from pydantic import BaseModel, Field

from scorer_kit.graders.base import (
    CalibrationUnit, GradeContext, Grader, Grading, JudgeParseError, fill, format_anchors,
    parse_judge_json,
)
from scorer_kit.schemas import Job, Message, Recipe, Task

VERDICT_SCORE = {"covered": 1.0, "partial": 0.5, "missing": 0.0}

MOCK_FABRICATION = "The authors additionally prove convergence for all non-convex objectives."


class GoldQuestion(BaseModel):
    question: str
    reference: str = Field(description="What a good answer must contain, in the user's words.")


class PaperDigestGold(BaseModel):
    claims: list[str] = Field(min_length=3, description="10-15 key claims the user expects.")
    questions: list[GoldQuestion] = Field(default_factory=list)
    source_attachment: str | None = Field(
        default=None, description="Attachment that is the paper; default: all attachments."
    )


class PaperDigestGrader(Grader):
    name = "paper_digest"
    gold_model = PaperDigestGold

    def task_prompt_suffix(self, task: Task, recipe: Recipe) -> str:
        gold = PaperDigestGold.model_validate(task.gold)
        if not gold.questions:
            return ""
        qs = "\n".join(f"Q{i}. {q.question}" for i, q in enumerate(gold.questions, 1))
        return f"Also answer these questions, labelling each answer Q1, Q2, ...:\n{qs}"

    def judge_messages(self, task, recipe, output, attachments):
        gold = PaperDigestGold.model_validate(task.gold)
        source = "\n\n".join(
            text for name, text in attachments
            if gold.source_attachment is None or name == gold.source_attachment
        )
        claims = "\n".join(f"{i}. {c}" for i, c in enumerate(gold.claims, 1))
        questions = "\n".join(
            f"Q{i}. {q.question}\n    Reference: {q.reference}" for i, q in enumerate(gold.questions, 1)
        ) or "(none)"
        prompt = fill(
            recipe.judge.prompt,
            source=source or "(no source text supplied)",
            output=output,
            claims=claims,
            questions=questions,
            raised_anchors=format_anchors(recipe, "raised_questions"),
            answer_anchors=format_anchors(recipe, "answers"),
        )
        return [Message(role="system", content=recipe.judge.system),
                Message(role="user", content=prompt)]

    def grade(self, task, recipe, output, judge_reply, ctx: GradeContext) -> Grading:
        gold = PaperDigestGold.model_validate(task.gold)
        p = recipe.params
        criteria: dict[str, float] = {}
        details: dict[str, Any] = {}
        flags: list[str] = []

        # automatic checks
        words = len(output.split())
        details["words"] = words
        if words > p.get("max_words", 10**9):
            flags.append(f"over-length:{words}w")
        sections = p.get("required_sections", [])
        if sections:
            low = output.lower()
            present = [s for s in sections if s.lower() in low]
            details["sections_present"] = present
            criteria["format"] = len(present) / len(sections)

        if judge_reply is None:
            flags.append("no-judge")
            return Grading(criteria, details, flags)
        try:
            j = parse_judge_json(judge_reply)
        except JudgeParseError as e:
            flags.append("judge-unparseable")
            details["judge_error"] = str(e)
            return Grading(criteria, details, flags)

        verdicts = [_verdict(x) for x in j.get("claims", [])][: len(gold.claims)]
        if len(verdicts) < len(gold.claims):
            flags.append(f"judge-missed-claims:{len(gold.claims) - len(verdicts)}")
            verdicts += ["missing"] * (len(gold.claims) - len(verdicts))
        details["claim_verdicts"] = verdicts
        criteria["claim_coverage"] = sum(VERDICT_SCORE[v] for v in verdicts) / len(verdicts)

        if gold.questions:
            scale = recipe.criterion("answers").scale
            answers = [_num(x.get("score") if isinstance(x, dict) else x, scale.min)
                       for x in j.get("answers", [])][: len(gold.questions)]
            answers += [scale.min] * (len(gold.questions) - len(answers))
            details["answer_scores"] = answers
            criteria["answers"] = sum(scale.normalize(a) for a in answers) / len(answers)

        rq_scale = recipe.criterion("raised_questions").scale
        rq = _num(j.get("raised_questions_quality"), rq_scale.min)
        details["raised_questions_quality"] = rq
        criteria["raised_questions"] = rq_scale.normalize(rq)

        unsupported = [str(u) for u in j.get("unsupported_claims", []) if str(u).strip()]
        details["unsupported_claims"] = unsupported
        penalty = p.get("hallucination_penalty", 0.25)
        criteria["faithfulness"] = max(0.0, 1.0 - penalty * len(unsupported))
        if unsupported:
            flags.append(f"hallucinations:{len(unsupported)}")
        return Grading(criteria, details, flags)

    def calibration_units(self, recipe: Recipe, details: dict[str, Any]) -> list[CalibrationUnit]:
        units = []
        for i, v in enumerate(details.get("claim_verdicts", []), 1):
            units.append(CalibrationUnit(
                "claim_coverage", f"claim-{i}", "categorical", v,
                f"Gold claim {i}: is it covered, partially covered, or missing in the output?",
                ["covered", "partial", "missing"]))
        a_scale = recipe.criterion("answers").scale
        for i, s in enumerate(details.get("answer_scores", []), 1):
            units.append(CalibrationUnit(
                "answers", f"q-{i}", "ordinal", s, f"Score the answer to Q{i}.",
                list(range(int(a_scale.min), int(a_scale.max) + 1))))
        if "raised_questions_quality" in details:
            rq = recipe.criterion("raised_questions").scale
            units.append(CalibrationUnit(
                "raised_questions", "overall", "ordinal", details["raised_questions_quality"],
                "Rate the questions the output raises on its own.",
                list(range(int(rq.min), int(rq.max) + 1))))
        if "unsupported_claims" in details:
            units.append(CalibrationUnit(
                "faithfulness", "unsupported-count", "numeric", len(details["unsupported_claims"]),
                "How many statements in the output are NOT supported by the paper?"))
        return units

    # -- mocks

    def mock_output(self, job: Job, skill: float, rng: random.Random) -> str:
        gold = PaperDigestGold.model_validate(job.meta["gold"])
        lines = ["## Summary", "A mock digest of the paper.", "", "## Key claims"]
        lines += [f"- {c}" for c in gold.claims if rng.random() < skill]
        if rng.random() > skill:
            lines.append(f"- {MOCK_FABRICATION}")
        lines += ["", "## Answers"]
        lines += [f"Q{i}. A {'detailed' if rng.random() < skill else 'vague'} answer."
                  for i in range(1, len(gold.questions) + 1)]
        lines += ["", "## Questions I would raise", "- Does it hold out of distribution?"]
        return "\n".join(lines)

    def mock_judgement(self, job: Job, rng: random.Random) -> str:
        gold = PaperDigestGold.model_validate(job.meta["gold"])
        output = job.meta["output"]
        claims = []
        for i, c in enumerate(gold.claims, 1):
            v = "covered" if c in output else "missing"
            if rng.random() < 0.1:
                v = "partial"
            claims.append({"id": i, "verdict": v})
        answers = [{"id": i, "score": 2 if f"Q{i}. A detailed" in output else rng.choice([0, 1])}
                   for i in range(1, len(gold.questions) + 1)]
        return "```json\n" + json.dumps({
            "claims": claims,
            "answers": answers,
            "raised_questions_quality": rng.choice([1, 2, 2, 3]),
            "unsupported_claims": [MOCK_FABRICATION] if MOCK_FABRICATION in output else [],
        }, indent=2) + "\n```"


def _verdict(x: Any) -> str:
    v = (x.get("verdict") if isinstance(x, dict) else x) or "missing"
    v = str(v).strip().lower()
    return v if v in VERDICT_SCORE else "missing"


def _num(x: Any, default: float) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default
