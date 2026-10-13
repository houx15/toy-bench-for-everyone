"""scorer — command line for the Personal AI Scorer Kit.

Typical flow:
  scorer validate my-kit
  scorer run my-kit -m openrouter:<model> -m app:ChatGPT -j openrouter:<judge>
  scorer resume results/<run>          # after pasting app responses; repeat until done
  scorer sheet results/<run> -r paper-digest   # blind sample for you to grade
  scorer calibrate my-kit/calibration/<sheet>/sheet.yaml
  scorer report results/<run>
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from scorer_kit.kit import REPO_ROOT, KitError, load_kit


def _print_progress(run, label: str, progress) -> None:
    print(progress.summary(label))
    for e in progress.errors[:10]:
        print(f"  error: {e}")
    if progress.pending:
        print(f"  -> app prompts are waiting: see {run.dir / 'HANDOFF.md'}, then `scorer resume {run.dir}`")


def _advance(run, workers: int) -> None:
    from scorer_kit.report.build import build_report
    from scorer_kit.runner.run import grade_run, run_tasks

    tp = run_tasks(run, workers)
    _print_progress(run, "outputs", tp)
    gp = grade_run(run, workers)
    _print_progress(run, "grades", gp)
    if not (tp.pending or gp.pending or gp.waiting):
        print(f"report: {build_report(run)}")


def cmd_validate(a) -> None:
    kit = load_kit(a.kit)
    print(f"ok: {len(kit.tasks)} tasks, {len(kit.profile.buckets)} buckets, "
          f"recipes {sorted({t.recipe for t in kit.tasks.values()})}")
    untested = [b.name for b in kit.profile.buckets if not any(t.bucket == b.id for t in kit.tasks.values())]
    if untested:
        print(f"note: buckets with no tasks yet: {', '.join(untested)}")


def cmd_run(a) -> None:
    from scorer_kit.runner.run import create_run

    run = create_run(a.kit, a.model, a.judge or [], a.repeats, a.results, a.run_id,
                     a.tasks.split(",") if a.tasks else None)
    print(f"run folder: {run.dir}")
    _advance(run, a.workers)


def cmd_resume(a) -> None:
    from scorer_kit.runner.run import Run

    _advance(Run.load(a.run), a.workers)


def cmd_grade(a) -> None:
    from scorer_kit.runner.run import Run, grade_run

    run = Run.load(a.run)
    _print_progress(run, "grades", grade_run(run, a.workers, regrade=a.regrade))


def cmd_status(a) -> None:
    from scorer_kit.runner.run import Run, dump_status

    print(dump_status(Run.load(a.run)))


def cmd_report(a) -> None:
    from scorer_kit.report.build import build_report
    from scorer_kit.runner.run import Run

    print(build_report(Run.load(a.run), Path(a.out) if a.out else None))


def cmd_sheet(a) -> None:
    from scorer_kit.calibration import make_sheet
    from scorer_kit.runner.run import Run

    path = make_sheet(Run.load(a.run), a.recipe, a.n, a.seed)
    print(f"blind grading sheet: {path}\nfill in user_label for each item, then: scorer calibrate {path}")


def cmd_calibrate(a) -> None:
    from scorer_kit.calibration import score_sheet

    s = score_sheet(a.sheet)
    print(f"{s['recipe']}: {s['unlabelled_items']} items left unlabelled")
    for c, r in s["criteria"].items():
        if r["status"] == "too-few-labels":
            print(f"  {c}: too few labels ({r['n']})")
        else:
            print(f"  {c}: {r['metric']}={r['value']} (n={r['n']}, threshold {r['threshold']}) -> {r['status']}")


def cmd_init(a) -> None:
    dest = Path(a.dest)
    if dest.exists():
        sys.exit(f"{dest} already exists; not overwriting")
    shutil.copytree(REPO_ROOT / "examples" / "demo-kit", dest)
    print(f"created {dest} from the demo kit — replace its tasks with your own (see SKILL.md)")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="scorer", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("validate", help="check a kit folder")
    s.add_argument("kit")
    s.set_defaults(fn=cmd_validate)

    s = sub.add_parser("run", help="start a run: task x model x repeat, then grade and report")
    s.add_argument("kit")
    s.add_argument("-m", "--model", action="append", required=True,
                   help="provider:model — openrouter:…, bailian:…, app:<label>, mock:<label>")
    s.add_argument("-j", "--judge", action="append",
                   help="judge model(s); the first one that is not the model under test is used")
    s.add_argument("-n", "--repeats", type=int, default=3)
    s.add_argument("--tasks", help="comma-separated task ids (default: all)")
    s.add_argument("--results", default="results")
    s.add_argument("--run-id")
    s.add_argument("--workers", type=int, default=8)
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("resume", help="continue a run (picks up pasted app responses)")
    s.add_argument("run")
    s.add_argument("--workers", type=int, default=8)
    s.set_defaults(fn=cmd_resume)

    s = sub.add_parser("grade", help="(re)grade a run's outputs")
    s.add_argument("run")
    s.add_argument("--regrade", action="store_true")
    s.add_argument("--workers", type=int, default=8)
    s.set_defaults(fn=cmd_grade)

    s = sub.add_parser("status", help="what is done, missing or failed")
    s.add_argument("run")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("report", help="build the HTML report")
    s.add_argument("run")
    s.add_argument("--out")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("sheet", help="make a blind grading sheet to calibrate the judge")
    s.add_argument("run")
    s.add_argument("-r", "--recipe", required=True)
    s.add_argument("-n", type=int, help="items per criterion (default: recipe sample_size)")
    s.add_argument("--seed", type=int, default=0)
    s.set_defaults(fn=cmd_sheet)

    s = sub.add_parser("calibrate", help="score a filled-in sheet: judge-user agreement")
    s.add_argument("sheet")
    s.set_defaults(fn=cmd_calibrate)

    s = sub.add_parser("init", help="create a kit folder from the demo kit")
    s.add_argument("dest", nargs="?", default="my-kit")
    s.set_defaults(fn=cmd_init)

    a = p.parse_args(argv)
    try:
        a.fn(a)
    except (KitError, ValueError, FileExistsError, RuntimeError) as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
