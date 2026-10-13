# Tidal Memory: Periodic Cache Flushing for Long-Context Agents

*Synthetic paper written for the scorer-kit demo. It describes a fictional method; none of
these results are real.*

## Abstract

Long-running language-model agents accumulate context until they hit the window limit, after
which most systems either truncate the oldest turns or summarize them once. We propose Tidal
Memory, which flushes the working context on a fixed schedule (every 40 turns in our main
setting) and rebuilds it from a structured notebook the agent maintains itself. On a suite of
120 multi-day software-maintenance tasks, Tidal Memory raises task completion from 41% to 58%
compared with truncation, and from 49% to 58% compared with one-shot summarization, while
cutting average tokens per turn by 37%.

## 1. Method

The agent writes to a notebook with three sections: *goals*, *facts*, and *open threads*.
Every 40 turns the working context is cleared and replaced by the notebook plus the last
5 turns verbatim. The flush interval was chosen on a held-out set of 20 tasks; intervals of
20 and 80 turns performed worse (52% and 54% completion respectively).

The notebook is capped at 2,000 tokens. When the cap is reached, the agent must delete or
merge entries before adding new ones. We found that without the cap, notebooks grew to an
average of 9,400 tokens and completion fell to 50%.

## 2. Experiments

All experiments use a single base model and three random seeds. The task suite covers bug
fixing, dependency upgrades, and documentation updates in 12 open-source repositories.
Completion is judged by the repository's own test suite plus a human check for the
documentation tasks.

| Method | Completion | Tokens / turn |
|---|---|---|
| Truncation | 41% | 6,100 |
| One-shot summary | 49% | 4,800 |
| Tidal Memory | 58% | 3,850 |

Most of the gain comes from dependency-upgrade tasks (+24 points over truncation); on
documentation tasks the improvement is small (+4 points) and within seed variance.

## 3. Limitations

We test only one base model, so we cannot say whether the schedule transfers. The flush
interval is fixed rather than adaptive. Tasks last at most 400 turns; behaviour over longer
horizons is untested. The human check for documentation tasks was done by the authors.
