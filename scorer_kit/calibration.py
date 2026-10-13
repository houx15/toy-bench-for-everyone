"""Judge calibration: before an AI judge is trusted on a recipe, it labels ~20 things the
user also labelled (blind), and we measure agreement.

- categorical labels -> Cohen's kappa
- ordinal labels     -> quadratic-weighted Cohen's kappa (near-misses count as partial agreement)
- numeric values     -> Pearson and Spearman correlation
"""

from __future__ import annotations

import math
import random
from collections.abc import Hashable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml

from scorer_kit.graders import REGISTRY

# ---------------------------------------------------------------- math


def cohen_kappa(a: Sequence[Hashable], b: Sequence[Hashable],
                labels: Sequence[Hashable] | None = None,
                weights: Literal[None, "linear", "quadratic"] = None) -> float:
    """Cohen's kappa between two raters. With ``weights`` the labels must be ordered
    (given by ``labels``, or sorted). If both raters always use one identical label,
    chance agreement is total and kappa is defined here as 1.0 (0.0 if they differ)."""
    if len(a) != len(b):
        raise ValueError("raters must label the same number of items")
    if not a:
        raise ValueError("no items")
    labels = list(labels) if labels is not None else sorted(set(a) | set(b), key=str)
    idx = {lab: i for i, lab in enumerate(labels)}
    unknown = (set(a) | set(b)) - set(idx)
    if unknown:
        raise ValueError(f"labels not in label set: {unknown}")
    k, n = len(labels), len(a)

    def w(i: int, j: int) -> float:  # disagreement weight
        if weights is None:
            return 0.0 if i == j else 1.0
        d = abs(i - j) / (k - 1) if k > 1 else 0.0
        return d if weights == "linear" else d * d

    observed = [[0.0] * k for _ in range(k)]
    for x, y in zip(a, b):
        observed[idx[x]][idx[y]] += 1 / n
    pa = [sum(row) for row in observed]
    pb = [sum(observed[i][j] for i in range(k)) for j in range(k)]
    do = sum(w(i, j) * observed[i][j] for i in range(k) for j in range(k))
    de = sum(w(i, j) * pa[i] * pb[j] for i in range(k) for j in range(k))
    if de == 0:
        return 1.0 if do == 0 else 0.0
    return 1.0 - do / de


def pearson(x: Sequence[float], y: Sequence[float]) -> float:
    if len(x) != len(y) or len(x) < 2:
        raise ValueError("need two equal-length sequences with at least 2 values")
    mx, my = sum(x) / len(x), sum(y) / len(y)
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sx = math.sqrt(sum((a - mx) ** 2 for a in x))
    sy = math.sqrt(sum((b - my) ** 2 for b in y))
    if sx == 0 or sy == 0:
        return float("nan")  # a constant rater carries no correlational information
    return sxy / (sx * sy)


def _ranks(v: Sequence[float]) -> list[float]:
    order = sorted(range(len(v)), key=lambda i: v[i])
    ranks = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        for t in range(i, j + 1):
            ranks[order[t]] = (i + j) / 2 + 1  # ties share the average rank
        i = j + 1
    return ranks


def spearman(x: Sequence[float], y: Sequence[float]) -> float:
    return pearson(_ranks(x), _ranks(y))


def agreement(kind: str, judge: list, user: list, allowed: list | None = None) -> dict:
    if kind == "categorical":
        return {"metric": "kappa", "value": cohen_kappa(user, judge, labels=allowed)}
    if kind == "ordinal":
        j = [float(v) for v in judge]
        u = [float(v) for v in user]
        labels = sorted({float(v) for v in (allowed or [])} | set(j) | set(u))
        return {"metric": "weighted_kappa",
                "value": cohen_kappa(u, j, labels=labels, weights="quadratic")}
    j = [float(v) for v in judge]
    u = [float(v) for v in user]
    return {"metric": "pearson", "value": pearson(u, j), "spearman": spearman(u, j)}


# ---------------------------------------------------------------- blind grading sheets


def make_sheet(run, recipe_id: str, sample_size: int | None = None, seed: int = 0) -> Path:
    """Sample judge-labelled units from a graded run into a blind sheet for the user.

    Outputs are copied under anonymous names so the user cannot see which model wrote
    them; the judge's labels go into a separate key file the user should not open.
    """
    recipe = run.kit.recipes[recipe_id]
    grader = REGISTRY[recipe.grader]
    n = sample_size or recipe.calibration.sample_size
    rng = random.Random(seed)

    graded = []
    for task, model, r in run.cells():
        if task.recipe != recipe_id:
            continue
        g = run.read_grade(model, task.id, r)
        if g:
            graded.append((task, model, r, g))
    if not graded:
        raise ValueError(f"no graded outputs for recipe {recipe_id} in run {run.config.run_id}")

    units_by_criterion: dict[str, list] = {}
    for task, model, r, g in graded:
        for u in grader.calibration_units(recipe, g.details):
            units_by_criterion.setdefault(u.criterion, []).append((task, model, r, u))

    sheet_dir = run.kit.root / "calibration" / f"{recipe_id}-{run.config.run_id}"
    if (sheet_dir / "sheet.yaml").exists():
        raise FileExistsError(f"sheet already exists (fill it in or delete it): {sheet_dir}")
    (sheet_dir / "outputs").mkdir(parents=True, exist_ok=True)

    anon: dict[tuple, str] = {}
    items, key = [], []
    for criterion, units in units_by_criterion.items():
        rng.shuffle(units)
        for task, model, r, u in units[:n]:
            cell = (task.id, model, r)
            if cell not in anon:
                anon[cell] = f"o{len(anon) + 1:02d}.md"
                text = run.output_path(model, task.id, r).with_suffix(".md").read_text()
                (sheet_dir / "outputs" / anon[cell]).write_text(text)
            item_id = f"u{len(items) + 1:03d}"
            c = recipe.criterion(criterion)
            items.append({
                "id": item_id, "criterion": criterion, "task": task.id,
                "output": f"outputs/{anon[cell]}", "question": u.question,
                "kind": u.kind, "allowed": u.allowed, "anchors": c.scale.anchors or None,
                "user_label": None,
            })
            key.append({"id": item_id, "judge_label": u.judge_label, "model": model,
                        "repeat": r, "unit": u.key})

    rng.shuffle(items)
    header = {
        "recipe": recipe_id, "run": run.config.run_id, "created": datetime.now().isoformat(timespec="seconds"),
        "instructions": (
            "Open each item's output file, answer the question, and write your answer in "
            "user_label. Use the gold material in your task file for reference. Do not open "
            "key.yaml until you are done. Then run: scorer calibrate <this file>"
        ),
        "items": items,
    }
    (sheet_dir / "sheet.yaml").write_text(yaml.safe_dump(header, sort_keys=False, allow_unicode=True))
    (sheet_dir / "key.yaml").write_text(yaml.safe_dump({"items": key}, sort_keys=False))
    return sheet_dir / "sheet.yaml"


def score_sheet(sheet_path: Path | str, kit_root: Path | None = None) -> dict:
    """Compare the user's labels with the judge's and record whether the judge is trusted."""
    from scorer_kit.kit import load_kit

    sheet_path = Path(sheet_path)
    sheet = yaml.safe_load(sheet_path.read_text())
    key = {k["id"]: k for k in yaml.safe_load((sheet_path.parent / "key.yaml").read_text())["items"]}
    kit_root = kit_root or sheet_path.parent.parent.parent
    recipe = load_kit(kit_root).recipes[sheet["recipe"]]

    by_criterion: dict[str, dict] = {}
    unlabelled = 0
    for item in sheet["items"]:
        if item.get("user_label") is None:
            unlabelled += 1
            continue
        c = by_criterion.setdefault(item["criterion"], {
            "kind": item["kind"], "allowed": item.get("allowed"), "judge": [], "user": []})
        user = item["user_label"]
        if item["kind"] == "categorical":
            user = str(user).strip().lower()
        c["judge"].append(key[item["id"]]["judge_label"])
        c["user"].append(user)

    results = {}
    for criterion, c in by_criterion.items():
        n = len(c["user"])
        if n < 2:
            results[criterion] = {"n": n, "status": "too-few-labels"}
            continue
        a = agreement(c["kind"], c["judge"], c["user"], c["allowed"])
        threshold = (recipe.calibration.min_correlation if a["metric"] == "pearson"
                     else recipe.calibration.min_kappa)
        value = a["value"]
        trusted = not math.isnan(value) and value >= threshold
        results[criterion] = {
            "n": n, **{k: (None if isinstance(v, float) and math.isnan(v) else round(v, 3))
                       for k, v in a.items() if k != "metric"},
            "metric": a["metric"], "threshold": threshold,
            "status": "trusted" if trusted else "needs-work",
        }

    summary = {
        "recipe": sheet["recipe"], "run": sheet["run"],
        "scored": datetime.now().isoformat(timespec="seconds"),
        "unlabelled_items": unlabelled, "criteria": results,
    }
    record = kit_root / "calibration" / f"{sheet['recipe']}.yaml"
    history = yaml.safe_load(record.read_text()) if record.is_file() else {"history": []}
    history["latest"] = summary
    history["history"].append(summary)
    record.write_text(yaml.safe_dump(history, sort_keys=False))
    return summary


def judge_trust(kit_root: Path, recipe_id: str) -> dict[str, str]:
    """criterion -> 'trusted' | 'needs-work' | 'uncalibrated', from the latest calibration."""
    record = kit_root / "calibration" / f"{recipe_id}.yaml"
    if not record.is_file():
        return {}
    latest = (yaml.safe_load(record.read_text()) or {}).get("latest", {})
    return {c: r.get("status", "uncalibrated") for c, r in latest.get("criteria", {}).items()}
