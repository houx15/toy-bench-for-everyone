"""Graders: automatic checks plus judge prompts/parsing, one per recipe family."""

from scorer_kit.graders.base import Grader
from scorer_kit.graders.brainstorming import BrainstormGrader
from scorer_kit.graders.paper_digest import PaperDigestGrader

REGISTRY: dict[str, Grader] = {g.name: g for g in (PaperDigestGrader(), BrainstormGrader())}
