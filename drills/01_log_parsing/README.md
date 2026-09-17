# 01 · Log parsing: status codes, top talkers, error rate

**Why this drill:** "Here's an access log, tell me what's going on" is the single most common
SRE coding screen. It is also what you actually do at 3am. If you only get one drill fluent,
make it this one.

## The task, as an interviewer would say it

> We have nginx-style access logs. Write something that tells me the total number of requests,
> how many lines we couldn't parse, the count per status code, the top N client IPs,
> and the 5xx error rate. Assume the file could be several GB.

Log line format:

```
<ip> - - [<dd/Mon/yyyy:HH:MM:SS +zzzz>] "<METHOD> <path> <protocol>" <status> <bytes> <duration_seconds>
```

```
10.0.0.1 - - [17/Sep/2026:10:15:32 +0000] "GET /api/users HTTP/1.1" 200 512 0.023
10.0.0.2 - - [17/Sep/2026:10:15:33 +0000] "POST /api/login HTTP/1.1" 503 - 1.204
```

`bytes` can be `-` (no body), which counts as 0.

## Contract (what the tests call)

```python
def parse_line(line: str) -> dict | None
    # -> {"ip": str, "time": datetime (tz-aware), "method": str, "path": str,
    #     "status": int, "bytes": int, "duration": float}
    # -> None if the line doesn't match

def summarize(lines: Iterable[str], top_n: int = 3) -> dict
    # -> {"total": int,              # lines that parsed
    #     "malformed": int,          # lines that didn't (blank lines are ignored entirely)
    #     "status_counts": {200: 7, 503: 1, ...},
    #     "top_ips": [("10.0.0.1", 4), ...],   # most requests first; ties: any order the Counter gives
    #     "error_rate": float}       # 5xx / total, 0.0 when total is 0

def summarize_file(path: str | Path, top_n: int = 3) -> dict
    # same as summarize(), reading the file line by line
```

## Patterns you are drilling

- `re.compile(r"...(?P<name>...)...")` once at module level, then `.match(line)` + `.groupdict()`
- `collections.Counter` and `.most_common(n)`
- Streaming: `with open(path) as f: for line in f:` never `f.read()` on a GB file
- Converting types at the edge: `int()`, `float()`, `datetime.strptime(..., "%d/%b/%Y:%H:%M:%S %z")`
- Guarding the division when there's no data

## Say this out loud (what the interviewer listens for)

- "I'll stream the file rather than load it. Memory stays constant whatever the file size."
- "I compile the regex once, outside the loop."
- "I count malformed lines instead of crashing. In production, one bad line shouldn't kill the report,
  but a *spike* in malformed lines is itself a signal: a log format change or truncation."
- "Error rate is 5xx only. 4xx is usually the client's fault, so I'd report it separately rather than page on it."
- Extension question you should expect: *"Now do it for the last 5 minutes only"* → filter on
  `record["time"]`, or see drill 08 (sliding windows).

## Traps

- `bytes` of `-` → `int("-")` raises. Handle it.
- `"%b"` month names are locale-dependent; fine for interviews, but worth one sentence.
- Dividing by `total` when every line was malformed.
- Using `line.split()` instead of a regex: it breaks on paths or user agents with spaces. Say so if you choose split for speed.
