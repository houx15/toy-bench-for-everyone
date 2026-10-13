"""Load a personal kit folder (profile, tasks, recipes) and validate it as a whole."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from scorer_kit.schemas import Profile, Recipe, Task

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILTIN_RECIPES = REPO_ROOT / "recipes"


class KitError(Exception):
    """A kit file is missing or invalid; the message says which and why."""


def read_yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise KitError(f"missing file: {path}") from e
    except yaml.YAMLError as e:
        raise KitError(f"{path}: invalid YAML: {e}") from e
    if not isinstance(data, dict):
        raise KitError(f"{path}: expected a mapping at the top level")
    return data


def _parse(model, path: Path):
    try:
        return model.model_validate(read_yaml(path))
    except ValidationError as e:
        raise KitError(f"{path}:\n{e}") from e


def load_recipe(path: Path) -> Recipe:
    return _parse(Recipe, path)


def load_recipes(*dirs: Path) -> dict[str, Recipe]:
    """Later directories override earlier ones, so a kit can customize a built-in recipe."""
    recipes: dict[str, Recipe] = {}
    for d in dirs:
        if d.is_dir():
            for p in sorted(d.glob("*.yaml")):
                r = load_recipe(p)
                recipes[r.id] = r
    return recipes


@dataclass
class Kit:
    root: Path
    profile: Profile
    tasks: dict[str, Task]
    recipes: dict[str, Recipe]
    task_dirs: dict[str, Path] = field(default_factory=dict)

    def attachment_text(self, task: Task) -> list[tuple[str, str]]:
        base = self.task_dirs[task.id]
        return [(name, (base / name).read_text(encoding="utf-8")) for name in task.input.attachments]

    def context_pack_text(self) -> str | None:
        if not self.profile.context_pack:
            return None
        return (self.root / self.profile.context_pack).read_text(encoding="utf-8")

    def recipe_for(self, task: Task) -> Recipe:
        return self.recipes[task.recipe]


def load_kit(root: Path | str) -> Kit:
    from scorer_kit.graders import REGISTRY  # local import: graders import schemas, not kit

    root = Path(root).resolve()
    if not root.is_dir():
        raise KitError(f"kit folder not found: {root}")
    profile = _parse(Profile, root / "profile.yaml")
    recipes = load_recipes(BUILTIN_RECIPES, root / "recipes")

    tasks: dict[str, Task] = {}
    task_dirs: dict[str, Path] = {}
    problems: list[str] = []
    bucket_ids = {b.id for b in profile.buckets}

    for path in sorted((root / "tasks").rglob("*.yaml")):
        try:
            task = _parse(Task, path)
        except KitError as e:
            problems.append(str(e))
            continue
        if task.id in tasks:
            problems.append(f"{path}: duplicate task id {task.id!r}")
        if task.bucket not in bucket_ids:
            problems.append(f"{path}: bucket {task.bucket!r} not in profile ({sorted(bucket_ids)})")
        recipe = recipes.get(task.recipe)
        if recipe is None:
            problems.append(f"{path}: unknown recipe {task.recipe!r} (have {sorted(recipes)})")
        elif recipe.grader not in REGISTRY:
            problems.append(f"recipe {recipe.id}: unknown grader {recipe.grader!r}")
        else:
            try:
                REGISTRY[recipe.grader].gold_model.model_validate(task.gold)
            except ValidationError as e:
                problems.append(f"{path}: gold does not fit recipe {recipe.id}:\n{e}")
        for name in task.input.attachments:
            if not (path.parent / name).is_file():
                problems.append(f"{path}: attachment not found: {name}")
        tasks[task.id] = task
        task_dirs[task.id] = path.parent

    if not tasks and not problems:
        problems.append(f"{root / 'tasks'}: no task files found")
    if profile.context_pack and not (root / profile.context_pack).is_file():
        problems.append(f"context_pack not found: {profile.context_pack}")
    if problems:
        raise KitError("kit has problems:\n- " + "\n- ".join(problems))
    return Kit(root=root, profile=profile, tasks=tasks, recipes=recipes, task_dirs=task_dirs)
