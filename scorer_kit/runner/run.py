"""Fan out task x model x repeat, then grade every output with a judge that is not the
model under test. Both steps are resumable: finished calls are skipped on re-run, which is
also how app (handoff) mode picks up pasted responses."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from scorer_kit.graders import REGISTRY
from scorer_kit.graders.base import GradeContext, combine
from scorer_kit.kit import Kit, load_kit
from scorer_kit.runner.backends import ModelSpec, make_backends
from scorer_kit.schemas import (
    CallResult, GradeRecord, Job, Message, OutputRecord, RunConfig, Task,
)


# ---------------------------------------------------------------- run folder


@dataclass
class Run:
    dir: Path
    config: RunConfig
    kit: Kit

    @classmethod
    def load(cls, run_dir: Path | str) -> Run:
        run_dir = Path(run_dir)
        config = RunConfig.model_validate(yaml.safe_load((run_dir / "run.yaml").read_text()))
        return cls(run_dir, config, load_kit(config.kit))

    @property
    def handoff_dir(self) -> Path:
        return self.dir / "handoff"

    def tasks(self) -> list[Task]:
        return [self.kit.tasks[t] for t in self.config.tasks]

    def output_path(self, model: str, task_id: str, repeat: int) -> Path:
        return self.dir / "outputs" / ModelSpec.parse(model).slug / f"{task_id}__r{repeat}.json"

    def grade_path(self, model: str, task_id: str, repeat: int) -> Path:
        return self.dir / "grades" / ModelSpec.parse(model).slug / f"{task_id}__r{repeat}.json"

    def read_output(self, model: str, task_id: str, repeat: int) -> OutputRecord | None:
        p = self.output_path(model, task_id, repeat)
        return OutputRecord.model_validate_json(p.read_text()) if p.is_file() else None

    def read_grade(self, model: str, task_id: str, repeat: int) -> GradeRecord | None:
        p = self.grade_path(model, task_id, repeat)
        return GradeRecord.model_validate_json(p.read_text()) if p.is_file() else None

    def cells(self):
        for task in self.tasks():
            for model in self.config.models:
                for r in range(1, self.config.repeats + 1):
                    yield task, model, r


def create_run(kit_dir: Path | str, models: list[str], judges: list[str], repeats: int,
               results_dir: Path | str, run_id: str | None = None,
               task_ids: list[str] | None = None) -> Run:
    for spec in [*models, *judges]:
        ModelSpec.parse(spec)  # fail fast on typos
    if len(set(models)) != len(models):
        raise ValueError("each model may be listed only once")
    kit = load_kit(kit_dir)
    tasks = task_ids or sorted(kit.tasks)
    unknown = [t for t in tasks if t not in kit.tasks]
    if unknown:
        raise ValueError(f"unknown task ids: {unknown}")
    _check_judges(models, judges, kit, tasks)

    run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = Path(results_dir) / run_id
    if (run_dir / "run.yaml").exists():
        raise FileExistsError(f"run already exists: {run_dir}")
    run_dir.mkdir(parents=True)
    config = RunConfig(run_id=run_id, kit=str(kit.root), models=models, judges=judges,
                       repeats=repeats, tasks=tasks)
    (run_dir / "run.yaml").write_text(yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False))
    return Run(run_dir, config, kit)


def _check_judges(models: list[str], judges: list[str], kit: Kit, tasks: list[str]) -> None:
    needs_judge = any(
        any(c.source == "judge" for c in kit.recipe_for(kit.tasks[t]).criteria) for t in tasks
    )
    if not needs_judge:
        return
    if not judges:
        raise ValueError("these recipes need an AI judge: pass at least one --judge")
    for m in models:
        if all(j == m for j in judges):
            raise ValueError(
                f"no judge available for {m}: a model never grades its own outputs, "
                "so add a judge that is not under test (or a second judge)"
            )


def pick_judge(model: str, judges: list[str]) -> str | None:
    """First listed judge that is not the model under test."""
    return next((j for j in judges if j != model), None)


# ---------------------------------------------------------------- prompts


def task_messages(kit: Kit, task: Task) -> list[Message]:
    recipe = kit.recipe_for(task)
    grader = REGISTRY[recipe.grader]
    messages = []
    context = kit.context_pack_text()
    if context:
        messages.append(Message(role="system",
                                content=f"Background about the person you are helping:\n\n{context}"))
    parts = [f'<document name="{name}">\n{text}\n</document>'
             for name, text in kit.attachment_text(task)]
    parts.append(task.input.prompt.strip())
    for extra in (grader.task_prompt_suffix(task, recipe), recipe.response_format):
        if extra.strip():
            parts.append(extra.strip())
    messages.append(Message(role="user", content="\n\n".join(parts)))
    return messages


# ---------------------------------------------------------------- execution


@dataclass
class Progress:
    done: int = 0
    new: int = 0
    pending: int = 0
    errors: list[str] = field(default_factory=list)
    waiting: int = 0  # grades blocked on outputs that are not in yet

    def summary(self, what: str) -> str:
        s = f"{what}: {self.done} done ({self.new} new), {self.pending} waiting for app responses"
        if self.waiting:
            s += f", {self.waiting} blocked on missing outputs"
        if self.errors:
            s += f", {len(self.errors)} errors"
        return s


def execute(jobs: list[Job], backends, workers: int = 8) -> list[tuple[Job, CallResult]]:
    def one(job: Job) -> tuple[Job, CallResult]:
        try:
            return job, backends[ModelSpec.parse(job.model).provider].call(job)
        except Exception as e:  # a crashed call must not kill the whole fan-out
            return job, CallResult(status="error", error=f"{type(e).__name__}: {e}")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, jobs))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def run_tasks(run: Run, workers: int = 8) -> Progress:
    progress = Progress()
    jobs = []
    for task, model, r in run.cells():
        rec = run.read_output(model, task.id, r)
        if rec and rec.result.status == "ok":
            progress.done += 1
            continue
        recipe = run.kit.recipe_for(task)
        jobs.append(Job(
            id=f"task__{task.id}__r{r}", kind="task", model=model,
            messages=task_messages(run.kit, task),
            meta={"task_id": task.id, "repeat": r, "grader": recipe.grader, "gold": task.gold},
        ))
    backends = make_backends([j.model for j in jobs], run.handoff_dir)
    for job, result in execute(jobs, backends, workers):
        if result.status == "pending":
            progress.pending += 1
            continue
        task_id, r = job.meta["task_id"], job.meta["repeat"]
        rec = OutputRecord(run_id=run.config.run_id, task_id=task_id, model=job.model,
                           repeat=r, result=result)
        path = run.output_path(job.model, task_id, r)
        _write(path, rec.model_dump_json(indent=2))
        if result.status == "ok":
            _write(path.with_suffix(".md"), result.text)
            progress.done += 1
            progress.new += 1
        else:
            progress.errors.append(f"{job.model} {task_id} r{r}: {result.error}")
    if progress.pending:
        write_handoff_index(run)
    return progress


def grade_run(run: Run, workers: int = 8, regrade: bool = False) -> Progress:
    progress = Progress()
    outputs: dict[str, list[OutputRecord]] = defaultdict(list)
    complete: dict[str, bool] = {}
    for task, model, r in run.cells():
        rec = run.read_output(model, task.id, r)
        if rec is not None and rec.result.status == "ok":
            outputs[task.id].append(rec)
        complete.setdefault(task.id, True)
        if rec is None:
            complete[task.id] = False

    jobs, pending_cells = [], []
    for task in run.tasks():
        recipe = run.kit.recipe_for(task)
        grader = REGISTRY[recipe.grader]
        for rec in outputs[task.id]:
            if not regrade and run.read_grade(rec.model, task.id, rec.repeat):
                progress.done += 1
                continue
            if not complete[task.id]:
                # novelty-style criteria compare against peers, so wait for every output
                progress.waiting += 1
                continue
            judge = pick_judge(rec.model, run.config.judges)
            msgs = grader.judge_messages(task, recipe, rec.result.text, run.kit.attachment_text(task))
            if msgs is None or judge is None:
                pending_cells.append((task, rec, None, None))
                continue
            slug = ModelSpec.parse(rec.model).slug
            job = Job(id=f"judge__{slug}__{task.id}__r{rec.repeat}", kind="judge", model=judge,
                      messages=msgs,
                      meta={"grader": recipe.grader, "gold": task.gold, "output": rec.result.text})
            jobs.append(job)
            pending_cells.append((task, rec, job, judge))

    backends = make_backends([j.model for j in jobs], run.handoff_dir)
    results = {j.id + j.model: res for j, res in execute(jobs, backends, workers)}

    for task, rec, job, judge in pending_cells:
        reply = None
        if job is not None:
            res = results[job.id + job.model]
            if res.status == "pending":
                progress.pending += 1
                continue
            if res.status == "error":
                progress.errors.append(f"judge {judge} on {rec.model} {task.id}: {res.error}")
                continue
            reply = res.text
        recipe = run.kit.recipe_for(task)
        peers = [o.result.text for o in outputs[task.id] if o.model != rec.model]
        g = REGISTRY[recipe.grader].grade(task, recipe, rec.result.text, reply, GradeContext(peers))
        score, missing = combine(recipe, g.criteria)
        grade = GradeRecord(
            run_id=run.config.run_id, task_id=task.id, model=rec.model, repeat=rec.repeat,
            recipe=recipe.id, judge_model=judge, criteria={k: round(v, 4) for k, v in g.criteria.items()},
            score=round(score, 4), details={**g.details, **({"judge_reply": reply} if reply else {})},
            flags=g.flags + missing,
        )
        _write(run.grade_path(rec.model, task.id, rec.repeat), grade.model_dump_json(indent=2))
        progress.done += 1
        progress.new += 1
    if progress.pending:
        write_handoff_index(run)
    return progress


# ---------------------------------------------------------------- app-mode instructions


def write_handoff_index(run: Run) -> Path:
    """HANDOFF.md: a checklist of prompts still waiting for a response, per app model."""
    lines = [
        f"# Handoff for run {run.config.run_id}",
        "",
        "Some models in this run are used through a chat app instead of an API.",
        "For each prompt below:",
        "",
        "1. Open a **new, temporary chat** (no memory, no custom instructions) with that model.",
        "2. Paste the whole content of the `.prompt.md` file and send it.",
        "3. Paste the model's complete reply into the matching `.response.md` file next to it.",
        "",
        "Then re-run the same `scorer` command; finished responses are picked up and only",
        "missing ones are listed again. An AI app with file access can do steps 1-3 for you",
        "if it can open fresh chats with the target model.",
        "",
    ]
    for model_dir in sorted(p for p in run.handoff_dir.iterdir() if p.is_dir()):
        waiting = []
        for prompt in sorted(model_dir.glob("*.prompt.md")):
            response = prompt.with_name(prompt.name.replace(".prompt.md", ".response.md"))
            if not (response.is_file() and response.read_text().strip()):
                waiting.append(f"- [ ] `{prompt.relative_to(run.dir)}` -> `{response.name}`")
        if waiting:
            lines += [f"## {model_dir.name} ({len(waiting)} waiting)", "", *waiting, ""]
    path = run.dir / "HANDOFF.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def status(run: Run) -> dict:
    out = Counter()
    graded = Counter()
    for task, model, r in run.cells():
        rec = run.read_output(model, task.id, r)
        out[(model, rec.result.status if rec else "missing")] += 1
        if run.read_grade(model, task.id, r):
            graded[model] += 1
    return {
        "models": {
            m: {"outputs_ok": out[(m, "ok")], "errors": out[(m, "error")],
                "missing": out[(m, "missing")], "graded": graded[m]}
            for m in run.config.models
        },
        "cells_per_model": len(run.config.tasks) * run.config.repeats,
    }


def dump_status(run: Run) -> str:
    return json.dumps(status(run), indent=2)
