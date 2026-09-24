# 11 · Explained: how and why, line by line

Read this in the Study step, and come back to it whenever you're stuck. `reference.py` shows you
*what* to write. This file is *why* it's written that way, so you can rebuild it from scratch
instead of fishing for a memory.

---

## The mental model

Five small generators that snap together into a pipeline:

```
read_lines(path)              a file   → lines          (source)
grep(pattern, lines)          lines    → fewer lines    (filter)
parse_json_lines(lines)       lines    → dicts          (transform, with an error channel)
batched(records, n)           dicts    → lists of n     (regroup)
follow(path)                  a file   → lines, forever (endless source)
```

**Why generators at all.** A function containing `yield` doesn't run when you call it. It hands
back a generator, and each `next()` runs just far enough to produce one item, then freezes. So
this pipeline holds **one line and one batch** in memory, whether the file is 4 KB or 40 GB. The
same property is what lets the last stage run on an infinite source: `follow()` never ends, and
`grep` over it is still perfectly well-behaved.

Compare the eager version, `return [line for line in f if ...]`, which builds the entire list
before the next stage sees a single item. On a 40 GB log that's an OOM kill, and on an infinite
source it simply never returns.

**Memory hook: source → filter → transform → regroup. Every stage takes an iterable and yields.**

---

## Chunk 1: `read_lines`

```python
def read_lines(path: str | Path) -> Iterator[str]:
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:                  # one line in memory at a time
            yield line.rstrip("\n")
```

- **`with` inside a generator** is fine, and it's the reason this is safe: the file stays open while
  the generator is suspended, and closes when the generator is exhausted. If the consumer abandons
  it early (a `break`), Python throws `GeneratorExit` in at the `yield` when the generator is
  collected, and the `with` still closes the file. Worth knowing precisely, because "doesn't the
  file close on the first yield?" is a standard follow-up question. (Relying on collection timing
  is CPython-specific; `contextlib.closing` or an explicit `.close()` is the belt-and-braces answer.)
- **`for line in f`** is the streaming idiom: a file object is itself an iterator of lines, buffered
  by the OS. `f.read().splitlines()` loads everything and defeats the purpose.
- **`rstrip("\n")`, not `.strip()`.** `.strip()` would also remove leading whitespace, which
  silently changes indented content. Strip only what you mean to strip.
- **`errors="replace"`** keeps a truncated or mixed-encoding log from killing the run on one byte.

---

## Chunk 2: `grep`

```python
def grep(pattern: str, lines: Iterable[str]) -> Iterator[str]:
    regex = re.compile(pattern)         # compile once, not per line
    for line in lines:
        if regex.search(line):
            yield line
```

- **Compile outside the loop.** Same habit as drill 01: the pattern is fixed, the lines are many.
- **`search`, not `match`.** `match` anchors at the start of the string, which would only find
  patterns at the beginning of a line. Grep semantics are "anywhere in the line".
- **Takes `lines`, returns lines.** Because the stage neither opens nor closes anything, it composes
  with any source: a list in a test, `read_lines` in production, `follow` on a live file.

---

## Chunk 3: `parse_json_lines`

```python
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            record = None
        if not isinstance(record, dict):
            if errors is not None:
                errors.append((number, line))
            continue
        yield record
```

- **`enumerate(lines, start=1)`** gives human line numbers. Editors and `sed` count from 1; a bug
  report saying "line 0" wastes someone's afternoon.
- **Catch `json.JSONDecodeError`, not bare `except`.** A bare `except:` also swallows
  `KeyboardInterrupt` and `SystemExit`, so your pipeline ignores Ctrl-C. `JSONDecodeError` is a
  subclass of `ValueError`, so catching `ValueError` works too and is slightly broader than you mean.
- **`isinstance(record, dict)` is not paranoia.** `[1, 2, 3]` and `42` and `"hello"` are all *valid*
  JSON, and none of them is a log record. Without this check, a bare array sails through and the
  next stage fails on `record["level"]` with a confusing `TypeError` far from the cause.
  `test_parse_json_lines_skips_and_reports_bad_lines` includes a `[1, 2, 3]` line for exactly this.
- **The `errors` list is an error *channel*, not a policy.** The function doesn't print, doesn't log,
  doesn't raise. The caller decides whether three bad lines in a million is normal, or whether a
  sudden spike means the log format changed upstream. That separation is the reusable-library habit
  interviewers look for. `errors=None` means "I don't care", and the code must not crash on it.
- **Blank lines skipped silently**, because a trailing newline at end of file isn't corruption.

---

## Chunk 4: `batched`

```python
def batched(iterable: Iterable, n: int) -> Iterator[list]:
    if n < 1:
        raise ValueError("n must be at least 1")
    it = iter(iterable)                 # without this, islice on a list restarts at item 0 forever
    while batch := list(islice(it, n)):
        yield batch
```

### The `iter()` line is the whole drill

`islice(some_list, 3)` starts from the beginning of the list **every time**, because a list is
iterable but not an iterator: each `islice` call asks it for a fresh iterator. So the loop yields
`[1,2,3]`, `[1,2,3]`, `[1,2,3]`… forever, and your bulk-shipping job re-sends the first three
records until the disk fills.

`iter(iterable)` converts it once into an iterator that **remembers its position**, so each
`islice` resumes where the last stopped. Passing an already-iterator (a generator, a file) through
`iter()` is harmless: `iter()` on an iterator returns it unchanged.

That distinction — *iterable* (can produce an iterator) versus *iterator* (has position, consumed
once) — is the single most useful Python-internals fact for this kind of work.

### The walrus loop

`while batch := list(islice(it, n)):` assigns and tests in one step. When the source is exhausted
`islice` gives an empty list, which is falsy, and the loop ends. The `list()` is required: a bare
`islice(...)` object is always truthy, so testing it directly loops forever.

### Why not `itertools.batched`

It exists in 3.12+, and in real code you'd use it. Here the point is that you can build it, and
that you can explain what `iter()` is doing. Say both sentences in an interview.

### Why validate `n`

`n = 0` makes `islice` return nothing, so the loop exits immediately and silently produces no
batches — your job "succeeds" having shipped nothing. A loud `ValueError` beats a silent no-op.

---

## Chunk 5: `follow`, tail -f in Python

```python
    with open(path, encoding="utf-8", errors="replace") as f:
        f.seek(0, os.SEEK_END)          # like tail -f: only lines written from now on
        partial = ""
        idle_polls = 0
        while True:
            chunk = f.readline()
            if chunk:
                idle_polls = 0
                partial += chunk
                if partial.endswith("\n"):          # hold back half-written lines
                    yield partial.rstrip("\n")
                    partial = ""
                continue
            if max_idle_polls is not None and idle_polls >= max_idle_polls:
                return
            idle_polls += 1
            sleep(poll_interval)
```

**Shape: seek to the end → loop → got data? accumulate and maybe emit : else sleep and count.**

- **`f.seek(0, os.SEEK_END)`** means "move 0 bytes relative to the end". That's the definition of
  `tail -f`: you want what happens *next*, not the existing 40 GB. `test_follow_starts_at_end_and_joins_partial_lines`
  writes a line before following and asserts it never appears.
- **The `partial` buffer is the subtle part.** A writer can flush `"partial"` and only later write
  `" done\n"`. `readline()` happily returns the incomplete fragment *without* a newline, because
  at that moment it's genuinely all there is. Yielding it would hand downstream a broken record and
  then a second broken one. So: accumulate, and only emit when you see the terminating newline.
- **Why `readline()` at all, rather than `for line in f`?** A file's iterator uses a read-ahead
  buffer and doesn't cope with a file that keeps growing; `readline()` returns `""` at EOF and can
  be called again once more data arrives.
- **`idle_polls` counts *consecutive* empty polls** and resets to 0 the moment data appears. That
  turns "run forever" into something a test can terminate. `max_idle_polls=None` is the production
  behaviour: follow indefinitely.
- **The order of the last three lines matters.** The give-up check happens *before* the increment
  and the sleep, which is why `max_idle_polls=3` produces exactly three sleeps
  (`test_follow_gives_up_after_max_idle_polls` asserts `sleeps == [0.5, 0.5, 0.5]`).
- **`sleep` is a parameter, and that's the testability trick.** The test passes a fake sleep that
  *writes to the file*, simulating a live writer without a thread, a race, or a real delay. Any
  time you have a loop that waits, injecting the waiter makes it instantly testable. Say this out
  loud; it's a design-for-testability signal.

**Honest limitation:** this doesn't handle log rotation. When `logrotate` renames the file, this
keeps reading the old inode forever; when a file is truncated, it never notices the file shrank.
Real `tail -F` re-`stat`s the path and reopens on inode change or shrink. In production you'd ship
with Fluent Bit or Vector rather than maintain this. Say that, then show the core loop.

---

## When a test fails

| Failing test | What it's telling you |
|---|---|
| `test_read_lines_strips_newline_only` | you used `.strip()` and lost leading whitespace |
| `test_read_lines_is_lazy` | you returned a list, or read the whole file, instead of yielding |
| `test_grep` | `match` instead of `search`, so mid-line matches were missed |
| `test_grep_is_lazy_on_infinite_input` | you built a list from `lines`, which never finishes on an endless source |
| `test_parse_json_lines_skips_and_reports_bad_lines` | no `isinstance(..., dict)` check, or wrong line numbering (`start=0`) |
| `test_parse_json_lines_without_errors_list` | crashed on `errors=None` instead of just skipping |
| `test_pipeline_end_to_end` | a stage that consumes its input twice, or returns a list mid-pipeline |
| `test_batched` | off-by-one in the slice size, or the final short batch dropped |
| `test_batched_works_on_a_list_and_infinite_iterator` | the missing `iter()`: the list case repeats the same batch forever |
| `test_batched_rejects_bad_n` | no `ValueError` for `n < 1` |
| `test_follow_starts_at_end_and_joins_partial_lines` | no `seek(0, SEEK_END)`, or a half-written line yielded instead of buffered |
| `test_follow_gives_up_after_max_idle_polls` | the give-up check placed after the sleep, so the sleep count is off by one |

If a "lazy" test hangs rather than fails, you built a list from an infinite iterator. Look for
`list(...)`, `sorted(...)`, `len(...)` or `in` against the whole stream.

---

## The variant: what actually changes

Aggregation rather than transport. Four differences worth understanding:

1. **Memory is bounded by *cardinality*, not by stream length.** `top_k` keeps a `Counter` of
   distinct values, which is fine for endpoints (hundreds) and dangerous for user IDs on a public
   API (unbounded). The honest interview answer: "at that point I'd move to a Count-Min sketch, or
   HyperLogLog if I only need distinct counts."

2. **`heapq.nlargest(k, ...)` instead of sorting everything.** O(n log k) rather than O(n log n),
   which matters when k is 10 and n is millions. It's also *stable*, and `Counter` preserves
   first-seen insertion order, so ties come out in stream order — deterministic output you can
   diff in a test. (`test_top_k_ties_first_seen_first`.)

3. **`itertools.groupby` groups *adjacent* items**, unlike SQL's `GROUP BY`. That's not a limitation
   here, it's exactly the requirement: syslog's "last message repeated N times" is about runs, not
   totals. The trap is that each group's iterator is invalidated as soon as you advance to the next
   group, so you must consume it immediately — `sum(1 for _ in run)` — and can never stash the
   groups in a list for later.

4. **`window_counts` emits as it goes.** It holds one bucket's count and yields the moment a
   timestamp from a later bucket arrives, plus a final flush after the loop for the last bucket.
   That's what makes it work on an infinite stream, and it's the core of every metrics pipeline.
   `int(ts // bucket_seconds) * bucket_seconds` floors a float timestamp onto an integer bucket
   boundary. Out-of-order input raises rather than miscounting a bucket it has already emitted;
   real pipelines instead use a watermark with an allowed-lateness window, which is worth naming.
