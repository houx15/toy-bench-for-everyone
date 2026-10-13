"""Dependency-free text similarity for idea novelty and diversity.

Character trigram vectors with cosine similarity: crude next to neural embeddings, but
deterministic, free, offline, and good enough to tell "same idea reworded" from "different
idea". Scores are meaningful relative to each other within a run, not as absolute values.
"""

from __future__ import annotations

import math
import re
from collections import Counter

Vector = Counter


def embed(text: str) -> Vector:
    t = " " + re.sub(r"[^a-z0-9]+", " ", text.lower()).strip() + " "
    return Counter(t[i : i + 3] for i in range(len(t) - 2))


def cosine(a: Vector, b: Vector) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    return dot / (math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values())))


def novelty(ideas: list[str], pool: list[str]) -> list[float]:
    """Per idea: 1 - similarity to its nearest neighbour in the baseline pool."""
    pool_vecs = [embed(p) for p in pool]
    return [1.0 - max((cosine(embed(i), p) for p in pool_vecs), default=0.0) for i in ideas]


def leader_clusters(ideas: list[str], threshold: float) -> list[list[int]]:
    """Greedy clustering: an idea joins the first cluster whose leader it resembles."""
    vecs = [embed(i) for i in ideas]
    clusters: list[list[int]] = []
    for idx, v in enumerate(vecs):
        for c in clusters:
            if cosine(v, vecs[c[0]]) >= threshold:
                c.append(idx)
                break
        else:
            clusters.append([idx])
    return clusters
