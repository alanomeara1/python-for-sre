# 11 · Generator pipelines: streaming, grep, JSON lines, batching, tail -f

**Why this drill:** "The log is 40 GB, now what?" follows every log-parsing answer. Generators are
how Python processes unbounded data in constant memory, and `tail -f` in Python is a common
live-coding ask because it tests file positions, polling and loop termination all at once.

## The task, as an interviewer would say it

> Our services write JSON lines. Build me a small streaming toolkit: read a file lazily, grep it,
> parse the JSON while skipping bad lines (and tell me which ones were bad), batch records so I can
> bulk-ship them to Elasticsearch, and follow a live file like `tail -f`. None of it should hold
> the whole file in memory.

```python
errors = []
lines = read_lines("app.log")
lines = grep(r'"level": "error"', lines)
records = parse_json_lines(lines, errors=errors)
for batch in batched(records, 500):
    ship(batch)
```

## Contract (what the tests call)

```python
def read_lines(path: str | Path) -> Iterator[str]
    # yields each line with the trailing newline removed; streams, doesn't read() the file

def grep(pattern: str, lines: Iterable[str]) -> Iterator[str]
    # yields lines where the regex matches anywhere (re.search semantics)

def parse_json_lines(lines: Iterable[str], errors: list | None = None) -> Iterator[dict]
    # yields parsed JSON objects (dicts). Blank lines are skipped silently.
    # Invalid JSON, or valid JSON that isn't an object: skipped, and if `errors` is a list,
    # append (line_number, line) to it. line_number is 1-based over the lines it was given.

def batched(iterable: Iterable, n: int) -> Iterator[list]
    # lists of up to n items; the last may be shorter. n < 1 -> ValueError.
    # Write it with itertools.islice, NOT itertools.batched (3.12+ only, and the point is to know how).

def follow(path, poll_interval: float = 0.1, max_idle_polls: int | None = None,
           sleep: Callable[[float], None] = time.sleep) -> Iterator[str]
    # tail -f: start at the END of the file and yield lines appended afterwards (newline removed).
    # A partially written line is held back until its newline arrives.
    # When there's no new data, call sleep(poll_interval). After max_idle_polls consecutive empty
    # polls (sleeps with nothing new), stop. None = follow forever.
```

## Patterns you are drilling

- `def f(): with open(...) as fh: for line in fh: yield ...`: the file closes when the generator finishes
- Pipelines: each stage takes an iterable and returns a generator, so nothing runs until someone iterates
- `try: json.loads(line) except json.JSONDecodeError:` (catch the specific exception)
- `enumerate(lines, start=1)` for human line numbers
- `it = iter(iterable)` then `while batch := list(islice(it, n)):`
- `f.seek(0, os.SEEK_END)` then a `readline()` polling loop
- Injecting `sleep` as a parameter so tests don't actually wait (and can write to the file mid-follow)

## Say this out loud (what the interviewer listens for)

- "Every stage is lazy, so memory is one line or one batch, not the file. It also means it works on an
  infinite source like `follow()`."
- "I pass an `errors` list in rather than printing. The caller decides whether 3 bad lines in a million is
  fine or whether a spike means the log format changed."
- "`batched` must call `iter()` first. If I islice a list directly I'd get the first n items forever."
- "In production `tail -f` also has to handle rotation: if the inode changes or the file shrinks, reopen
  it. That's what `tail -F` does. I'd use inotify or just ship with Fluent Bit / Vector rather than
  maintain this, but here's the core loop."
- "`sleep` is injectable, so the test runs instantly and deterministically."

## Traps

- `return [ ... ]` instead of `yield` turns the pipeline eager and blows memory on a big file.
- `islice` on a list (not an iterator) restarts from the beginning each time, so it loops forever.
- In `follow`, yielding a partial line that a writer hasn't finished: `readline()` returns it with no `\n`.
- Catching bare `except:` around `json.loads` also swallows `KeyboardInterrupt`.
- `line.strip()` vs `rstrip("\n")`: stripping all whitespace changes indented content.
