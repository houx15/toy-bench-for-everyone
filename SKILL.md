---
name: personal-ai-scorer
description: >
  Build a private benchmark from the user's own AI usage, run it on new models, and report
  which model should do which job for them. Use when the user wants to set up their
  personal benchmark, compare models on their own tasks, or read a scorer report.
---

# Personal AI Scorer Kit

You are helping one person find out which AI model is best **for them**, using tasks taken
from how they actually use AI. There are two phases; ask which one they want if it's unclear.

- **Phase 1: Setup**, done once. Design their benchmark with them, present it, save it to
  their private GitHub repo, and produce the exam they will give to models.
- **Phase 2: Run**, whenever a new model comes out. Collect each model's answers, grade
  them, and report.

## Two things that must stay apart

| | Contains | Who may see it |
|---|---|---|
| **The kit** (the user's private repo) | Tasks, **gold answers**, design, results | The user, and the agent grading the answers |
| **The exam** (`exam/EXAM.md`) | Task prompts and documents only | The models being tested |

If a tested model can read the kit, it can read the answer key, and the benchmark is
worthless. Never share the kit with a model under test, and never put gold material in
the exam. `scorer exam` builds the exam from the kit and leaves the gold material out.

**The scorer tool.** In a clone of this repo, use `uv run scorer ...`. Anywhere else, use
`uvx --from git+https://github.com/houx15/toy-bench-for-everyone scorer ...`. Below,
`scorer` means whichever of these works. If you cannot run commands at all, follow the
manual fallbacks marked *(no terminal)*.

---

## Phase 1: Setup

### Step 1: Find out how they use AI

Use whatever access you have to their past AI conversations: memory, chat search, past
sessions, project files. **Be honest about what you can see.** A coding agent usually sees
only its own coding sessions, not the user's chat apps. If most of their usage lives
somewhere you cannot reach, ask them for one of these, in order of preference:

1. In the app they use most, have that app list its last ~50 conversations with a
   one-line summary each, then paste the list to you. Give them this prompt to use:
   *"List my last 50 conversations with you: date, title, and one line on what I asked
   for. Plain list, no commentary."*
2. A list of chat titles they copy from the app's sidebar.
3. A short interview: "What did you use AI for this week? Last month? What do you rely on
   it for most?"

Then write a usage inventory. For each kind of use, give a short name, 2-3 real examples,
a rough share of their usage (count conversations rather than guessing), and a bucket type:

| Bucket type | Meaning | How it is tested |
|---|---|---|
| model-dependent | Quality depends on the model (paper reading, brainstorming, rewriting) | Core of the kit: real tasks plus a recipe |
| public-benchmark | Public scores already cover it well (coding) | Public scores plus 3-5 tasks from the user's own work |
| product-dependent | Depends on the app's features, not the model (search digests, file management) | Left out, or a manual app check |
| high-stakes | Health, money, training plans | Score safety and appropriateness, not cleverness |

Aim for **coverage**: 4-8 buckets that span the most distinct kinds of use. Shares add up
to 1.

### Step 2: Design the benchmark with the user

Go through it a few questions at a time:

1. **Buckets.** Confirm, merge, split or rename them, and correct the shares.
2. **Tasks.** For each model-dependent bucket, pick 1-3 *real* past requests. Prefer ones
   where the user remembers what a great answer looked like. Keep their original wording.
   Recipes available now: `paper-digest` (fact-heavy) and `brainstorming` (taste-heavy).
   See `recipes/*.yaml`. For a bucket that no recipe fits, say so: leave it out for now
   rather than forcing it into the wrong recipe.
3. **Resources.** Collect what each task needs: the paper, the draft, the notes. Save each
   as `.md` or `.txt` next to its task (convert PDFs to text once, so every model gets
   identical input). Use only material the user agrees to include, because it will go into
   the exam that other AI companies' models will read.
4. **Gold material.** This must come from the user. You can draft candidates for them to
   edit, but you cannot write it for them:
   - `paper-digest`: 10-15 claims a good digest must contain, plus 2-4 "why" or
     "limitations" questions with a short reference answer.
   - `brainstorming`: the goal in their words (what makes an idea useful to them), how
     many ideas to ask for, and 3-5 obvious ideas to use as the baseline.
5. **Weights and favorite.** Which tasks matter more within a bucket (`weight`), and
   which model they use today (`current_favorite`).
6. **Their choices, not yours.** Ask whether to give every model an identical context pack
   (a short text about them).

### Step 3: Present the design (`DESIGN.md`) and wait for approval

Write `DESIGN.md` in the kit and walk the user through it. It is the human-readable
version of their benchmark plus your reasoning:

- **Usage inventory**: buckets, shares, and the evidence for each (which conversations).
- **What is tested and what isn't**: every bucket is either in or out, with the reason.
  Give the share of their usage the kit covers.
- **Each task**: where it came from, what it tests, which recipe measures it, and what
  gold material the user supplied.
- **Your thoughts**: where the benchmark is weak, for example tasks that probably won't
  separate the models, buckets with only one task, or gold claims that are ambiguous.
  Also cover what you would add next, and anything you are unsure you understood.
- **How to run it**: the models they plan to compare and the judge (see Phase 2).

Revise until they approve it.

### Step 4: Write the kit and save it as a private repo

Folder layout (`examples/demo-kit/` in this repo is a complete example):

```
my-ai-bench/
  README.md                    # copy examples/demo-kit/README.md and fill it in
  DESIGN.md
  profile.yaml                 # buckets, usage shares, current favorite
  tasks/<task-id>/task.yaml    # one folder per task, attachments next to it
  tasks/<task-id>/paper.md
  exam/EXAM.md                 # generated in step 5, the only thing to share
  context-pack.md              # optional
```

Task file:

```yaml
id: pd-my-paper            # lowercase, digits, dashes
title: Digest X before reading group
bucket: paper-reading      # a bucket id from profile.yaml
recipe: paper-digest       # a file in recipes/
source: "where in the history this came from"
input:
  prompt: |
    The user's original request
  attachments: [paper.md]
gold:                      # what the recipe needs, see recipes/<recipe>.yaml
  claims:
    - "Quote any line that contains a colon: like this"
  questions:
    - {question: "...", reference: "..."}
```

Check it with `scorer validate my-ai-bench` and fix everything it reports.

Then create the private repo. Ask the user for a name first (default `my-ai-bench`):

```bash
cd my-ai-bench && git init && git add -A && git commit -m "My AI benchmark v0.1.0"
gh repo create my-ai-bench --private --source . --push
```

If `gh` is not available or not logged in, give the user these commands to run
themselves. *(no terminal)*: give the user every file's content and the commands.
**Confirm with `gh repo view --json visibility` that the repo is PRIVATE.**

From now on the kit is frozen. Changing tasks or gold material makes later results
incomparable with earlier ones, so bump `kit_version` in `profile.yaml` when that happens.

### Step 5: Build the exam

```bash
scorer exam my-ai-bench -o my-ai-bench/exam/EXAM.md
```

Check that it contains no gold claims, reference answers, goals or baseline ideas, then
commit it. Explain to the user how to hand it to each model they want to test:

- **Best: upload or paste the file** into a **new, temporary chat** (memory off, no
  custom instructions). Use one chat per repeat, and 3 chats per model.
- **If they want a link:** a *secret* gist (`gh gist create exam/EXAM.md`) or a second
  repo that holds only `EXAM.md`. Never use the kit repo. Warn them that anything
  readable by link can be crawled and end up in future training data, which would
  contaminate their benchmark. A link also only works if the app can browse.

The model must reply with `=== ANSWER <id> === ... === END ANSWER ===` sections. Tell the
user to save each full reply as a file, for example `replies/grok-r1.md`.

---

## Phase 2: Run

### Collect answers

**From chat apps (no API keys):** create a run with one `app:` model per app, then file
each saved reply:

```bash
scorer run my-ai-bench -m app:grok -m app:gemini -m app:claude -j <judge> -n 3
scorer ingest results/<run> replies/grok-r1.md -m app:grok -r 1
# ... one ingest per reply file; the run grades and reports as soon as everything is in
```

**Through APIs:** `-m openrouter:<model>` (`OPENROUTER_API_KEY`) or `-m bailian:<model>`
(`DASHSCOPE_API_KEY`, and set `BAILIAN_BASE_URL` for the international endpoint). These
are called directly, one fresh call per task and repeat. You can mix them with `app:` models.

### Choose the judge

The judge must not be a model under test. The first listed `-j` that isn't the model being
graded is used, so list two judges if a judge is also being tested.

- **API judge**: `-j openrouter:<model>`.
- **You, the agent, as judge**: `-j app:<your-name>` (for example `app:codex`). Grading
  then writes one prompt per output under `results/<run>/handoff/app_<your-name>/`. Answer
  each `judge__*.prompt.md` by writing the JSON reply into the matching `.response.md`,
  then run `scorer resume results/<run>`. Only do this if you are **not** one of the
  tested models.

### Calibrate the judge before trusting it

```bash
scorer sheet results/<run> -r paper-digest     # blind sample, outputs anonymized
# the user fills in user_label for each item in calibration/<...>/sheet.yaml
scorer calibrate my-ai-bench/calibration/<...>/sheet.yaml
```

Agreement is measured with Cohen's κ for categories, quadratic-weighted κ for ordered
scales, and correlation for numbers. Below the recipe's threshold (0.6 for now) a criterion
shows "needs work": sharpen the anchors in the recipe and grade again. The report flags
every judge criterion that has not been calibrated yet.

### Report

`scorer report results/<run>` writes `report.html`. For each model it shows: a persona
card with an evidence line, fit weighted by the user's usage mix, a radar by bucket
against the current favorite, what to use it for and what not to, its best and worst
output, and cost, speed and consistency. It ends with the team roster (which model to route
each bucket to) and task-level evidence that links every score to its output.

When presenting results, lead with the roster and personas, point every headline to its
tasks, call small margins "close calls", and say so when the judge is not yet calibrated.
Commit `results/` to the private kit repo so the history stays with the user.
