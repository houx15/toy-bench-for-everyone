import pytest
import yaml
from pydantic import ValidationError

from scorer_kit.kit import BUILTIN_RECIPES, KitError, load_kit, load_recipes
from scorer_kit.schemas import Profile, Recipe, Scale, Task


def bucket(id, share):
    return {"id": id, "name": id, "usage_share": share}


def test_profile_shares_must_sum_to_one():
    Profile(buckets=[bucket("a", 0.6), bucket("b", 0.4)])
    with pytest.raises(ValidationError, match="sum to 1"):
        Profile(buckets=[bucket("a", 0.6), bucket("b", 0.3)])


def test_profile_rejects_duplicate_buckets():
    with pytest.raises(ValidationError, match="duplicate"):
        Profile(buckets=[bucket("a", 0.5), bucket("a", 0.5)])


def test_ids_must_be_slugs():
    with pytest.raises(ValidationError, match="lowercase"):
        Profile(buckets=[bucket("Paper Reading", 1.0)])


def test_task_rejects_pdf_attachments():
    with pytest.raises(ValidationError, match="convert PDFs"):
        Task(id="t", bucket="b", recipe="r", input={"prompt": "x", "attachments": ["paper.pdf"]})


def test_scale_normalize_clips():
    s = Scale(kind="ordinal", min=1, max=3)
    assert s.normalize(1) == 0 and s.normalize(2) == 0.5 and s.normalize(9) == 1


def test_recipe_with_judge_criteria_needs_judge_prompt():
    crit = {"id": "c", "name": "c", "weight": 1, "source": "judge",
            "scale": {"kind": "numeric"}}
    with pytest.raises(ValidationError, match="no judge prompt"):
        Recipe(id="r", name="r", grader="paper_digest", criteria=[crit])


def test_builtin_recipes_load():
    recipes = load_recipes(BUILTIN_RECIPES)
    assert {"paper-digest", "brainstorming"} <= set(recipes)


def test_demo_kit_loads(kit_dir):
    kit = load_kit(kit_dir)
    assert set(kit.tasks) == {"pd-tidal-memory", "bs-weekend-project", "bs-follow-up-experiments"}


def test_kit_reports_unknown_bucket_and_bad_gold(kit_dir):
    path = kit_dir / "tasks" / "bs-weekend-project.yaml"
    data = yaml.safe_load(path.read_text())
    data["bucket"] = "nope"
    data["gold"] = {"target_count": 5}  # goal missing
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(KitError) as e:
        load_kit(kit_dir)
    assert "bucket 'nope'" in str(e.value) and "goal" in str(e.value)
