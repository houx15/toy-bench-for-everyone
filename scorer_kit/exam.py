"""Exam mode: one self-contained file to hand to any chat app, and a parser for its reply.

The kit holds gold answers, so it must never be shown to a model under test. ``write_exam``
renders only what the models are supposed to see (prompts, attachments, response formats)
into EXAM.md. The app answers every task in one reply using delimited sections, and
``ingest_answers`` files those sections as app-mode responses for a run.

One chat answers all tasks once, so one chat = one repeat. That is a deliberate trade-off
against strict per-task isolation: 3 chats per model instead of 3 x tasks.
"""

from __future__ import annotations

import re
from pathlib import Path

from scorer_kit.kit import Kit
from scorer_kit.runner.backends import ModelSpec
from scorer_kit.runner.run import Run, task_messages

# Markers need at least one "=" so a body line like "Answer correctness" is never a header;
# stray markdown (bold, quotes, headings) around a marker is tolerated.
ANSWER_START = re.compile(r"^[\s*#>]*=+\s*ANSWER\s+([a-z0-9][a-z0-9-]*)\s*=*[\s*]*$", re.I)
ANSWER_END = re.compile(r"^[\s*#>]*=+\s*END\s+ANSWER\s*=*[\s*]*$", re.I)


def render_exam(kit: Kit, task_ids: list[str] | None = None) -> str:
    ids = task_ids or sorted(kit.tasks)
    lines = [
        "# A few requests from me",
        "",
        "Please work through each request below, in order. Treat each one as if I had asked",
        "it on its own, in a fresh conversation: use only that request and the documents",
        "included with it.",
        "",
        "Put every answer in this exact format, so I can file them. Use the id given in each",
        "request's heading:",
        "",
        "```",
        "=== ANSWER <request-id> ===",
        "(your complete answer)",
        "=== END ANSWER ===",
        "```",
        "",
        "If the reply gets too long, stop after a complete answer and I will say \"continue\".",
        "",
    ]
    context = kit.context_pack_text()
    if context:
        lines += ["## Background about me", "", context.strip(), ""]
    for n, tid in enumerate(ids, 1):
        task = kit.tasks[tid]
        user_text = next(m.content for m in reversed(task_messages(kit, task)) if m.role == "user")
        lines += [f"## Request {n} of {len(ids)} (id: {tid})", "", user_text.strip(), ""]
    lines += ["---", "", f"That's all {len(ids)} requests. Remember the ANSWER / END ANSWER markers."]
    return "\n".join(lines) + "\n"


def write_exam(kit: Kit, out: Path, task_ids: list[str] | None = None) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_exam(kit, task_ids), encoding="utf-8")
    return out


def parse_answers(text: str) -> dict[str, str]:
    """Split a reply into {task_id: answer}. A missing END marker ends at the next ANSWER."""
    answers: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []

    def flush():
        if current is not None:
            body = "\n".join(buf).strip()
            body = re.sub(r"^```\w*\n|\n```$", "", body).strip() if body.startswith("```") else body
            if body:
                answers[current] = body

    for line in text.splitlines():
        start = ANSWER_START.match(line)
        if start:
            flush()
            current, buf = start.group(1).lower(), []
        elif ANSWER_END.match(line):
            flush()
            current, buf = None, []
        elif current is not None:
            buf.append(line)
    flush()
    return answers


def ingest_answers(run: Run, model: str, repeat: int, text: str, force: bool = False) -> dict:
    spec = ModelSpec.parse(model)
    if model not in run.config.models:
        raise ValueError(f"{model} is not in this run (models: {run.config.models})")
    if spec.provider != "app":
        raise ValueError(f"{model}: only app: models take pasted answers")
    if not 1 <= repeat <= run.config.repeats:
        raise ValueError(f"repeat must be 1..{run.config.repeats}")

    answers = parse_answers(text)
    folder = run.handoff_dir / spec.slug
    folder.mkdir(parents=True, exist_ok=True)
    filed, skipped = [], []
    for tid, body in answers.items():
        if tid not in run.config.tasks:
            skipped.append(f"{tid} (not a task in this run)")
            continue
        path = folder / f"task__{tid}__r{repeat}.response.md"
        if path.is_file() and path.read_text().strip() and not force:
            skipped.append(f"{tid} (already has a response; use --force to replace)")
            continue
        path.write_text(body + "\n", encoding="utf-8")
        filed.append(tid)
    missing = [t for t in run.config.tasks if t not in answers]
    return {"filed": filed, "skipped": skipped, "missing": missing}
