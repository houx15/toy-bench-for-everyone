"""Aggregate grades into the scored report: persona card, usage-weighted fit, radar,
use for / don't use for, highlight reel, cost/speed/consistency, team roster.

Every number traces back to task-level files: the report links each headline to the
output and grade JSON it came from.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from scorer_kit.calibration import judge_trust
from scorer_kit.report.personas import Persona, assign
from scorer_kit.runner.backends import ModelSpec
from scorer_kit.runner.run import Run

TEMPLATE_DIR = Path(__file__).parent
SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)"]
MARGIN = 0.05  # bucket-score gap that counts as a real difference in use for / avoid


@dataclass
class Cell:
    task_id: str
    repeat: int
    score: float
    criteria: dict[str, float]
    flags: list[str]
    output_href: str
    grade_href: str


@dataclass
class ModelSummary:
    spec: str
    label: str
    cells: list[Cell] = field(default_factory=list)
    task_scores: dict[str, float] = field(default_factory=dict)
    task_spread: dict[str, float] = field(default_factory=dict)
    bucket_scores: dict[str, float] = field(default_factory=dict)
    recipe_scores: dict[str, float] = field(default_factory=dict)
    fit: float | None = None
    coverage: float = 0.0
    persona: Persona | None = None
    use_for: list[str] = field(default_factory=list)
    avoid_for: list[str] = field(default_factory=list)
    cost_total: float | None = None
    cost_per_call: float | None = None
    latency_mean: float | None = None
    output_tokens_mean: float | None = None
    consistency: float | None = None  # mean std-dev of score across repeats
    errors: int = 0
    best: Cell | None = None
    worst: Cell | None = None
    # presentation, filled in by build_report
    color: str = ""
    radar: str | None = None
    bars: list = field(default_factory=list)
    best_excerpt: str = ""
    worst_excerpt: str = ""


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def summarize(run: Run) -> dict:
    kit, cfg = run.kit, run.config
    profile = kit.profile
    models: dict[str, ModelSummary] = {}

    for spec in cfg.models:
        m = ModelSummary(spec=spec, label=ModelSpec.parse(spec).name)
        costs, latencies, toks = [], [], []
        per_task: dict[str, list[float]] = {}
        for task in run.tasks():
            for r in range(1, cfg.repeats + 1):
                out = run.read_output(spec, task.id, r)
                if out is None:
                    continue
                if out.result.status != "ok":
                    m.errors += 1
                    continue
                costs.append(out.result.cost_usd)
                latencies.append(out.result.latency_s)
                toks.append(out.result.output_tokens)
                g = run.read_grade(spec, task.id, r)
                if g is None:
                    continue
                out_path = run.output_path(spec, task.id, r)
                cell = Cell(task.id, r, g.score, g.criteria, g.flags,
                            str(out_path.with_suffix(".md").relative_to(run.dir)),
                            str(run.grade_path(spec, task.id, r).relative_to(run.dir)))
                m.cells.append(cell)
                per_task.setdefault(task.id, []).append(g.score)
        for tid, scores in per_task.items():
            m.task_scores[tid] = sum(scores) / len(scores)
            m.task_spread[tid] = statistics.pstdev(scores) if len(scores) > 1 else 0.0
        m.consistency = _mean(m.task_spread.values())
        known_costs = [c for c in costs if c is not None]
        m.cost_total = sum(known_costs) if known_costs else None
        m.cost_per_call = _mean(known_costs)
        m.latency_mean = _mean(latencies)
        m.output_tokens_mean = _mean(toks)
        if m.cells:
            m.best = max(m.cells, key=lambda c: c.score)
            m.worst = min(m.cells, key=lambda c: c.score)

        for level, key in (("bucket", "bucket"), ("recipe", "recipe")):
            acc: dict[str, list[tuple[float, float]]] = {}
            for tid, s in m.task_scores.items():
                t = kit.tasks[tid]
                acc.setdefault(getattr(t, key), []).append((s, t.weight))
            target = m.bucket_scores if level == "bucket" else m.recipe_scores
            for k, pairs in acc.items():
                target[k] = sum(s * w for s, w in pairs) / sum(w for _, w in pairs)

        share = {b.id: b.usage_share for b in profile.buckets}
        covered = {b: s for b, s in m.bucket_scores.items() if share.get(b, 0) > 0}
        m.coverage = sum(share[b] for b in covered)
        if covered:
            m.fit = sum(share[b] * s for b, s in covered.items()) / m.coverage
        models[spec] = m

    # field averages, personas, use-for/avoid
    def field_mean(attr: str, key: str) -> float | None:
        return _mean([getattr(m, attr).get(key) for m in models.values()])

    recipes = sorted({k for m in models.values() for k in m.recipe_scores})
    recipe_field = {r: field_mean("recipe_scores", r) for r in recipes}
    bucket_ids = [b.id for b in profile.buckets
                  if any(b.id in m.bucket_scores for m in models.values())]
    bucket_field = {b: field_mean("bucket_scores", b) for b in bucket_ids}
    for m in models.values():
        m.persona = assign(m.recipe_scores, recipe_field)
        if len(models) > 1:
            for b in bucket_ids:
                if b not in m.bucket_scores:
                    continue
                others = [o.bucket_scores[b] for o in models.values()
                          if o is not m and b in o.bucket_scores]
                if not others:
                    continue
                name = profile.bucket(b).name
                if m.bucket_scores[b] >= max(others) + MARGIN:
                    m.use_for.append(name)
                elif m.bucket_scores[b] <= min(others) - MARGIN:
                    m.avoid_for.append(name)

    roster = []
    for b in bucket_ids:
        ranked = sorted((m for m in models.values() if b in m.bucket_scores),
                        key=lambda m: m.bucket_scores[b], reverse=True)
        top = ranked[0]
        margin = top.bucket_scores[b] - ranked[1].bucket_scores[b] if len(ranked) > 1 else None
        roster.append({
            "bucket": profile.bucket(b), "model": top, "score": top.bucket_scores[b],
            "margin": margin, "close_call": margin is not None and margin < MARGIN,
        })

    ordered = sorted(models.values(), key=lambda m: (m.fit is None, -(m.fit or 0)))
    favorite = models.get(profile.current_favorite or "") or (ordered[0] if ordered else None)
    for i, m in enumerate(cfg.models):
        models[m].color = SERIES[i] if i < len(SERIES) else "var(--text-muted)"

    trust = {}
    for r in recipes:
        status = judge_trust(kit.root, r)
        judge_criteria = [c.id for c in kit.recipes[r].criteria if c.source == "judge"]
        trust[r] = {c: status.get(c, "uncalibrated") for c in judge_criteria}

    return {
        "run": cfg, "profile": profile, "models": ordered, "favorite": favorite,
        "bucket_ids": bucket_ids, "bucket_field": bucket_field, "roster": roster,
        "trust": trust, "tasks": run.tasks(), "recipes": {r: kit.recipes[r] for r in recipes},
    }


# ---------------------------------------------------------------- radar


def radar_svg(axes: list[str], series: list[tuple[str, str, list[float | None]]],
              size: int = 320) -> str:
    """Inline SVG radar, scores 0-1. series = (label, css colour, values per axis)."""
    cx = cy = size / 2
    radius = size / 2 - 64
    n = len(axes)

    def point(i: int, v: float) -> tuple[float, float]:
        a = -math.pi / 2 + 2 * math.pi * i / n
        return cx + radius * v * math.cos(a), cy + radius * v * math.sin(a)

    pad = 80  # room for axis labels left and right
    parts = [f'<svg viewBox="{-pad} 0 {size + 2 * pad} {size}" class="radar" role="img" '
             f'aria-label="Radar of scores per usage bucket">']
    for ring in (0.25, 0.5, 0.75, 1.0):
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (point(i, ring) for i in range(n)))
        parts.append(f'<polygon points="{pts}" class="grid"/>')
    for i, label in enumerate(axes):
        x, y = point(i, 1.0)
        lx, ly = point(i, 1.18)
        anchor = "middle" if abs(lx - cx) < 8 else ("start" if lx > cx else "end")
        parts.append(f'<line x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" class="grid"/>')
        parts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" '
                     f'dominant-baseline="middle" class="axis-label">{_esc(label)}</text>')
    for label, color, values in series:
        pts = [point(i, v or 0) for i, v in enumerate(values)]
        poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        parts.append(f'<polygon points="{poly}" fill="{color}" fill-opacity="0.12" '
                     f'stroke="{color}" stroke-width="2" stroke-linejoin="round"/>')
        for (x, y), axis, v in zip(pts, axes, values):
            shown = "no data" if v is None else f"{v:.2f}"
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{color}" '
                         f'stroke="var(--surface)" stroke-width="2"><title>{_esc(label)} — '
                         f'{_esc(axis)}: {shown}</title></circle>')
    parts.append("</svg>")
    return "".join(parts)


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ---------------------------------------------------------------- render


def excerpt(run: Run, cell: Cell | None, limit: int = 420) -> str:
    if cell is None:
        return ""
    text = (run.dir / cell.output_href).read_text(encoding="utf-8").strip()
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " …"


def build_report(run: Run, out: Path | None = None) -> Path:
    data = summarize(run)
    profile = data["profile"]
    names = {b.id: b.name for b in profile.buckets}
    axes = [names[b] for b in data["bucket_ids"]]
    fav = data["favorite"]

    for m in data["models"]:
        series = [(m.label, m.color, [m.bucket_scores.get(b) for b in data["bucket_ids"]])]
        if fav is not None and fav is not m:
            series.insert(0, (fav.label, fav.color,
                              [fav.bucket_scores.get(b) for b in data["bucket_ids"]]))
        m.radar = radar_svg(axes, series) if len(axes) >= 3 else None
        m.bars = [(names[b], [(s[0], s[1], s[2][i]) for s in series])
                  for i, b in enumerate(data["bucket_ids"])]
        m.best_excerpt = excerpt(run, m.best)
        m.worst_excerpt = excerpt(run, m.worst)

    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(["html"]))
    env.filters["pct"] = lambda v: "—" if v is None else f"{v * 100:.0f}"
    env.filters["num"] = lambda v, d=2: "—" if v is None else f"{v:.{d}f}"
    env.filters["money"] = lambda v: "—" if v is None else (f"${v:.4f}" if v < 0.01 else f"${v:.2f}")
    html = env.get_template("template.html").render(**data, kit_tasks=run.kit.tasks)
    out = out or run.dir / "report.html"
    out.write_text(html, encoding="utf-8")
    return out
