# For AI agents opening this repository

People send this repository's link to an AI agent (Codex, Claude Code, or similar) for
one of two reasons. Work out which one applies before doing anything.

## 1. "Set up my benchmark" (most common)

The user wants their own private benchmark. **Follow [SKILL.md](SKILL.md), Phase 1:
Setup**, step by step. In short:

1. Find out what they actually use AI for (their history, or an interview).
2. Design the benchmark: buckets, tasks, and recipes, plus the gold material the user writes.
3. **Present the design and your reasoning** in `DESIGN.md`, and wait for their approval.
4. Save it as their own **private** GitHub repository.
5. Produce the exam file (`EXAM.md`, which has no answers in it) that they will give to the models they want to test.

Rules that matter here:

- Do not commit the user's kit into *this* repository. It belongs in their own private repo.
- The private kit repo contains gold answers. **Never** suggest sharing it with a model that
  is being tested. Only `EXAM.md` is shared.
- Gold claims, reference answers and goals come from the user. You can draft candidates,
  but the user decides.
- If you are one of the models the user will test, say so. You may help with the design,
  but you must not grade your own answers later.

## 2. "Develop the kit itself"

Read [CLAUDE.md](CLAUDE.md) for the design, conventions and roadmap. Run `uv run pytest`
before committing.
