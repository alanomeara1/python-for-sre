"""Run the drill 11 reference on realistic input and print what it produces.

Output must be byte-identical every run, so `drill sample --check` can catch drift:
no wall-clock times, no randomness, no temp paths in the output. The log file lives in a
temporary directory, and only its BASENAME is ever printed.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import reference
import variant_reference

APP_LOG = """\
{"level": "info", "msg": "started", "endpoint": "/api/users"}
{"level": "error", "msg": "db timeout", "endpoint": "/api/orders"}
not json at all

[1, 2, 3]
{"level": "error", "msg": "db timeout", "endpoint": "/api/orders"}
{"level": "info", "msg": "ok", "endpoint": "/api/users"}
"""

tmpdir = tempfile.TemporaryDirectory()
LOG_PATH = Path(tmpdir.name) / "app.log"
LOG_PATH.write_text(APP_LOG)

print("## The main problem: a lazy pipeline\n")
print("`app.log`, with two lines that aren't log records (one isn't JSON at all, one is valid\n"
      "JSON but a list), plus a blank line:\n")
print("```text")
print(APP_LOG.rstrip())
print("```\n")

print("Parsing the whole file, with an error channel for the lines that aren't records:\n")
print("```python")
print("errors = []")
print("records = parse_json_lines(read_lines(path), errors=errors)")
print()
all_errors = []
all_records = list(reference.parse_json_lines(reference.read_lines(LOG_PATH), errors=all_errors))
print(f"len(records)               -> {len(all_records)}")
print("errors (line number, text) ->")
for number, text in all_errors:
    print(f"    line {number}: {text!r}")
print("```\n")

print("Reading that: the blank line is skipped silently (a trailing newline is not corruption),\n"
      "but the two lines that aren't objects are reported with their 1-based line numbers, so you\n"
      "can go straight to them with `sed -n 3p`. They're collected rather than raised: three bad\n"
      "lines in a million is routine, a sudden spike means the format changed upstream.\n")

print("The three stages compose, and nothing is read until the final loop asks for a record:\n")
print("```python")
print("records = parse_json_lines(grep('\"error\"', read_lines(path)))")
print()
records = reference.parse_json_lines(reference.grep('"error"', reference.read_lines(LOG_PATH)))
print(f"type(records)              -> {type(records).__name__}   # nothing has been read yet")
for record in records:
    print(f"    {record}")
print("```\n")

print("Reading that: `grep` passes only 2 of the 7 lines through, so the JSON stage never even\n"
      "sees the corrupt ones — filter early and the expensive stage does less work. Memory is one\n"
      "line at a time whether the file holds 7 lines or 70 million, which is the whole point.\n")

print("`batched(...)` turns a stream into chunks, for a bulk API that takes 100 at a time:\n")
print("```python")
print(f"list(batched(range(7), 3))   -> {list(reference.batched(range(7), 3))}")
print(f"list(batched([], 3))         -> {list(reference.batched([], 3))}")
print("batched([1], 0)              -> ValueError: n must be at least 1")
print("```\n")

print("Reading that: the last batch is short rather than padded, and an empty source yields\n"
      "nothing at all. `n=0` raises instead of yielding forever — a batch size of zero would\n"
      "otherwise 'succeed' having shipped no data, the worst kind of silent failure.\n")

# follow() needs a live writer. The injected sleep IS that writer: each poll appends the next
# chunk, so there is no thread, no race, and no real waiting.
FOLLOW_LOG = Path(tmpdir.name) / "live.log"
FOLLOW_LOG.write_text("old line written before we started\n")
writes = iter(['{"msg": "new 1"}\n{"msg": "new 2"}\n', '{"msg": "half-writ', 'ten"}\n'])


def fake_writer(_seconds):
    """Stands in for a process appending to the log between polls."""
    chunk = next(writes, None)
    if chunk is not None:
        with open(FOLLOW_LOG, "a") as f:
            f.write(chunk)


print("`follow(...)` is `tail -f`. Here the injected `sleep` plays the writer, so the sample is\n"
      "instant and deterministic; in production you would pass the real `time.sleep`:\n")
print("```python")
print("# the file already contains: old line written before we started")
print("# the writer appends, across three polls:")
print('#   1. {"msg": "new 1"}\\n{"msg": "new 2"}\\n      (two whole lines at once)')
print('#   2. {"msg": "half-writ                        (no newline yet!)')
print('#   3. ten"}\\n                                   (the rest of it)')
print()
print("follow(path, poll_interval=0, max_idle_polls=2, sleep=fake_writer) ->")
for line in reference.follow(FOLLOW_LOG, poll_interval=0, max_idle_polls=2, sleep=fake_writer):
    print(f"    {line!r}")
print("```\n")

print("Reading that: the pre-existing line never appears — `follow` seeks to the end first, which\n"
      "is what you want when the file already holds 40GB. The half-written line is held back until\n"
      "its newline arrives, so downstream never sees a truncated record. It stops after 2 idle\n"
      "polls because we asked; `max_idle_polls=None` follows forever, which is the production\n"
      "behaviour.\n")

print("## The variant: bounded-memory aggregation\n")

EVENTS = [
    {"endpoint": "/api/users", "status": 200},
    {"endpoint": "/api/orders", "status": 500},
    {"endpoint": "/api/users", "status": 200},
    {"endpoint": "/healthz"},                      # no status key at all
    {"endpoint": "/api/orders", "status": 500},
    {"endpoint": "/api/users", "status": 404},
    {"endpoint": "/api/orders", "status": 500},
]

print("A stream of request events, one of them missing the `status` key entirely:\n")
print("```python")
for event in EVENTS:
    print(f"  {event}")
print("```\n")

print("`top_k(...)`, `dedupe_consecutive(...)` and `window_counts(...)`:\n")
print("```python")
print(f"top_k(events, k=2, key='endpoint') -> {variant_reference.top_k(EVENTS, 2, 'endpoint')}")
print(f"top_k(events, k=2, key='status')   -> {variant_reference.top_k(EVENTS, 2, 'status')}")
print()

REPEATED = [
    "disk 91% full",
    "disk 91% full",
    "disk 91% full",
    "backup finished",
    "disk 92% full",
]
print(f"lines = {REPEATED}")
print("dedupe_consecutive(lines) ->")
for line, count in variant_reference.dedupe_consecutive(REPEATED):
    print(f"    {count} x {line!r}")
print()

# Fixed epoch seconds. BASE is an exact multiple of 60, so the bucket boundaries are obvious.
BASE = 1_789_000_020
TIMESTAMPS = [BASE, BASE + 20, BASE + 40, BASE + 60, BASE + 90]
print(f"timestamps = {TIMESTAMPS}")
print("#            BASE+0, +20, +40 fall in the first minute; +60 and +90 in the second")
print("window_counts(timestamps, bucket_seconds=60) ->")
for bucket, count in variant_reference.window_counts(TIMESTAMPS, 60):
    plural = "event" if count == 1 else "events"
    print(f"    bucket {bucket} (BASE+{bucket - BASE}) -> {count} {plural}")
print("```\n")

print("Reading that: `top_k` skips the event with no `status` rather than raising, because a\n"
      "heterogeneous event stream is normal. /api/users and /api/orders tie on 3 each, and the\n"
      "tie breaks by first appearance, so repeated runs give the same answer — an unstable top-N\n"
      "makes a dashboard flicker between equals. `dedupe_consecutive` is syslog's 'repeated N\n"
      "times': it collapses ADJACENT duplicates only, so the 92% line stays separate from the 91%\n"
      "ones. `window_counts` holds exactly one bucket at a time and emits each as soon as the next\n"
      "timestamp closes it, which is why it runs on an endless stream.")

tmpdir.cleanup()
