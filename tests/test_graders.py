import json

import pytest

from scorer_kit.graders import REGISTRY, similarity
from scorer_kit.graders.base import GradeContext, JudgeParseError, combine, fill, parse_judge_json
from scorer_kit.graders.brainstorming import parse_ideas
from scorer_kit.kit import load_kit


def test_fill_leaves_single_braces_alone():
    assert fill('{"a": 1} {{x}}', x="hi") == '{"a": 1} hi'
    with pytest.raises(KeyError):
        fill("{{missing}}")


def test_parse_judge_json_variants():
    assert parse_judge_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_judge_json('Sure! {"a": {"b": 2}} hope this helps') == {"a": {"b": 2}}
    with pytest.raises(JudgeParseError):
        parse_judge_json("no json here")


def test_paper_digest_scoring(kit_dir):
    kit = load_kit(kit_dir)
    task = kit.tasks["pd-tidal-memory"]
    recipe = kit.recipe_for(task)
    n = len(task.gold["claims"])
    verdicts = ["covered"] * (n - 2) + ["partial", "missing"]
    reply = json.dumps({
        "claims": [{"id": i + 1, "verdict": v} for i, v in enumerate(verdicts)],
        "answers": [{"id": 1, "score": 2}, {"id": 2, "score": 1}],
        "raised_questions_quality": 3,
        "unsupported_claims": ["made-up number"],
    })
    output = "## Summary\n...\n## Key claims\n...\n## Answers\n...\n## Questions I would raise\n..."
    g = REGISTRY["paper_digest"].grade(task, recipe, output, reply, GradeContext())
    assert g.criteria["claim_coverage"] == pytest.approx((n - 2 + 0.5) / n)
    assert g.criteria["answers"] == pytest.approx(0.75)
    assert g.criteria["raised_questions"] == 1.0
    assert g.criteria["faithfulness"] == pytest.approx(0.75)
    assert g.criteria["format"] == 1.0
    assert "hallucinations:1" in g.flags
    score, missing = combine(recipe, g.criteria)
    assert 0 < score < 1 and missing == []


def test_paper_digest_without_judge_flags_missing_criteria(kit_dir):
    kit = load_kit(kit_dir)
    task = kit.tasks["pd-tidal-memory"]
    recipe = kit.recipe_for(task)
    g = REGISTRY["paper_digest"].grade(task, recipe, "## Summary only", None, GradeContext())
    _, missing = combine(recipe, g.criteria)
    assert "no-judge" in g.flags and "missing-criterion:claim_coverage" in missing


def test_parse_ideas():
    assert parse_ideas("1. A: x\n2) B: y\n- C\nnot an idea") == ["A: x", "B: y", "C"]
    assert parse_ideas("First idea\n\nSecond idea") == ["First idea", "Second idea"]


def test_novelty_is_zero_for_copied_idea_and_clusters_merge_rewordings():
    assert similarity.novelty(["build a podcast"], ["build a podcast"])[0] == pytest.approx(0)
    assert similarity.novelty(["quantum gardening"], ["build a podcast"])[0] > 0.5
    clusters = similarity.leader_clusters(
        ["weekly podcast about AI", "a weekly AI podcast", "soil sensor kit"], threshold=0.5)
    assert len(clusters) == 2


def test_brainstorm_uses_peers_as_baseline_but_not_itself(kit_dir):
    kit = load_kit(kit_dir)
    task = kit.tasks["bs-weekend-project"]
    recipe = kit.recipe_for(task)
    output = "1. Personal leaderboard of models on my prompts\n2. Soil moisture sonification"
    alone = REGISTRY["brainstorming"].grade(task, recipe, output, '{"usefulness": 3}', GradeContext())
    copied = REGISTRY["brainstorming"].grade(task, recipe, output, '{"usefulness": 3}',
                                              GradeContext(peer_outputs=[output]))
    assert copied.criteria["novelty"] < alone.criteria["novelty"]
    assert alone.criteria["usefulness"] == 1.0
    assert alone.criteria["count"] == pytest.approx(0.2)
