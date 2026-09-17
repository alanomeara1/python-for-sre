#!/usr/bin/env python3
"""drill - repetition trainer for SRE/DevOps Python.

    drill list                  all drills, reps, best times, next due date
    drill due                   what to do today
    drill start 01              fresh attempt file + start the clock
    drill start 01 --variant    same, for the variant problem
    drill check 01 [--variant]  run the tests; a pass is logged as a rep
    drill flash [N]             N random idiom flashcards from PATTERNS.md
    drill verify [01 ...]       self-test: references pass, stubs fail
"""

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tomllib
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DRILLS = ROOT / "drills"
ATTEMPTS = ROOT / "attempts"
PROGRESS = ROOT / "progress.json"

# Days until the next recall rep, indexed by how many on-target recalls you have banked.
INTERVALS = [1, 2, 4, 7, 14, 30]
STAGES = ("copy", "recall", "variant")


# ---------------------------------------------------------------- data helpers

def all_drills() -> list[Path]:
    return sorted(p for p in DRILLS.iterdir() if p.is_dir() and (p / "drill.toml").exists())


def find_drill(ref: str) -> Path:
    ref = ref.strip().lower()
    for d in all_drills():
        number, _, name = d.name.partition("_")
        if ref in (d.name, name) or (ref.isdigit() and int(ref) == int(number)):
            return d
    sys.exit(f"No drill matches {ref!r}. Try: drill list")


def meta(drill: Path) -> dict:
    with open(drill / "drill.toml", "rb") as f:
        return tomllib.load(f)


def load_progress() -> dict:
    if PROGRESS.exists():
        return json.loads(PROGRESS.read_text())
    return {}


def save_progress(progress: dict) -> None:
    PROGRESS.write_text(json.dumps(progress, indent=2, sort_keys=True))


def fmt_secs(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


# ---------------------------------------------------------------- commands

def cmd_list(_args) -> int:
    progress = load_progress()
    today = date.today().isoformat()
    print(f"{'#':<3} {'drill':<26} {'target':>6} {'reps':>4} {'best':>6}  next due")
    for d in all_drills():
        m, p = meta(d), progress.get(d.name, {})
        recalls = [r["seconds"] for r in p.get("reps", []) if r["stage"] == "recall"]
        best = min(recalls) if recalls else None
        due = p.get("due", "new")
        flag = " <- due" if due != "new" and due <= today else ""
        print(f"{d.name[:2]:<3} {d.name[3:]:<26} {m['target_minutes']:>5}m "
              f"{len(p.get('reps', [])):>4} {fmt_secs(best):>6}  {due}{flag}")
    return 0


def cmd_due(_args) -> int:
    progress = load_progress()
    today = date.today().isoformat()
    due = [d for d in all_drills() if d.name in progress and progress[d.name].get("due", "9999") <= today]
    new = [d for d in all_drills() if not progress.get(d.name, {}).get("reps")]

    print("Warm-up:  drill flash 5")
    if due:
        print("Review (recall from memory, against the clock):")
        for d in due:
            print(f"  drill start {d.name[:2]}      # {meta(d)['title']}")
    else:
        print("Review:   nothing due")
    if new:
        print(f"New:      drill start {new[0].name[:2]}      # {meta(new[0])['title']}")
    return 0


def cmd_start(args) -> int:
    drill = find_drill(args.drill)
    kind = "variant" if args.variant else "solution"
    progress = load_progress()
    entry = progress.setdefault(drill.name, {"reps": [], "level": 0})

    if args.stage:
        stage = args.stage
    elif args.variant:
        stage = "variant"
    else:
        stage = "copy" if not entry["reps"] else "recall"

    stub = drill / ("variant_stub.py" if args.variant else "stub.py")
    target = ATTEMPTS / drill.name / f"{kind}.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_text() != stub.read_text():
        shutil.copy(target, target.with_suffix(".prev.py"))
    shutil.copy(stub, target)

    entry.setdefault("started", {})[kind] = {"at": datetime.now().isoformat(), "stage": stage}
    save_progress(progress)

    spec = drill / ("variant.md" if args.variant else "README.md")
    reference = drill / ("variant_reference.py" if args.variant else "reference.py")
    target_min = meta(drill)["variant_target_minutes" if args.variant else "target_minutes"]

    print(f"\n{meta(drill)['title']}  [{stage.upper()}]  target {target_min} min\n")
    print(f"  spec:     {spec.relative_to(ROOT)}")
    print(f"  write in: {target.relative_to(ROOT)}")
    if stage == "copy":
        print(f"  copy:     {reference.relative_to(ROOT)}")
        print("\n  Put the reference beside your editor and TYPE it. No pasting.")
        print("  Say each line's purpose out loud as you type it.")
    else:
        print("\n  Reference closed. Write it from memory, narrating as if to an interviewer.")
        print("  Stuck for more than 2 minutes? Peek at ONE line and carry on. The rep still counts, but it'll be slow.")
    flag = " --variant" if args.variant else ""
    print(f"\n  Clock started. When the tests should pass:  drill check {drill.name[:2]}{flag}\n")
    return 0


def run_pytest(drill: Path, kind: str, mode: str, quiet: bool = False) -> subprocess.CompletedProcess:
    test_file = drill / ("test_variant.py" if kind == "variant" else "test_solution.py")
    env = {**os.environ, "DRILL_MODE": mode}
    cmd = [sys.executable, "-m", "pytest", str(test_file), "-p", "no:cacheprovider"]
    if quiet:
        cmd += ["--tb=no"]
    return subprocess.run(cmd, cwd=ROOT, env=env, capture_output=quiet, text=True)


def cmd_check(args) -> int:
    drill = find_drill(args.drill)
    kind = "variant" if args.variant else "solution"
    result = run_pytest(drill, kind, "attempt")
    if result.returncode != 0:
        print("\nNot yet. Read the first failure, fix it, run check again. The clock is still running.")
        return 1

    progress = load_progress()
    entry = progress.setdefault(drill.name, {"reps": [], "level": 0})
    started = entry.get("started", {}).pop(kind, None)
    if started is None:
        print("\nPassed, but no clock was running (use `drill start` first). Rep not logged.")
        return 0

    seconds = (datetime.now() - datetime.fromisoformat(started["at"])).total_seconds()
    stage = started["stage"]
    target_min = meta(drill)["variant_target_minutes" if kind == "variant" else "target_minutes"]
    on_target = seconds <= target_min * 60

    entry["reps"].append({"date": date.today().isoformat(), "stage": stage, "kind": kind,
                          "seconds": round(seconds), "on_target": on_target})

    # Only unaided work moves the schedule. Copying is learning, not recall.
    if stage == "copy":
        entry.setdefault("due", date.today().isoformat())
        verdict = "Copy rep done. Now close the reference and recall it:  drill start " + drill.name[:2]
    elif on_target:
        days = INTERVALS[min(entry["level"], len(INTERVALS) - 1)]
        entry["level"] += 1
        entry["due"] = (date.today() + timedelta(days=days)).isoformat()
        verdict = f"On target. Next recall in {days} day(s): {entry['due']}"
    else:
        entry["due"] = (date.today() + timedelta(days=1)).isoformat()
        verdict = f"Passed but over {target_min} min, so it's not fluent yet. Again tomorrow: {entry['due']}"

    save_progress(progress)
    print(f"\nPASS in {fmt_secs(seconds)}  [{stage}]  {verdict}")
    return 0


def cmd_flash(args) -> int:
    text = (ROOT / "PATTERNS.md").read_text()
    cards = re.findall(r"^### (.+?)\n+```python\n(.*?)```", text, flags=re.M | re.S)
    if not cards:
        sys.exit("No cards found in PATTERNS.md")
    picks = random.sample(cards, min(args.n, len(cards)))
    print("Type each one in your scratch file BEFORE revealing. Then compare, character for character.\n")
    for i, (prompt, answer) in enumerate(picks, 1):
        print(f"[{i}/{len(picks)}] {prompt}")
        input("   ...press Enter to reveal ")
        print("\n" + "\n".join("    " + line for line in answer.rstrip().splitlines()) + "\n")
    return 0


def cmd_verify(args) -> int:
    drills = [find_drill(r) for r in args.drills] if args.drills else all_drills()
    failures = 0
    for d in drills:
        for kind in ("solution", "variant"):
            ref = run_pytest(d, kind, "reference", quiet=True)
            stub = run_pytest(d, kind, "stub", quiet=True)
            stub_passed = re.search(r"(\d+) passed", (stub.stdout.strip().splitlines() or [""])[-1])
            ref_ok = ref.returncode == 0
            stub_ok = stub.returncode != 0 and not stub_passed
            summary = (ref.stdout.strip().splitlines() or ["?"])[-1]
            status = "ok " if ref_ok and stub_ok else "BAD"
            failures += status == "BAD"
            print(f"{status} {d.name:<26} {kind:<8} reference: {summary:<32} "
                  f"stub passes: {stub_passed.group(1) if stub_passed else 0}")
            if not ref_ok:
                print(ref.stdout)
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="drill", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list").set_defaults(func=cmd_list)
    sub.add_parser("due").set_defaults(func=cmd_due)

    p = sub.add_parser("start")
    p.add_argument("drill")
    p.add_argument("--variant", action="store_true")
    p.add_argument("--stage", choices=STAGES)
    p.set_defaults(func=cmd_start)

    p = sub.add_parser("check")
    p.add_argument("drill")
    p.add_argument("--variant", action="store_true")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("flash")
    p.add_argument("n", nargs="?", type=int, default=5)
    p.set_defaults(func=cmd_flash)

    p = sub.add_parser("verify")
    p.add_argument("drills", nargs="*")
    p.set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
