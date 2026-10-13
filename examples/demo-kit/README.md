# My AI benchmark

My private benchmark, built from my own AI usage with the
[Personal AI Scorer Kit](https://github.com/houx15/toy-bench-for-everyone).

> **Keep this repository private, and never share it with an AI model you are testing.**
> It contains the answer key (gold claims, reference answers). Share only
> [`exam/EXAM.md`](exam/EXAM.md).

- [`DESIGN.md`](DESIGN.md): what is tested and why, and the designer's notes
- `profile.yaml`: my usage buckets and how much each counts
- `tasks/`: the tasks, their documents, and the gold material
- `exam/EXAM.md`: the only file that goes to the models being tested
- `results/`: past runs and reports

## Test a new model

1. Open a new, temporary chat with the model (memory off), upload `exam/EXAM.md`, and
   send it. Save the full reply as `replies/<model>-r1.md`. Do this 3 times, each in a
   new chat.
2. File the replies and grade them (the judge must not be a model under test):

   ```bash
   S="uvx --from git+https://github.com/houx15/toy-bench-for-everyone scorer"
   $S run . -m app:<model> -m app:<other-model> -j openrouter:<judge-model> -n 3
   $S ingest results/<run> replies/<model>-r1.md -m app:<model> -r 1   # one per reply
   ```

3. Open `results/<run>/report.html`.

Or give this repository to an AI agent you are *not* testing, and ask it to run Phase 2
of the kit's SKILL.md.
