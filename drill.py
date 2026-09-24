#!/usr/bin/env python3
"""drill - repetition trainer for SRE/DevOps Python.

Study the model answer, type it out, rebuild it from memory against the clock,
then solve a variant. Reps that stay inside the target time come back less often.

    drill due                 what to do today
    drill help start          detail on any command
"""

import argparse
import ast
import difflib
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import textwrap
import tomllib
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DRILLS = ROOT / "drills"
# DRILL_HOME redirects your reps and history elsewhere, so tests of this tool
# can never touch the real ones.
HOME = Path(os.environ.get("DRILL_HOME", ROOT))
ATTEMPTS = HOME / "attempts"
PROGRESS = HOME / "progress.json"

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


def get_clock(entry: dict, kind: str) -> dict | None:
    return entry.get("started", {}).get(kind)


def clock_elapsed(clock: dict) -> float:
    """Time actually spent on the rep: banked time plus the stretch running right now."""
    elapsed = clock.get("elapsed", 0.0)
    if clock.get("running_since"):
        elapsed += (datetime.now() - datetime.fromisoformat(clock["running_since"])).total_seconds()
    return elapsed


def open_clock(args) -> tuple[Path, str, dict, dict, dict]:
    """Shared lookup for pause/resume/cancel: exits if there's no clock on that rep."""
    drill = find_drill(args.drill)
    kind = "variant" if args.variant else "solution"
    progress = load_progress()
    entry = progress.setdefault(drill.name, {"reps": [], "level": 0})
    clock = get_clock(entry, kind)
    if clock is None:
        sys.exit(f"No rep in progress for {drill.name[:2]} ({kind}). Start one:  drill start {drill.name[:2]}")
    return drill, kind, progress, entry, clock


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

    in_progress = [(d, kind, clock) for d in all_drills()
                   for kind, clock in progress.get(d.name, {}).get("started", {}).items()]
    for d, kind, clock in in_progress:
        state = "running" if clock.get("running_since") else "PAUSED"
        flag = " --variant" if kind == "variant" else ""
        print(f"\nIn progress: {d.name[:2]} {clock['stage']} ({kind}) {state} at {fmt_secs(clock_elapsed(clock))}"
              f"\n  drill check {d.name[:2]}{flag}   |   drill "
              f"{'pause' if state == 'running' else 'resume'} {d.name[:2]}{flag}   |   drill cancel {d.name[:2]}{flag}")
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
    saved_note = None
    if target.exists() and target.read_text() != stub.read_text():
        # Never reuse one backup slot: a second start would destroy the first rep.
        # Every previous attempt is kept under its own timestamp.
        backup = target.with_name(f"{kind}.{datetime.now():%Y%m%d-%H%M%S}.bak.py")
        shutil.copy(target, backup)
        saved_note = f"  kept:     {backup.name} (your previous attempt)"
    shutil.copy(stub, target)

    entry.setdefault("started", {})[kind] = {
        "running_since": datetime.now().isoformat(),
        "elapsed": 0.0,
        "stage": stage,
    }
    save_progress(progress)

    spec = drill / ("variant.md" if args.variant else "README.md")
    reference = drill / ("variant_reference.py" if args.variant else "reference.py")
    target_min = meta(drill)["variant_target_minutes" if args.variant else "target_minutes"]

    print(f"\n{meta(drill)['title']}  [{stage.upper()}]  target {target_min} min\n")
    explained = drill / "EXPLAINED.md"
    print(f"  spec:     {spec.relative_to(ROOT)}")
    if explained.exists():
        print(f"  why:      {explained.relative_to(ROOT)}  (how and why, when you're stuck)")
    print(f"  write in: {os.path.relpath(target, ROOT)}")
    if saved_note:
        print(saved_note)
    if stage == "copy":
        print(f"  copy:     {reference.relative_to(ROOT)}")
        print("\n  Put the reference beside your editor and TYPE it. No pasting.")
        print("  Say each line's purpose out loud as you type it.")
    else:
        print("\n  Reference closed. Write it from memory, narrating as if to an interviewer.")
        print("  Stuck for more than 2 minutes? Peek at ONE line and carry on. The rep still counts, but it'll be slow.")
    flag = " --variant" if args.variant else ""
    print(f"\n  Clock started. When the tests should pass:  drill check {drill.name[:2]}{flag}")
    print(f"  Interrupted? drill pause {drill.name[:2]}{flag}   (resume / cancel also work)\n")
    return 0


def cmd_pause(args) -> int:
    drill, kind, progress, _entry, clock = open_clock(args)
    if not clock.get("running_since"):
        print(f"Already paused at {fmt_secs(clock_elapsed(clock))}.")
        return 0
    # Bank the time run so far, then stop counting.
    clock["elapsed"] = clock_elapsed(clock)
    clock["running_since"] = None
    save_progress(progress)
    flag = " --variant" if args.variant else ""
    print(f"Paused at {fmt_secs(clock['elapsed'])}. Your attempt file is untouched.")
    print(f"Pick it up with:  drill resume {drill.name[:2]}{flag}")
    return 0


def cmd_resume(args) -> int:
    drill, kind, progress, _entry, clock = open_clock(args)
    if clock.get("running_since"):
        print(f"Already running: {fmt_secs(clock_elapsed(clock))} so far.")
        return 0
    clock["running_since"] = datetime.now().isoformat()
    save_progress(progress)
    target_min = meta(drill)["variant_target_minutes" if kind == "variant" else "target_minutes"]
    left = target_min * 60 - clock["elapsed"]
    print(f"Running again at {fmt_secs(clock['elapsed'])}. "
          + (f"{fmt_secs(left)} left to stay on target." if left > 0 else "Already over target, so finish it anyway."))
    return 0


def cmd_cancel(args) -> int:
    drill, kind, progress, entry, clock = open_clock(args)
    entry["started"].pop(kind, None)
    save_progress(progress)
    print(f"Clock discarded after {fmt_secs(clock_elapsed(clock))}; no rep logged. "
          f"Your attempt file is untouched.\nStart fresh whenever:  drill start {drill.name[:2]}")
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
    progress = load_progress()
    entry = progress.setdefault(drill.name, {"reps": [], "level": 0})
    clock = get_clock(entry, kind)
    paused = clock is not None and not clock.get("running_since")

    result = run_pytest(drill, kind, "attempt")
    if result.returncode != 0:
        state = "still paused" if paused else "still running"
        print(f"\nNot yet. Read the first failure, fix it, run check again. The clock is {state}.")
        return 1

    if clock is None:
        print("\nPassed, but no clock was running (use `drill start` first). Rep not logged.")
        return 0

    seconds = clock_elapsed(clock)
    stage = clock["stage"]
    entry["started"].pop(kind, None)
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
    if seconds > target_min * 60 * 3:
        # Almost always a clock left running overnight rather than a genuinely slow rep.
        print(f"  That's a long way over {target_min} min. If you walked away without pausing, ignore the\n"
              f"  time on this one and use `drill pause` next time.")
    return 0


CARD_RE = re.compile(r"^### (.+?)\n+```python\n(.*?)```", flags=re.M | re.S)
MARKER_RE = re.compile(r"^# --- (\d+)\. (.+?)\s*$", flags=re.M)
PATTERN_SHEET_HEADER = """\
# drill flash - {count} cards, {when}
#
# Type each idiom from memory in the space under its marker. Keep the `# ---` lines:
# they tell `drill flash --check` where one answer ends and the next begins.
# Save the file, then come back to this terminal.

"""


def load_cards() -> list[tuple[str, str]]:
    cards = CARD_RE.findall((ROOT / "PATTERNS.md").read_text())
    if not cards:
        sys.exit("No cards found in PATTERNS.md")
    return cards


def card_history(progress: dict) -> dict:
    return progress.setdefault("_patterns", {})


def same_code(attempt: str, answer: str) -> tuple[bool, str | None]:
    """Compare on structure, not formatting: whitespace and comments don't count, names do."""
    try:
        mine = ast.dump(ast.parse(textwrap.dedent(attempt)))
    except SyntaxError as exc:
        return False, f"syntax error: {exc.msg} (line {exc.lineno})"
    if not attempt.strip():
        return False, "left blank"
    theirs = ast.dump(ast.parse(textwrap.dedent(answer)))
    return mine == theirs, None


def grade_sheet(path: Path, cards: dict[str, str]) -> int:
    text = path.read_text()
    sections = MARKER_RE.split(text)[1:]          # [number, title, body, number, title, body, ...]
    if not sections:
        sys.exit(f"No `# ---` markers left in {path.name}; can't tell the answers apart.")

    progress = load_progress()
    history = card_history(progress)
    # Re-marking the same unchanged sheet shouldn't inflate your record: show the result,
    # log nothing. Retyping the misses and marking again DOES count, which is the point.
    marked = progress.setdefault("_patterns_marked", {})
    # A stable digest: builtins.hash() is salted per process, so it never matched across runs.
    fingerprint = hashlib.sha256(text.encode()).hexdigest()
    already = marked.get(path.name) == fingerprint
    passed = 0
    results = []

    for i in range(0, len(sections), 3):
        title, body = sections[i + 1], sections[i + 2]
        answer = cards.get(title)
        if answer is None:
            results.append((title, False, "card not found in PATTERNS.md (title edited?)"))
            continue
        ok, note = same_code(body, answer)
        passed += ok
        results.append((title, ok, note))

        if not already:
            record = history.setdefault(title, {"attempts": 0, "passes": 0})
            record["attempts"] += 1
            record["passes"] += ok
            record["last"] = date.today().isoformat()
            record["last_ok"] = bool(ok)

    marked[path.name] = fingerprint
    save_progress(progress)

    print()
    for title, ok, note in results:
        print(f"{'PASS' if ok else 'FAIL'}  {title}" + (f"   ({note})" if note else ""))

    for title, ok, _ in results:
        if not ok and title in cards:
            body = next(sections[i + 2] for i in range(0, len(sections), 3) if sections[i + 1] == title)
            print(f"\n--- {title} ---")
            diff = difflib.unified_diff(
                textwrap.dedent(body).strip().splitlines(),
                cards[title].strip().splitlines(),
                fromfile="yours", tofile="the card", lineterm="",
            )
            print("\n".join(diff) or "  (nothing typed)")

    scored = "  (unchanged since you last marked it, so not counted again)" if already else ""
    print(f"\n{passed}/{len(results)} from memory.{scored}\n  Sheet kept at {os.path.relpath(path, ROOT)}")
    if passed < len(results):
        print("Retype the ones you missed now, while the correction is fresh, then re-run --check.")
    return 0


def cmd_flash(args) -> int:
    cards = dict(load_cards())

    if args.stats:
        history = card_history(load_progress())
        if not history:
            print("No flashcard attempts logged yet. Start one:  drill flash 5")
            return 0
        rows = sorted(history.items(), key=lambda kv: (kv[1]["passes"] / kv[1]["attempts"], -kv[1]["attempts"]))
        print(f"{'card':<62} {'tried':>5} {'got':>4}  last")
        for title, r in rows:
            print(f"{title[:60]:<62} {r['attempts']:>5} {r['passes']:>4}  "
                  f"{r.get('last', '-')}{'' if r.get('last_ok') else '  <- missed'}")
        return 0

    if args.check or args.cancel:
        sheets = sorted((ATTEMPTS / "patterns").glob("*.py")) if (ATTEMPTS / "patterns").exists() else []
        if not sheets:
            sys.exit("No flashcard sheet found. Start one:  drill flash 5")
        if args.cancel:
            sheets[-1].unlink()
            print(f"Deleted {sheets[-1].name}, nothing logged.")
            return 0
        return grade_sheet(sheets[-1], cards)

    if args.reveal:                                # the old behaviour: no file, no marking
        picks = random.sample(list(cards.items()), min(args.n, len(cards)))
        for i, (prompt, answer) in enumerate(picks, 1):
            print(f"[{i}/{len(picks)}] {prompt}")
            input("   ...press Enter to reveal ")
            print("\n" + "\n".join("    " + line for line in answer.rstrip().splitlines()) + "\n")
        return 0

    # Default: write a sheet, open it, grade what comes back.
    history = card_history(load_progress())

    def weakness(item) -> tuple:
        record = history.get(item[0])
        if record is None:
            return (1, 0)                          # never tried comes after a proven miss
        if not record.get("last_ok"):
            return (0, record["passes"] / record["attempts"])   # missed last time: drill it first
        return (2, record["passes"] / record["attempts"])

    pool = sorted(cards.items(), key=weakness) if args.weak else random.sample(list(cards.items()), len(cards))
    picks = pool[:min(args.n, len(cards))]

    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    sheet = ATTEMPTS / "patterns" / f"{stamp}.py"
    sheet.parent.mkdir(parents=True, exist_ok=True)
    for n in range(2, 100):                        # two sheets in the same second must not collide
        if not sheet.exists():
            break
        sheet = sheet.with_name(f"{stamp}_{n}.py")
    body = PATTERN_SHEET_HEADER.format(count=len(picks), when=f"{datetime.now():%Y-%m-%d %H:%M}")
    body += "\n\n".join(f"# --- {i}. {title}\n\n" for i, (title, _) in enumerate(picks, 1))
    sheet.write_text(body)

    print(f"\n{len(picks)} cards, written to {os.path.relpath(sheet, ROOT)}:\n")
    for i, (title, _) in enumerate(picks, 1):
        print(f"  {i}. {title}")

    editor = os.environ.get("EDITOR") or (shutil.which("code") and "code")
    if editor and not args.no_open:
        subprocess.Popen([editor, str(sheet)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"\nOpened in {os.path.basename(editor)}. Type each one from memory, then save.")
    else:
        print("\nOpen that file and type each one from memory, then save.")

    if not sys.stdin.isatty():
        print("\nMark it with:  drill flash --check")
        return 0

    try:
        answer = input("\n[Enter] mark it   [s] leave it for later   [c] cancel and delete: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        # Ctrl+C here means "I'm done for now", not "crash at me".
        print(f"\n\nLeft unmarked. It's still there: drill flash --check when you want it marked.")
        return 0

    if answer.startswith("c"):
        sheet.unlink()
        print("Sheet deleted, nothing logged.")
        return 0
    if answer.startswith("s"):
        print("Left for later. Mark it with:  drill flash --check")
        return 0
    return grade_sheet(sheet, cards)


TOC_START = "<!-- toc: generated by `drill toc`, do not edit by hand -->"
TOC_END = "<!-- end toc -->"


def github_slug(heading: str) -> str:
    """GitHub's anchor rules: lowercase, drop punctuation, spaces to hyphens.

    Emphasis is resolved before slugging, because GitHub slugs the RENDERED text:
    a bare __main__ renders as bold "main" and loses its underscores, while
    `__main__` in a code span keeps them.
    """
    rendered = []
    for part in re.split(r"(`[^`]*`)", heading):
        if part.startswith("`"):
            rendered.append(part.strip("`"))        # code span: taken literally
        else:
            part = re.sub(r"\*\*(.+?)\*\*", r"\1", part)
            part = re.sub(r"__(.+?)__", r"\1", part)
            rendered.append(part)

    slug = "".join(rendered).strip().lower()
    slug = "".join(ch for ch in slug if ch.isalnum() or ch in " -_")
    return slug.replace(" ", "-")


def build_toc(text: str) -> str:
    lines = [TOC_START, "", "## Contents", ""]
    seen: dict[str, int] = {}
    for line in text.splitlines():
        if line.startswith("## ") and not line.startswith("## Contents"):
            heading = line[3:].strip()
        elif line.startswith("### "):
            heading = line[4:].strip()
        else:
            continue
        slug = github_slug(heading)
        # GitHub disambiguates repeats by appending -1, -2 ... so mirror that.
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        anchor = slug if not count else f"{slug}-{count}"
        indent = "" if line.startswith("## ") else "  "
        prefix = "**" if line.startswith("## ") else ""
        lines.append(f"{indent}- {prefix}[{heading}](#{anchor}){prefix}")
    lines += ["", TOC_END]
    return "\n".join(lines)


def cmd_toc(args) -> int:
    path = ROOT / "PATTERNS.md"
    text = path.read_text()
    if TOC_START not in text or TOC_END not in text:
        sys.exit(f"No toc markers in {path.name}. Add {TOC_START} and {TOC_END} where it should go.")

    before, rest = text.split(TOC_START, 1)
    _, after = rest.split(TOC_END, 1)
    updated = before + build_toc(text) + after

    if args.check:
        if updated != text:
            print("BAD PATTERNS.md contents list is out of date; run: drill toc")
            return 1
        print("ok  PATTERNS.md contents list is current")
        return 0

    path.write_text(updated)
    print(f"{'wrote' if updated != text else 'same '} contents list in PATTERNS.md")
    return 0


SAMPLE_HEADER = """<!-- Generated by `drill sample {number} --write` from sample.py, which runs the
     reference solution. Do not edit by hand: your changes will be overwritten. -->

# {number} · {title}

*Sample output: what the model solution actually produces, on the input shown.*

"""


def cmd_sample(args) -> int:
    """Run each drill's sample.py, which exercises the reference and prints what it produces."""
    drills = [find_drill(r) for r in args.drills] if args.drills else all_drills()
    failures = 0

    for d in drills:
        script = d / "sample.py"
        if not script.exists():
            print(f"--  {d.name}: no sample.py")
            continue

        # Run it as its own process so a sample can't leak state into the next one.
        result = subprocess.run([sys.executable, str(script)], cwd=ROOT, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"BAD {d.name}: sample.py exited {result.returncode}\n{result.stderr}")
            failures += 1
            continue

        page = SAMPLE_HEADER.format(number=d.name[:2], title=meta(d)["title"]) + result.stdout
        out_file = d / "SAMPLE_OUTPUT.md"

        if args.write:
            changed = not out_file.exists() or out_file.read_text() != page
            out_file.write_text(page)
            print(f"{'wrote' if changed else 'same '} {out_file.relative_to(ROOT)}")
        elif args.check:
            # Samples must be reproducible: a drifting one means the docs no longer match the code.
            if not out_file.exists():
                print(f"BAD {d.name}: SAMPLE_OUTPUT.md missing; run drill sample --write")
                failures += 1
            elif out_file.read_text() != page:
                print(f"BAD {d.name}: SAMPLE_OUTPUT.md is stale, the sample isn't deterministic, or a\n"
                      f"    local tool version words an error differently. Diff it:\n"
                      f"    diff <(python3 {(d / 'sample.py')}) {(d / 'SAMPLE_OUTPUT.md').relative_to(ROOT)}")
                failures += 1
            else:
                print(f"ok  {d.name}")
        else:
            print(result.stdout)

    return 1 if failures else 0


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


LADDER = """
The ladder, one drill at a time:
  1 STUDY    drills/NN_*/README.md (the task), EXPLAINED.md (the why), reference.py (the answer)
  2 COPY     drill start NN            type the reference out beside you; no pasting
  3 RECALL   drill start NN            reference closed, from memory, against the clock
  4 VARY     drill start NN --variant  same patterns, different problem

A typical session:  drill flash 5   ->   drill due   ->   drill start NN   ->   drill check NN
Interrupted:        drill pause NN  ->   drill resume NN   (or drill cancel NN to bin the rep)
Details for one command:  drill help start
"""

DRILL_ARG_HELP = "drill number or name, e.g. 01 or log_parsing"


def cmd_help(args) -> int:
    parser, commands = build_cli()
    if args.topic is None:
        parser.print_help()
        print(LADDER)
        return 0
    if args.topic not in commands:
        print(f"No command called {args.topic!r}. Try one of: {', '.join(commands)}")
        return 1
    commands[args.topic].print_help()
    return 0


def build_cli() -> tuple[argparse.ArgumentParser, dict[str, argparse.ArgumentParser]]:
    parser = argparse.ArgumentParser(prog="drill", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    # Not required: bare `drill` should teach, not scold. main() falls back to help.
    sub = parser.add_subparsers(dest="command", metavar="command")
    commands: dict[str, argparse.ArgumentParser] = {}

    def add(name: str, func, help_text: str, description: str | None = None):
        p = sub.add_parser(name, help=help_text, description=description or help_text,
                           formatter_class=argparse.RawDescriptionHelpFormatter)
        p.set_defaults(func=func)
        commands[name] = p
        return p

    add("due", cmd_due, "what to do today: reviews that are due, plus the next new drill")
    add("list", cmd_list, "every drill: target, reps, best recall time, next due, any rep in progress")

    p = add("start", cmd_start, "begin a rep: fresh attempt file, clock starts",
            "Begin a rep.\n\n"
            "Copies the stub into attempts/ and starts the clock. Any previous attempt is kept\n"
            "under its own timestamp. The stage is chosen for you (copy the first time, recall\n"
            "after that) unless you pass --stage.")
    p.add_argument("drill", help=DRILL_ARG_HELP)
    p.add_argument("--variant", action="store_true", help="the variant problem instead of the main one")
    p.add_argument("--stage", choices=STAGES,
                   help="force the stage: copy (reference open), recall (from memory), variant")

    p = add("check", cmd_check, "run the tests; a pass logs the rep and schedules the next",
            "Run the drill's tests against your attempt.\n\n"
            "A pass logs the rep and sets the next due date: a recall inside the target time\n"
            "pushes it out (1, 2, 4, 7, 14, 30 days), over target brings it back tomorrow.\n"
            "A failure changes nothing and leaves the clock running.")
    p.add_argument("drill", help=DRILL_ARG_HELP)
    p.add_argument("--variant", action="store_true", help="check the variant attempt")

    for name, func, help_text in (
        ("pause", cmd_pause, "called away mid-rep: stop the clock, keep your file"),
        ("resume", cmd_resume, "start the clock again where it stopped"),
        ("cancel", cmd_cancel, "abandon the rep: nothing logged, your file kept"),
    ):
        p = add(name, func, help_text)
        p.add_argument("drill", help=DRILL_ARG_HELP)
        p.add_argument("--variant", action="store_true", help="act on the variant rep")

    p = add("flash", cmd_flash, "type idiom flashcards from memory and have them marked",
            "Drill the idioms in PATTERNS.md.\n\n"
            "Writes a sheet of prompts into attempts/patterns/, opens it in your editor, and\n"
            "marks what you typed against the cards when you come back. Marking compares the\n"
            "code structure, so spacing and comments don't count against you, but names do.\n"
            "Every attempt is logged: see drill flash --stats, and drill flash --weak 5 to\n"
            "drill the ones you keep missing.")
    p.add_argument("n", nargs="?", type=int, default=5, help="how many cards (default: 5)")
    p.add_argument("--weak", action="store_true", help="pick the cards you've missed or never tried")
    p.add_argument("--check", action="store_true", help="mark the most recent sheet again")
    p.add_argument("--cancel", action="store_true", help="delete the most recent sheet, log nothing")
    p.add_argument("--stats", action="store_true", help="your record per card, worst first")
    p.add_argument("--reveal", action="store_true", help="old behaviour: show answers, mark nothing")
    p.add_argument("--no-open", action="store_true", help="don't launch an editor")

    p = add("sample", cmd_sample, "show what a drill's solution actually produces",
            "Show what the model solution produces, by running it.\n\n"
            "Each drill's sample.py exercises reference.py on realistic input and prints the\n"
            "result. --write regenerates the SAMPLE_OUTPUT.md files; --check fails if any is\n"
            "stale, which also catches a sample that isn't deterministic.")
    p.add_argument("drills", nargs="*", help="drills to run (default: all)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--write", action="store_true", help="regenerate SAMPLE_OUTPUT.md")
    g.add_argument("--check", action="store_true", help="fail if any SAMPLE_OUTPUT.md is out of date")

    p = add("verify", cmd_verify, "self-test the course: references pass, stubs fail",
            "Self-test of the course, not of you.\n\n"
            "Checks that every model solution passes its tests and every stub passes none.\n"
            "Run it after adding or editing a drill. No arguments means all of them.")
    p.add_argument("drills", nargs="*", help="drills to check (default: all)")

    p = add("toc", cmd_toc, "rebuild the clickable contents list in PATTERNS.md",
            "Rebuild the contents list in PATTERNS.md from its headings.\n\n"
            "Run it after adding or renaming a card. --check fails if the list is stale.")
    p.add_argument("--check", action="store_true", help="fail if the contents list is out of date")

    p = add("help", cmd_help, "this help, or detail on one command")
    p.add_argument("topic", nargs="?", help="a command name, e.g. start")

    return parser, commands


def main(argv: list[str] | None = None) -> int:
    parser, _ = build_cli()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):        # bare `drill`: show the same thing as `drill help`
        parser.print_help()
        print(LADDER)
        return 0
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
