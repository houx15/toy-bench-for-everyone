"""End-to-end with the offline mock backend and the app handoff backend."""

import httpx
import pytest
import yaml

from scorer_kit.calibration import judge_trust, make_sheet, score_sheet
from scorer_kit.report.build import build_report, summarize
from scorer_kit.runner.backends import ModelSpec, OpenAICompatBackend
from scorer_kit.runner.run import Run, create_run, grade_run, pick_judge, run_tasks, task_messages
from scorer_kit.schemas import Job, Message

MODELS = ["mock:alpha", "mock:beta"]
JUDGES = ["mock:judge"]


def test_model_spec_parsing():
    s = ModelSpec.parse("openrouter:anthropic/claude-opus-5-5")
    assert s.provider == "openrouter" and s.slug == "openrouter_anthropic_claude-opus-5-5"
    with pytest.raises(ValueError):
        ModelSpec.parse("gpt-4")


def test_never_self_grades(kit_dir, tmp_path):
    assert pick_judge("mock:a", ["mock:a", "mock:b"]) == "mock:b"
    with pytest.raises(ValueError, match="never grades its own"):
        create_run(kit_dir, ["mock:a"], ["mock:a"], 1, tmp_path / "results")
    with pytest.raises(ValueError, match="need an AI judge"):
        create_run(kit_dir, ["mock:a"], [], 1, tmp_path / "results")


def test_task_prompt_contains_document_questions_and_format(kit_dir, tmp_path):
    run = create_run(kit_dir, MODELS, JUDGES, 1, tmp_path / "results")
    msgs = task_messages(run.kit, run.kit.tasks["pd-tidal-memory"])
    text = msgs[-1].content
    assert '<document name="paper.md">' in text and "Q2." in text and "## Key claims" in text


def test_mock_run_grade_report_calibrate(kit_dir, tmp_path):
    run = create_run(kit_dir, MODELS, JUDGES, 2, tmp_path / "results", run_id="t1")
    p = run_tasks(run)
    assert p.new == 3 * 2 * 2 and not p.errors
    g = grade_run(run)
    assert g.new == 12 and not g.errors

    # resumable: nothing new the second time
    assert run_tasks(run).new == 0 and grade_run(run).new == 0

    grade = Run.load(run.dir).read_grade("mock:alpha", "pd-tidal-memory", 1)
    assert grade.judge_model == "mock:judge" and 0 <= grade.score <= 1

    data = summarize(run)
    assert {m.spec for m in data["models"]} == set(MODELS)
    assert all(m.fit is not None and m.persona for m in data["models"])
    assert abs(data["models"][0].coverage - 0.65) < 1e-9  # 3 of 5 buckets tested
    html = build_report(run).read_text()
    assert "Team roster" in html and "Judge not yet calibrated" in html

    # calibration: a user who agrees with the judge perfectly -> trusted
    sheet = make_sheet(run, "paper-digest", sample_size=6)
    s = yaml.safe_load(sheet.read_text())
    key = {k["id"]: k for k in yaml.safe_load((sheet.parent / "key.yaml").read_text())["items"]}
    for item in s["items"]:
        item["user_label"] = key[item["id"]]["judge_label"]
        assert "mock:" not in item["output"]  # outputs are anonymized
    sheet.write_text(yaml.safe_dump(s))
    result = score_sheet(sheet)
    assert result["unlabelled_items"] == 0
    assert result["criteria"]["claim_coverage"]["status"] == "trusted"
    assert judge_trust(run.kit.root, "paper-digest")["claim_coverage"] == "trusted"


def test_app_handoff_round_trip(kit_dir, tmp_path):
    run = create_run(kit_dir, ["app:ChatGPT", "mock:beta"], JUDGES, 1, tmp_path / "results",
                     task_ids=["bs-weekend-project"])
    p = run_tasks(run)
    assert p.pending == 1 and p.new == 1
    assert "app_ChatGPT" in (run.dir / "HANDOFF.md").read_text()
    # grading waits until every model has answered (novelty compares against peers)
    assert grade_run(run).waiting == 1

    prompt = run.dir / "handoff" / "app_ChatGPT" / "task__bs-weekend-project__r1.prompt.md"
    assert "Brainstorm weekend side projects" in prompt.read_text()
    prompt.with_name("task__bs-weekend-project__r1.response.md").write_text(
        "1. Model diary: log every prompt\n2. Blind taste test for answers\n")
    p = run_tasks(run)
    assert p.new == 1 and p.pending == 0
    assert grade_run(run).new == 2


def test_app_judge_handoff(kit_dir, tmp_path):
    run = create_run(kit_dir, ["mock:alpha"], ["app:Claude"], 1, tmp_path / "results",
                     task_ids=["bs-weekend-project"])
    run_tasks(run)
    assert grade_run(run).pending == 1
    folder = run.dir / "handoff" / "app_Claude"
    (folder / "judge__mock_alpha__bs-weekend-project__r1.response.md").write_text(
        'Here you go:\n```json\n{"usefulness": 2, "best_idea": 1}\n```')
    assert grade_run(run).new == 1
    assert run.read_grade("mock:alpha", "bs-weekend-project", 1).criteria["usefulness"] == 0.5


def test_openai_compat_backend_parses_usage_and_retries(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, text="slow down")
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "hello"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.0012},
        })

    backend = OpenAICompatBackend("openrouter", "https://example.test/v1", "k",
                                  client=httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr("scorer_kit.runner.backends.time.sleep", lambda s: None)
    r = backend.call(Job(id="j", kind="task", model="openrouter:x/y",
                         messages=[Message(role="user", content="hi")]))
    assert r.status == "ok" and r.text == "hello" and r.cost_usd == 0.0012 and r.input_tokens == 10
    assert len(calls) == 2
    assert calls[-1].headers["authorization"] == "Bearer k"


def test_openai_compat_backend_does_not_retry_client_errors():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401, text="bad key")

    backend = OpenAICompatBackend("bailian", "https://example.test/v1", "k",
                                  client=httpx.Client(transport=httpx.MockTransport(handler)))
    r = backend.call(Job(id="j", kind="task", model="bailian:qwen-max",
                         messages=[Message(role="user", content="hi")]))
    assert r.status == "error" and "401" in r.error and len(calls) == 1
