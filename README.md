# Python for SRE: repetition drills

A short course for building **muscle memory** and **learning Python fast** in the Python that SRE and DevOps work actually
demands: parsing logs, shelling out to commands, retrying flaky HTTP, cleaning up disks, doing SLO
maths. You won't work problems out from scratch here. For each problem you're shown a clean,
production-quality answer, you type it, and then you rebuild it from memory against tests and a
clock until it's automatic.

**Who it's for:** anyone who knows Python fundamentals but hasn't spent years writing it every day,
and needs to get fluent quickly — moving into an SRE or platform role, inheriting the on-call
scripts, or just tired of reaching for the docs to write a `subprocess` call. Free to use and adapt:
see [LICENSE](LICENSE).

Everything runs offline — no cloud account, no API keys, no network — and the only prerequisites are
[uv](https://docs.astral.sh/uv/) and a terminal.

---

## Setup (once)

```bash
cd ~/Projects/python-for-sre
uv sync                                    # Python 3.12 + pytest, requests, pyyaml, boto3, moto

# add to ~/.zshrc so `drill` works from anywhere
alias drill='uv run --project ~/Projects/python-for-sre python ~/Projects/python-for-sre/drill.py'
```

Check everything works: `drill verify` should print `ok` for every drill.

---

## How it works: the four-rung ladder

Every drill is one realistic SRE task. You climb the same four rungs each time:

| Rung | What you do | Why |
|---|---|---|
| **1. Study** (5–10 min) | Read the drill's `README.md` for the task and `SAMPLE_OUTPUT.md` for what the answer produces, then `EXPLAINED.md` for the reasoning, then `reference.py` top to bottom. | You can't memorise what you don't understand, and understanding is what rebuilds a line you've forgotten. Seeing the output first makes the code concrete. |
| **2. Copy** | `drill start 01`. Put `reference.py` beside your editor and **type it** into the attempt file. No pasting. Say each line's purpose out loud. `drill check 01`. | Your fingers learn the shapes: imports, signatures, the loop, the return. |
| **3. Recall** | `drill start 01` again. Reference **closed**. Write it from memory against the clock, then `drill check 01`. | This is the rep that builds memory. Struggling to retrieve it is the point. |
| **4. Vary** | `drill start 01 --variant`. Read `variant.md`, then solve a *different* problem with the same patterns. `drill check 01 --variant`. | Proves you learned the pattern, not the text. Interviewers never ask the exact question you practised. |

### Rules that make it work

- **Type, never paste.** Pasting feels productive and builds nothing.
- **Narrate out loud** during recall, as if the interviewer were listening. Each drill's README has a
  "Say this out loud" section. For a manager role, the trade-offs you mention count as much as the code.
- **The two-minute rule.** Stuck in recall for more than 2 minutes? Look at *one line* of the reference,
  close it, carry on. The rep will run slow, and that's fine: it means you see it again tomorrow.
- **Read the first failing test only.** Fix it, re-run. That's how you'll debug in a live interview too.
- **Fluency, not just correctness.** A pass over the target time is logged but doesn't move the drill
  forward. You repeat it tomorrow until you're under target.

### If you're interrupted

The clock only counts time you're actually at the keyboard:

```bash
drill pause 01       # phone rings, school run, meeting
drill resume 01      # picks up exactly where it stopped
drill cancel 01      # abandon the rep entirely: nothing logged, your file kept
```

`drill list` shows any rep in progress and whether it's running or paused. If you forget to pause and
the time comes out absurd, `drill check` says so; ignore that reading, since only recall times under
target move the schedule anyway.

### Spaced repetition

`drill check` records every pass. A recall that's on target pushes the next review out to
**1 → 2 → 4 → 7 → 14 → 30 days**. Over target: back tomorrow. `drill due` tells you what's up today.

---

## Daily routine (~60 minutes)

```bash
drill flash 5        # 5 min   warm-up: type 5 idioms from memory; it marks them for you
drill due            #         shows today's reviews + the next new drill
drill start NN       # 20 min  reviews: recall reps of whatever is due
                     # 35 min  one NEW drill: study → copy → recall → variant
drill list           #         reps, best recall time, next due date per drill
```

Short day (20 minutes)? Do the flashcards and one due recall. Don't start a new drill.

---

## The drills

Ordered by how often each comes up in real SRE work, which is also roughly how often it comes up in
coding rounds. Short on time?
**Work in this order and stop wherever you run out of road**: 01–05 are the core.

| # | Drill | Main problem | Variant | Core patterns |
|---|---|---|---|---|
| 01 | Log parsing | Access log: status counts, top IPs, 5xx rate | SSH brute-force block list from auth.log | `re` named groups, `Counter`, streaming files |
| 02 | CLI script | Nagios-style disk check with exit codes | TLS certificate expiry checker | `argparse`, `logging`, `main() -> int`, `sys.exit` |
| 03 | Subprocess | Safe command runner + `df` parser | Git helpers for deploy scripts | `subprocess.run`, timeouts, dataclasses |
| 04 | HTTP retries | Fetch with backoff, honour `Retry-After` | Generic `@retry` decorator | `requests`, exponential backoff, decorators |
| 05 | Concurrency | Health-check many endpoints in parallel | Concurrent TCP port checker | `ThreadPoolExecutor`, `as_completed`, `socket` |
| 06 | K8s manifest lint | Find `:latest`, missing limits/probes | Terraform plan: dangerous changes | `yaml.safe_load_all`, nested `.get()`, JSON |
| 07 | Filesystem | Find & clean old large files, rotate | Grandfather-father-son backup retention | `os.walk` + `pathlib`, `os.stat`, dry-run by default |
| 08 | Sliding window | Error-rate alert, per-client rate limiter | Token bucket limiter | `deque`, `defaultdict`, injected clocks |
| 09 | SLO maths | Percentiles, error budget, burn-rate paging | Incident CSV: MTTA / MTTR | `csv`, `datetime`, `statistics` |
| 10 | Intervals | Merge outages, downtime, concurrent outages | On-call gaps & double-booking | sort + merge, sweep line |
| 11 | Generators | `tail -f`, grep, batch pipeline | Bounded-memory top-K & time buckets | `yield`, `islice`, `heapq` |
| 12 | Metrics endpoint | `/healthz` + Prometheus `/metrics` server | Parse exposition, counter rate with resets | `http.server`, `threading.Lock`, context managers |
| 13 | AWS boto3 | Unattached volumes, untagged instances | S3 bucket security audit | paginators, `ClientError`, `moto` tests |

Target times per drill: `drill list`.

### A two-week plan, if you want one

- **Days 1–5:** one new drill a day (01 → 05), plus that day's reviews.
- **Days 6–10:** drills 06–10 the same way. The reviews get longer; that's expected.
- **Days 11–14:** no new drills unless reviews are all on target. Instead, run 3 random recalls a day
  cold (`drill start NN --stage recall`) and do each variant a second time.
- **A light day:** flashcards, plus one recall of 01 and 02. Stop there; cramming doesn't stick.

---

## What's in each drill folder

```
drills/01_log_parsing/
  README.md             the task as an interviewer would put it, the exact contract, what to say, traps
  EXPLAINED.md          how and why, chunk by chunk: the mental model, how to rebuild each part from
                        first principles, what each failing test means. Read when stuck.
  SAMPLE_OUTPUT.md      what the model answer actually prints, on real input, with the edge cases
                        it's built for. Generated by running it, never written by hand.
  sample.py             the runnable demo behind that file (`drill sample NN`)
  reference.py          the model answer: the thing you memorise
  stub.py               signatures only: copied into attempts/ by `drill start`
  test_solution.py      what `drill check` runs
  variant.md            a different problem, same patterns
  variant_reference.py
  variant_stub.py
  test_variant.py
  drill.toml            title, target minutes, patterns drilled
```

Your work goes in `attempts/` and your history in `progress.json`. Both are git-ignored and belong to
you. `drill start` overwrites the attempt file with a fresh stub each rep, saving the previous one
as `solution.prev.py`.

`PATTERNS.md` holds the flashcards: ~35 idioms (argparse skeleton, subprocess with timeout, thread
pool, paginator, retry…) small enough to type in under a minute each.

`drill flash 5` writes the prompts into `attempts/patterns/<timestamp>.py`, opens it in `$EDITOR`,
and marks your answers when you come back. Marking compares the **structure** of the code, so
formatting and comments cost you nothing, but a wrong name or a `%y` where the card says `%Y` is
caught and shown as a diff. Every attempt is logged, so `--weak` can feed you the ones you keep
missing and `--stats` shows where you stand. `--reveal` gives the old show-me-the-answer behaviour,
which is what you want away from a keyboard.

**Called away mid-sheet?** At the prompt, `s` leaves it for later (`drill flash --check` marks it
whenever you come back) and `c` deletes it. Ctrl+C is the same as `s`. Nothing is logged until a
sheet is marked, and re-marking an unchanged sheet doesn't count twice.

## Commands

| Command | Does |
|---|---|
| `drill due` | today's reviews and the next new drill |
| `drill list` | all drills: target, reps, best recall time, next due |
| `drill start NN [--variant] [--stage copy\|recall\|variant]` | fresh attempt file, starts the clock (stage is auto-picked if omitted) |
| `drill check NN [--variant]` | runs the tests; a pass is logged as a rep and schedules the next one |
| `drill pause NN [--variant]` | called away mid-rep: stops the clock, leaves your file alone |
| `drill resume NN [--variant]` | starts the clock again from where it stopped |
| `drill cancel NN [--variant]` | abandons the rep, logs nothing, keeps your file |
| `drill flash [N]` | writes a sheet of N idiom prompts, opens it, marks what you typed |
| `drill flash --weak 5` | the cards you missed last time, or have never tried |
| `drill flash --stats` | your record per card, worst first |
| `drill flash --cancel` | bin the current sheet, log nothing |
| `drill verify [NN ...]` | self-test of the course: every reference passes, every stub fails |
| `drill sample NN` | runs the model solution and shows what it produces on realistic input |
| `drill help [command]` | all commands and the ladder, or the detail on one (`drill help start`) |

`drill sample --write` regenerates the sample pages and `--check` fails if any is stale, which keeps
the docs honest. Treat `--check` as a same-machine guarantee: a couple of samples print a real error
message from `git` or the OS, so a different version can word it differently and report a false
mismatch. Diff it before assuming the code broke.

You can also run the tests directly: `uv run pytest drills/01_log_parsing` tests your attempts.
Put `DRILL_MODE=reference` in front to test the model answers instead.

## Adding a drill

Copy the nine-file layout of an existing drill, and write the tests so they use the `solution` /
`variant` fixtures (see `conftest.py`). A drill is done only when `drill verify NN` prints `ok` for both
halves: the reference passes and the stub passes nothing. That second check catches tests that
can't actually fail.

---

## Corrections log

If something in this course turns out to be wrong (a reference with a bug, bad advice in a README),
record it here with the date when you fix it, rather than silently editing it away.

- **2026-09-23 — `drill start` could destroy a finished attempt.** `start` overwrote the attempt file
  with the stub and kept only a single `.prev.py` backup, which the next `start` overwrote in turn, so a
  completed rep could be lost for good. Fixed: every previous attempt is now kept under its own timestamp
  (`solution.20260923-210302.bak.py`), and `DRILL_HOME` points reps and history at a scratch directory so
  the tool can be exercised without touching real work.
- **2026-09-23 — no way to stop the clock.** A rep interrupted by real life recorded a meaningless time.
  Fixed: `drill pause` / `resume` / `cancel`, and the clock now sums only the stretches you were working.
