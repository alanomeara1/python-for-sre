# 01 · Explained: how and why, line by line

Read this in the Study step, and come back to it whenever you're stuck. `reference.py` shows you
*what* to write. This file is *why* it's written that way, so you can rebuild it from scratch
instead of fishing for a memory.

---

## The mental model

Three functions, each a layer on the one below:

```
parse_line(line)        one line   → one dict, or None if it doesn't fit the format
summarize(lines)        many lines → one report dict
summarize_file(path)    a file     → opens it, hands the lines to summarize()
```

**Why split it three ways?** Each layer has one job and can be tested alone. In an interview say:
"I'll parse a single line first, then fold many lines into a summary, then wrap that for files."
That decomposition is itself part of what's being marked, especially for a manager-level role.

**Memory hook: one, many, file.**

---

## Chunk 1: The imports

```python
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Iterable
```

Each import exists for one job:

| Import | Job |
|---|---|
| `re` | pull fields out of a text line whose shape is fixed but whose content varies |
| `Counter` | tally things without writing `if key not in d: d[key] = 0` |
| `datetime` | turn the timestamp text into a real point in time you can compare and subtract |
| `Path` | accept a `Path` as well as a `str` in the type hint |
| `Iterable` | say "any sequence of strings", not specifically a list |

**If you're stuck:** don't recall the list. Ask what jobs the code does, and the imports follow.

---

## Chunk 2: The regex

```python
LINE_RE = re.compile(
    r'(?P<ip>\S+) \S+ \S+ '
    r'\[(?P<time>[^\]]+)\] '
    r'"(?P<method>[A-Z]+) (?P<path>\S+) \S+" '
    r'(?P<status>\d{3}) '
    r'(?P<bytes>\d+|-) '
    r'(?P<duration>[\d.]+)'
)
```

### Why a regex rather than `line.split()`

`split()` is faster to write and genuinely fine for a fixed-width, space-separated line. It breaks as
soon as a field contains a space: the `[timestamp +0000]` has one, and so does the quoted request.
`"GET /a b HTTP/1.1"` would shift every later field along by one. **Say this trade-off out loud**;
choosing `split()` knowingly is fine, not noticing the problem isn't.

### Why `re.compile` at module level

Compiling turns the pattern text into a matching program. Do it once at import, not once per line,
or you pay that cost a billion times on a big log. (CPython caches compiled patterns internally, so
the real-world difference is small, but interviewers look for the habit and it makes the intent obvious.)

### Why named groups

`(?P<ip>...)` labels a captured field. The alternative, `match.group(1)`, means counting brackets and
renumbering everything when the format changes. Named groups also give you `groupdict()` free.

### How to rebuild the pattern when you're stuck

Put the sample line above a blank line and translate it left to right, piece by piece:

```
10.0.0.1 - - [17/Sep/2026:10:15:32 +0000] "GET /api/users HTTP/1.1" 200 512 0.023
└─ip───┘ └┘└┘ └──────────time──────────┘  └method┘└─path──┘└proto─┘ └st┘└by┘└dur┘
```

| Piece of the line | What you write | Reasoning |
|---|---|---|
| a field you want | `(?P<name>\S+)` | "one or more non-space characters", captured under a name |
| a field you don't want | `\S+` | match it so the pattern stays aligned, but don't capture it |
| `[...]` around the time | `\[(?P<time>[^\]]+)\]` | brackets mean "character class" in regex, so escape them. `[^\]]+` is "anything that isn't a closing bracket", which stops the match running past the `]` |
| `"GET /path HTTP/1.1"` | `"(?P<method>[A-Z]+) (?P<path>\S+) \S+"` | plain quotes are literal. Method is letters, path is non-space, protocol is discarded |
| `200` | `(?P<status>\d{3})` | exactly three digits, so a stray number can't slip in |
| `512` or `-` | `(?P<bytes>\d+\|-)` | `\|` means OR: digits, or a single dash for "no body" |
| `0.023` | `(?P<duration>[\d.]+)` | digits and dots. Inside `[...]` a dot is literal, so no escaping needed |

### Two traps

1. **The trailing space at the end of each line of the pattern.** Adjacent string literals in Python
   are glued together with nothing between them, so `r'...\S+ '` + `r'\[...'` must carry that space
   itself. Lose it and the pattern silently never matches: `parse_line` returns `None` for everything.
2. **The `r` prefix.** In a normal string `\d` survives by luck, but `\b` becomes a backspace
   character and `\n` a newline. Always use raw strings for patterns; there is no downside.

---

## Chunk 3: `parse_line`

```python
def parse_line(line: str) -> dict | None:
    match = LINE_RE.match(line)
    if not match:
        return None

    record = match.groupdict()
    record["time"] = datetime.strptime(record["time"], TIME_FORMAT)
    record["status"] = int(record["status"])
    record["bytes"] = 0 if record["bytes"] == "-" else int(record["bytes"])
    record["duration"] = float(record["duration"])
    return record
```

**Shape: match → bail → groupdict → convert → return.**

- **`.match` vs `.search`:** `match` anchors at the start of the string, which is what you want when
  the line has a fixed layout. Use `search` when the interesting part floats in the middle, as in the
  variant, where a syslog prefix comes first.
- **Return `None`, don't raise.** A single malformed line shouldn't kill a report over a million lines.
  The caller counts them instead. That's a deliberate reliability decision, and worth saying aloud.
- **`groupdict()` gives you every named group as a dict — all values strings.** That's the key fact.
  `"200"` is not `200`, and `"200" >= 500` is a `TypeError` in Python 3.
- **Convert at the edge.** The four conversion lines mean nothing downstream ever has to think about
  types again. This is the "parse, don't validate" habit: turn text into real objects at the boundary,
  then trust them inside.
- **`0 if ... == "-" else int(...)`:** the `-` means "no response body". `int("-")` raises `ValueError`,
  and one such line would abort the whole run. Zero is the honest value.
- **`TIME_FORMAT = "%d/%b/%Y:%H:%M:%S %z"`** is a photograph of the timestamp: `17`/`Sep`/`2026`:`10`:`15`:`32` `+0000`.
  `%b` is the short month name, `%z` the UTC offset. Because `%z` is present, the result is
  timezone-*aware*, so comparing it with `datetime.now(timezone.utc)` works. A naive datetime
  (no `%z`) raises `TypeError` when compared with an aware one, which is the classic 3am bug.

---

## Chunk 4: `summarize`

```python
    status_counts = Counter()
    ip_counts = Counter()
    total = malformed = errors = 0

    for line in lines:
        if not line.strip():
            continue
        record = parse_line(line)
        if record is None:
            malformed += 1
            continue

        total += 1
        status_counts[record["status"]] += 1
        ip_counts[record["ip"]] += 1
        if record["status"] >= 500:
            errors += 1
```

**Memory hook: two Counters, three ints; then skip blank → parse → count bad → count good.**

- **`Counter` is a dict whose missing keys read as 0**, so `counts[key] += 1` needs no setup. Reach for
  it any time the question contains "how many" or "top N".
- **`total = malformed = errors = 0`** binds all three names to the same `0` object. Safe because ints
  are immutable: `total += 1` rebinds `total` to a new int and leaves the others alone. Never do this
  with a mutable default like `a = b = []`, where both names share one list.
- **Guard clauses with `continue`** keep the body flat: handle the boring cases early, leave the happy
  path unindented at the bottom. Nesting the counting inside `if record is not None:` works too, and reads worse.
- **Blank lines are skipped, not counted as malformed.** Files usually end with a newline, and a
  trailing empty line isn't corruption. Counting it would make the report cry wolf.
- **`>= 500` is the error definition.** 5xx means the server broke; 4xx usually means the client asked
  for something silly. Paging on 404s is how teams learn to ignore their alerts.
- **`Iterable[str]`, not `list[str]`:** the function then works on a list, a generator or an open file.
  That is what lets `summarize_file` hand it a file object and stream a 10GB log through constant memory.

### The return dict

```python
    return {
        "total": total,
        "malformed": malformed,
        "status_counts": dict(status_counts),
        "top_ips": ip_counts.most_common(top_n),
        "error_rate": errors / total if total else 0.0,
    }
```

Five keys, in the order the interviewer asked the questions: **how many, how many bad, per status,
top talkers, error rate.**

- **`dict(status_counts)`:** a `Counter` already compares equal to a plain dict, so this is cosmetic.
  It signals "this is a plain result, not a live tally", and it serialises to JSON cleanly.
- **`most_common(n)`** returns `[(ip, count), ...]` highest first, and handles `n` larger than the data.
- **`errors / total if total else 0.0`** is the whole reason the drill exists. An empty file, or one
  where every line is garbage, gives `total == 0` and `ZeroDivisionError` takes down your monitoring
  script at exactly the moment something is already wrong. Say: "zero requests means zero error rate,
  not a crash."

---

## Chunk 5: `summarize_file`

```python
def summarize_file(path: str | Path, top_n: int = 3) -> dict:
    with open(path, encoding="utf-8", errors="replace") as f:
        return summarize(f, top_n=top_n)
```

- **`with`** closes the file even if `summarize` raises. On a long-running process, leaked file handles
  eventually exhaust the limit and everything fails with a confusing `OSError`.
- **Passing `f` itself** is the streaming trick: iterating a file yields one line at a time, so memory
  stays flat no matter the size. `f.read().splitlines()` would pull the whole log into RAM and is the
  single most common mistake in this question.
- **`errors="replace"`** swaps undecodable bytes for `�` instead of raising. Logs get truncated
  mid-write and mixed encodings happen; a monitoring script should survive that.
- **`str | Path`** documents that both work, because `open()` accepts either.

---

## When a test fails

| Failing test | What it's telling you |
|---|---|
| `test_parse_line_types` | regex doesn't match (a dropped trailing space?) or you skipped a conversion |
| `test_parse_line_dash_bytes` | `int("-")` on a body-less response |
| `test_parse_line_malformed_returns_none` | you raised, or returned something truthy, instead of `None` |
| `test_summarize_counts` | blank line counted as malformed, or `total` incremented in the wrong branch |
| `test_summarize_top_ips` | forgot `most_common(top_n)`, or hardcoded 3 |
| `test_summarize_error_rate_is_5xx_only` | counted 4xx as errors (`>= 400`) |
| `test_summarize_empty_input_no_zero_division` | the missing `if total else 0.0` |
| `test_summarize_accepts_generator` | you iterated `lines` twice, or called `len()` on it |
| `test_summarize_file` | read the whole file, or forgot to pass `top_n` through |

`TypeError: 'dict' object is not callable` means you typed `record("key")` instead of `record["key"]`.
Round brackets call, square brackets look up.

---

## The variant: what actually changes

Same skeleton, different log. Four differences worth understanding rather than memorising:

1. **`search` instead of `match`.** The syslog prefix (`Sep 17 10:15:32 bastion sshd[1234]:`) sits
   before the part you care about, so anchoring at the start would fail.
2. **An optional group:** `(?P<invalid>invalid user )?`. The `?` means "zero or one". When absent,
   `match["invalid"]` is `None`, which is exactly the boolean you need: `match["invalid"] is not None`.
3. **One pass, two collections.** `ips_to_block` builds a failure `Counter` *and* an `accepted` set in
   the same loop, because the input may be a generator that can only be read once. Two passes over a
   stream silently gives you an empty second pass. There's a test for this.
4. **A two-key sort:** `key=lambda pair: (-pair[1], pair[0])`. Tuples compare left to right, so this is
   "count descending, then IP ascending". Negating is the trick for "descending on this key only";
   `reverse=True` would reverse the tie-break too and make the output non-deterministic in a different way.

The judgement call to voice: **never auto-block from this list.** A NAT'd office IP would lock out the
whole building. Feed it to fail2ban or a WAF with an expiry, and exclude IPs that have authenticated.
