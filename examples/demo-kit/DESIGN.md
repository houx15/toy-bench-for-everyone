# Benchmark design: Demo User, v0.1.0

*Example of the design document an agent presents before the kit is frozen. The user and
their history are fictional.*

## Usage inventory

Based on the user's last 48 conversations (a list the user pasted from their main chat app):

| Bucket | Share | Evidence (examples) | Type |
|---|---|---|---|
| Paper reading | 30% | "summarize this paper, what's the trick" ×9, "explain section 3" ×5 | model-dependent |
| Coding | 25% | Python tooling, small web apps | public-benchmark |
| Brainstorming | 20% | side-project ideas, talk titles, blog angles | model-dependent |
| Research planning | 15% | "what experiments should I run next" after results | model-dependent |
| Daily AI digest | 10% | news summaries, which depend on the app's search | product-dependent |

## What is tested, and what isn't

- **Tested (65% of usage):** paper reading, brainstorming, and research planning.
- **Coding (25%), left out for now:** public coding benchmarks track this reasonably well
  for small Python work. Add 3-5 tasks from the user's own repos later.
- **Daily digest (10%), left out:** quality there comes from the app's search, not the model.

## Tasks

| Task | Bucket | Recipe | From | Gold material from the user |
|---|---|---|---|---|
| pd-tidal-memory | Paper reading | paper-digest | Typical "digest before group meeting" request | 10 claims, 2 questions with reference answers |
| bs-weekend-project | Brainstorming | brainstorming | Recurring "side project ideas" request | Goal, 10 ideas, 3 baseline ideas |
| bs-follow-up-experiments | Research planning | brainstorming | "What next?" after a surprising ablation | Goal, 8 ideas, 3 baseline ideas |

## Designer's notes

- **Thin coverage.** Each bucket has one task, so a single bad answer can flip a bucket
  ranking. 3 repeats help with noise, but not with how representative the task is. Next:
  a second paper, ideally from a different subfield.
- **Paper digest may not separate strong models:** claims stated plainly in the abstract
  will be covered by everyone. 4 of the 10 claims are deliberately buried in the
  experiments section, and these are where the differences should show up.
- **Research planning uses the brainstorming recipe**, so it is scored on novelty,
  diversity and usefulness. It does not check whether each experiment would actually
  isolate one explanation, which is the user's real goal. A dedicated recipe would do
  better; this is a stopgap.
- **Novelty is relative:** it is measured against the other models in the same run, so
  it shifts when the line-up changes.
- **Unsure:** whether "paper reading" also covers the "explain section 3" requests (close
  reading), which may need its own task type.

## How to run it

Compare Claude, Gemini and Grok through their chat apps using `exam/EXAM.md`, 3 temporary
chats each. Judge: an API model from a fourth provider, so no tested model grades itself.
