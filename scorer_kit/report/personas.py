"""Job personas: the nearest role to a model's strength profile.

Roles are fixed for now (open question in CLAUDE.md: fixed vs generated per user). Each
role lists how much each recipe counts toward it. A model's strength on a recipe is its
score minus the field average, so a persona says what a model is *relatively* good at
among the models you tested, not that it is good in absolute terms.
"""

from __future__ import annotations

from dataclasses import dataclass

ROLES: dict[str, dict[str, float]] = {
    "Research Analyst": {"paper-digest": 1.0, "literature-review": 1.0, "report-writing": 0.6},
    "Senior Engineer": {"coding": 1.0, "architecture": 1.0},
    "Creative Strategist": {"brainstorming": 1.0, "ui-design": 0.8},
    "Editor": {"paper-rewrite": 1.0, "report-writing": 0.6},
}
GENERALIST = "Generalist"
GENERALIST_MARGIN = 0.03  # strengths smaller than this are noise at 3 repeats

TAGLINES = {
    "Research Analyst": "Reads closely, keeps the facts straight.",
    "Senior Engineer": "Ships code that passes the tests.",
    "Creative Strategist": "Goes wide and finds the unexpected angle.",
    "Editor": "Improves the text without losing your voice.",
    GENERALIST: "No standout specialty among the models you tested — solid across the board.",
}


@dataclass
class Persona:
    role: str
    tagline: str
    strength: float
    evidence_recipe: str | None


def assign(recipe_scores: dict[str, float], field_means: dict[str, float]) -> Persona:
    """recipe_scores: this model's mean score per recipe; field_means: all models' mean."""
    advantage = {r: s - field_means.get(r, s) for r, s in recipe_scores.items()}
    best_role, best_value, best_recipe = GENERALIST, 0.0, None
    for role, affinities in ROLES.items():
        relevant = {r: w for r, w in affinities.items() if r in advantage}
        if not relevant:
            continue
        value = sum(w * advantage[r] for r, w in relevant.items()) / sum(relevant.values())
        if value > best_value:
            best_role, best_value = role, value
            best_recipe = max(relevant, key=lambda r: relevant[r] * advantage[r])
    if best_value < GENERALIST_MARGIN:
        return Persona(GENERALIST, TAGLINES[GENERALIST], best_value, None)
    return Persona(best_role, TAGLINES[best_role], best_value, best_recipe)
