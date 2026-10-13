import pytest

from scorer_kit.exam import ingest_answers, parse_answers, render_exam
from scorer_kit.kit import load_kit
from scorer_kit.runner.run import create_run, grade_run, run_tasks


def test_exam_contains_prompts_but_no_gold(kit_dir):
    kit = load_kit(kit_dir)
    exam = render_exam(kit)
    for task in kit.tasks.values():
        assert f"(id: {task.id})" in exam
        assert task.input.prompt.strip().splitlines()[0] in exam
    assert '<document name="paper.md">' in exam  # attachments are inlined
    assert "Q1." in exam  # paper-digest questions are part of the prompt, by design
    pd = kit.tasks["pd-tidal-memory"].gold
    leaked = [c for c in pd["claims"] if c in exam]
    leaked += [q["reference"].strip()[:40] for q in pd["questions"] if q["reference"].strip()[:40] in exam]
    for bs in ("bs-weekend-project", "bs-follow-up-experiments"):
        g = kit.tasks[bs].gold
        leaked += [i for i in g["baseline_ideas"] if i in exam]
        leaked += [g["goal"].strip()] if g["goal"].strip() in exam else []
    assert leaked == []


def test_parse_answers_tolerates_markdown_and_missing_end():
    reply = """Sure, here you go.

**=== ANSWER pd-tidal-memory ===**
## Summary
Answer correctness matters here.
=== END ANSWER ===

=== ANSWER bs-weekend-project ===
```
1. Idea one
2. Idea two
```
=== ANSWER bs-follow-up-experiments ===
1. Ablate the cap
"""
    a = parse_answers(reply)
    assert set(a) == {"pd-tidal-memory", "bs-weekend-project", "bs-follow-up-experiments"}
    assert "Answer correctness" in a["pd-tidal-memory"]
    assert a["bs-weekend-project"] == "1. Idea one\n2. Idea two"
    assert a["bs-follow-up-experiments"] == "1. Ablate the cap"


def test_ingest_flows_into_run(kit_dir, tmp_path):
    run = create_run(kit_dir, ["app:Grok", "mock:beta"], ["mock:judge"], 1, tmp_path / "r",
                     task_ids=["bs-weekend-project", "bs-follow-up-experiments"])
    run_tasks(run)
    reply = ("=== ANSWER bs-weekend-project ===\n1. A\n2. B\n=== END ANSWER ===\n"
             "=== ANSWER not-a-task ===\nx\n=== END ANSWER ===\n")
    r = ingest_answers(run, "app:Grok", 1, reply)
    assert r["filed"] == ["bs-weekend-project"]
    assert r["missing"] == ["bs-follow-up-experiments"]
    assert "not-a-task" in r["skipped"][0]
    assert run_tasks(run).new == 1
    # no silent overwrite
    again = ingest_answers(run, "app:Grok", 1, reply)
    assert again["filed"] == [] and any("already has a response" in x for x in again["skipped"])

    ingest_answers(run, "app:Grok", 1, "=== ANSWER bs-follow-up-experiments ===\n1. C\n")
    run_tasks(run)
    assert grade_run(run).new == 4


def test_ingest_rejects_wrong_model_or_repeat(kit_dir, tmp_path):
    run = create_run(kit_dir, ["app:Grok"], ["mock:judge"], 1, tmp_path / "r")
    with pytest.raises(ValueError, match="not in this run"):
        ingest_answers(run, "app:Gemini", 1, "")
    with pytest.raises(ValueError, match="repeat"):
        ingest_answers(run, "app:Grok", 2, "")
