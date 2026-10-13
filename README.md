# Personal AI Scorer Kit

Public leaderboards measure an average user who doesn't exist. This kit turns **your own**
AI usage into a private benchmark, runs it on any model you like, and tells you which model
should do which job for you.

- **Setup, once:** give `SKILL.md` to the AI app that knows you best. It mines your past
  conversations, interviews you, and writes your kit (`my-kit/`): usage buckets, real
  tasks, and the gold answers only you can supply.
- **Run, whenever a new model ships:** `scorer run` fans out task × model × 3 repeats,
  grades the outputs (automatic checks plus a judge model that never grades itself), and
  writes an HTML report with a persona per model and a team roster.

It works with or without API keys: `openrouter:` and `bailian:` models are called directly,
and `app:` models are handed to you as prompt files to paste into any chat app.

## Try it offline

```bash
uv sync
uv run scorer run examples/demo-kit -m mock:steady-sonnet -m mock:bold-qwen -j mock:judge
open results/*/report.html
```

## Your own kit

```bash
uv run scorer init my-kit          # start from the demo, or let your AI app write it (SKILL.md)
uv run scorer validate my-kit
export OPENROUTER_API_KEY=...       # and/or DASHSCOPE_API_KEY for Bailian
uv run scorer run my-kit -m openrouter:<model> -m app:ChatGPT -j openrouter:<judge>
uv run scorer resume results/<run>  # after pasting app replies
uv run scorer sheet results/<run> -r paper-digest   # grade a blind sample yourself...
uv run scorer calibrate my-kit/calibration/<sheet>/sheet.yaml   # ...to check the judge
```

`my-kit/` and `results/` are git-ignored: your data stays on your machine.

## Layout

```
SKILL.md              setup interview + run instructions for an AI app
recipes/              how each task type is measured (YAML, fixed before any run)
scorer_kit/
  schemas.py          profile / task / recipe / record schemas
  kit.py              load + validate a kit folder
  graders/            automatic checks, judge prompts, scoring per recipe
  runner/             backends (openrouter, bailian, app handoff, mock) + fan-out
  calibration.py      Cohen's κ / weighted κ / correlation + blind grading sheets
  report/             HTML report, personas
examples/demo-kit/    a complete fictional kit
tests/
```
