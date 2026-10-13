---
name: personal-ai-scorer
description: >
  Build a private benchmark from the user's own AI usage history, run it on new models,
  and report which model should do which job for them. Use when the user wants to set up
  their personal scorer kit, compare models on their own tasks, or read a scorer report.
---

# Personal AI Scorer Kit

You are helping one person find out which AI model is best **for them**, using tasks taken
from how they actually use AI. There are two phases. Ask the user which one they want.

- **Setup** (once, in the app that holds their history and memory): mine their past
  conversations, interview them, and write their personal kit.
- **Run** (whenever a new model comes out): run the kit on the models they name, grade
  the outputs, and produce the report.

Everything the kit stores is plain YAML and text files in a folder the user owns
(`my-kit/`). It is personal: never upload it anywhere the user did not ask for.

---

## Phase 1: Setup

### Step 1: Mine the history (you do this, no export needed)

Use whatever access you have to the user's past conversations: memory, chat search,
project files, past sessions. If you have none, ask the user to describe their last
~30 AI conversations in a few words each, or paste a list of chat titles.

Go through as much history as you can reach and write a usage inventory. For each
kind of use: a short name, 2-3 example conversations (title or date plus a one-line
summary), a rough share of their usage (count conversations, don't guess), and which
bucket type it is:

| Bucket type | Meaning | How it is tested |
|---|---|---|
| model-dependent | The quality depends on the model (paper reading, brainstorming, rewriting) | Core of the kit: real tasks plus a recipe |
| public-benchmark | Public scores already cover it well (coding) | Public scores plus 3-5 tasks from the user's own work |
| product-dependent | Depends on the app's features, not the model (search digests, file management) | Left out, or a manual app check |
| high-stakes | Health, money, training plans | Score safety and appropriateness, not cleverness |

Aim for **coverage**: 4-8 buckets that cover the most distinct kinds of use, not the 8
biggest variants of one thing. Usage shares must add up to 1.

### Step 2: Interview

Show the inventory and go through it with the user, a few questions at a time:

1. **Buckets.** Confirm, merge, split or rename them, and correct the usage shares.
2. **Tasks.** For each model-dependent bucket, pick 1-3 *real* past requests to turn
   into tasks. Prefer requests where the user remembers what a great answer looked like.
   Use their original wording for the prompt.
3. **Resources.** Collect what each task needs from the history: the paper, the draft,
   the notes. Save it as `.md` or `.txt` next to the task (convert PDFs to text once, so
   every model gets identical input). Only include material the user agrees to use.
4. **Gold material.** This is the important part, and it must come from the user, not
   from you. Each recipe says what it needs:
   - `paper-digest`: 10-15 claims the user expects a good digest to contain, plus 2-4
     "why" or "limitations" questions with a short reference answer. Draft candidate
     claims if that helps, but the user decides which ones are kept and how they are worded.
   - `brainstorming`: the goal in the user's words (what makes an idea useful to them),
     how many ideas to ask for, and 3-5 obvious ideas as the baseline.
5. **Weights.** Any task that matters more than others in its bucket (`weight`), and
   which model they currently use (`current_favorite`).
6. **Open choices.** Ask the user, don't decide for them: whether to include a manual
   checklist for app features, and whether to give every model a context pack (a short
   text export of their memory, identical for each model).

### Step 3: Write the kit

Write these files (`examples/demo-kit/` in this repo shows complete examples):

```
my-kit/
  profile.yaml                 # buckets, usage shares, current favorite
  tasks/<task-id>/task.yaml    # one folder per task, attachments next to it
  tasks/<task-id>/paper.md
  calibration/                 # filled later by the calibration step
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
  claims: [...]
  questions: [{question: ..., reference: ...}]
```

Quote any YAML line that contains `: ` inside a value. If you can run commands, check the
kit with `scorer validate my-kit`. Then show the user a summary: the buckets with their
shares, the tasks per bucket, and which buckets have no tasks (and why).

Tell the user the kit is frozen: changing tasks or gold material later means results
are no longer comparable with earlier runs, so bump `kit_version` when that happens.

---

## Phase 2: Run

### With a terminal (API mode or a mix)

```bash
scorer run my-kit \
  -m openrouter:<model-a> -m bailian:<model-b> -m app:<label-for-a-chat-app-model> \
  -j openrouter:<judge-model> -j bailian:<second-judge> -n 3
```

- `openrouter:` needs `OPENROUTER_API_KEY`. `bailian:` needs `DASHSCOPE_API_KEY` (set
  `BAILIAN_BASE_URL` for the international endpoint).
- `app:<label>` means the user runs that model in a chat app with no API: the run writes
  one prompt file per call and a `HANDOFF.md` checklist. Each prompt goes into a **new,
  temporary chat**, and the reply is pasted into the matching `.response.md` file. Then
  run `scorer resume results/<run>`, and repeat until nothing is waiting.
- Judges can be `app:` models too. The first judge that is not the model under test is
  used, so a model never grades itself. List two judges when one of them is also being
  tested.
- `mock:<name>` runs the whole pipeline offline with fake models, which is useful for
  trying things out.

### Without a terminal (chat app only)

If you, the AI app, cannot run commands, act as the runner yourself, carefully:

1. For each task and each model the user names, build the prompt exactly as the runner
   would: attachments first as `<document name="...">` blocks, then the prompt, then the
   recipe's extra lines (for paper-digest, the gold questions as Q1, Q2, ...), then the
   recipe's `response_format`.
2. Ask the user to send each prompt to each model in a fresh, temporary chat, 3 times,
   and paste the replies back. Save them as
   `results/<run>/handoff/app_<model>/task__<task>__r<k>.response.md` if you can write
   files.
3. Grade with the recipe's judge prompt, but **only for outputs written by a different
   model than you**. Tell the user which outputs you cannot grade, and why.
4. Report using the layout below and mark every judge-scored number as provisional until
   calibration is done.

### Calibrate the judge (before trusting it)

```bash
scorer sheet results/<run> -r paper-digest      # blind sample, outputs anonymized
# the user fills in user_label for each item in my-kit/calibration/<...>/sheet.yaml
scorer calibrate my-kit/calibration/<...>/sheet.yaml
```

Agreement uses Cohen's κ for categories, quadratic-weighted κ for ordered scales, and
correlation for numbers. Below the recipe's threshold (0.6 for now) a criterion shows as
"needs work": improve the anchors in the recipe and grade again. The report warns about
any judge criterion that has not been calibrated.

### Report

`scorer report results/<run>` writes `report.html`. For each model it shows: a persona
card with its role and an evidence line, fit weighted by the user's usage mix, a radar
by bucket against the current favorite, what to use it for and what not to, its best and
worst output, and cost, speed and consistency. It ends with a team roster (which model
to route each bucket to) and task-level evidence linking every score to its output.

When you present results, lead with the roster and the persona cards. Every headline must
point to the tasks behind it. Say "close call" when the margin is small, and say so when
the judge is not yet calibrated.
