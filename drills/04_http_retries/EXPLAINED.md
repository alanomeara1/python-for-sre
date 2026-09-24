# 04 · Explained: how and why, line by line

Read this in the Study step, and come back whenever you're stuck. `reference.py` shows you *what* to
write. This file is *why* it's written that way, so you can rebuild it instead of fishing for a memory.

---

## The mental model

```
backoff_delays(base, attempts, cap)   how long to wait    (pure: a list of numbers, easy to test)
_should_retry(status)                 what's worth retrying (pure: one boolean)
fetch_with_retry(url, ...)            the loop that uses both
```

Three questions, and the code answers them in that order:

1. **Which failures deserve another go?** Connection errors, timeouts, 429, 5xx. Nothing else.
2. **How long do I wait?** Exponentially longer each time, capped, unless the server told me.
3. **When do I stop?** After `attempts`, raising an error that says what went wrong.

**Memory hook: what to retry, how long to wait, when to stop.**

The deeper idea: **a retry loop is a load amplifier.** Every retry you send to a struggling service is
load it didn't ask for. That's why the delays grow, why there's a cap, and why 4xx is never retried.

---

## Chunk 1: Setup

```python
MAX_DELAY = 30.0


class RetryError(Exception):
    pass
```

- **A named ceiling**, not a magic `30` buried in the loop. It bounds both the computed backoff and
  anything a server asks for via `Retry-After`.
- **A custom exception type** so callers can catch *this* failure specifically. Raising
  `Exception("gave up")` forces them to catch everything, including their own bugs. An empty class
  body is completely normal: the type itself is the information.

---

## Chunk 2: `backoff_delays`

```python
def backoff_delays(base: float, attempts: int, cap: float,
                   rng: Callable[[], float] | None = None) -> list[float]:
    delays = []
    for i in range(attempts):
        delay = min(base * 2 ** i, cap)
        if rng is not None:
            delay *= rng()
        delays.append(delay)
    return delays
```

- **Why a separate function at all?** Because a list of numbers is trivial to test, while "did it sleep
  the right amount" inside a network loop is not. Pull the arithmetic out and the hard part gets easy.
- **`base * 2 ** i`** doubles each time: 0.5, 1.0, 2.0, 4.0. Each failure buys the service twice as much
  breathing room. Precedence is on your side here: `**` binds tighter than `*`.
- **`min(..., cap)`** stops the doubling running away. Without it, attempt 10 waits over eight minutes.
- **`rng` is injected, not called as `random.random()` directly.** Two payoffs: tests pass
  `lambda: 0.5` and assert exact numbers, and the caller chooses whether to jitter at all.
- **Full jitter (`delay *= rng()`)** is the point worth saying aloud. A thousand clients that failed at
  the same instant will otherwise retry at the same instant, and the thundering herd keeps the service
  down. Multiplying by a random 0–1 factor smears them across the window.
- **`range(attempts)` returns `[]` when `attempts` is 0**, which is why `backoff_delays(1.0, 0, 10)`
  is an empty list rather than an error. That falls out of the loop; no special case needed.

**How to rebuild it:** "double it each time, but never more than the cap, and shake it a bit".

---

## Chunk 3: `_should_retry`

```python
def _should_retry(status: int) -> bool:
    return status == 429 or status >= 500
```

- **The whole policy in one line**, named, so the loop reads as prose and the rule can be tested alone.
- **5xx = the server broke.** It may well work in a second. Retrying is reasonable.
- **429 = "you're going too fast".** The one 4xx worth retrying, and the server usually tells you how
  long to wait.
- **Every other 4xx is your fault**: a bad URL, a missing token, a malformed body. Retrying a 404 three
  times gets you three 404s and wastes the caller's latency budget.
- **The leading underscore** marks it as internal. Nothing enforces that in Python; it's a signal to
  readers that it isn't part of the public surface.

---

## Chunk 4: `fetch_with_retry`

```python
def fetch_with_retry(url: str, attempts: int = 3, base_delay: float = 0.5, timeout: float = 2.0,
                     sleep: Callable[[float], None] = time.sleep,
                     session: requests.Session | None = None) -> requests.Response:
    session = session or requests.Session()
    delays = backoff_delays(base_delay, attempts - 1, MAX_DELAY)
    last_error = "no attempts made"
```

- **`sleep` as a parameter** is the trick that makes this testable. Production gets `time.sleep`; tests
  pass `sleeps.append` and assert the exact delays without waiting a single second. Reach for this
  whenever code waits, retries or schedules.
- **`session or requests.Session()`.** A `Session` reuses the underlying TCP connection across requests,
  which matters when you're about to make several to the same host. Accepting one lets a caller
  configure auth, headers or pooling, and lets a test pass a fake.
- **`attempts - 1` delays for `attempts` tries.** Three attempts have two gaps between them. Off-by-one
  here is the most likely bug in the whole drill.
- **`last_error` starts as a string**, so the final message is always meaningful even in odd cases.

```python
    for attempt in range(1, attempts + 1):
        retry_after = None
        try:
            response = session.get(url, timeout=timeout)
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        else:
            if not _should_retry(response.status_code):
                return response
            last_error = f"HTTP {response.status_code}"
            retry_after = response.headers.get("Retry-After")
```

- **`range(1, attempts + 1)`** counts 1..attempts, so `attempt == attempts` reads as "this was the last
  one" without mental arithmetic.
- **`timeout=timeout` on every call.** requests has **no default timeout**: without it, a blackholed
  backend holds the worker forever and your thread pool slowly fills with zombies. This is the single
  most common production mistake with `requests`.
- **Catch the two specific exception types**, not bare `Exception`. Catching everything means a `TypeError`
  in your own code gets retried three times and then reported as a network failure.
- **`try/except/else`.** The `else` block runs only when no exception was raised. Putting the
  response handling there, rather than at the end of `try`, keeps the `except` clause from accidentally
  catching exceptions raised by your own response handling.
- **`return response` on anything not worth retrying.** Note that this includes a 404: the function's
  job is to retry transient failures, and the *caller* decides what a 404 means.
- **`headers.get("Retry-After")`** is read from the response that just failed, before you decide the delay.

```python
        if attempt == attempts:
            break

        delay = delays[attempt - 1]
        if retry_after and retry_after.isdigit():
            delay = min(float(retry_after), MAX_DELAY)
        sleep(delay)

    raise RetryError(f"GET {url} failed after {attempts} attempts; last error: {last_error}")
```

- **Break before sleeping on the last attempt.** Sleeping and then raising wastes the caller's time for
  no possible benefit. `test_gives_up_after_attempts_without_final_sleep` checks exactly this.
- **`delays[attempt - 1]`** because `attempt` starts at 1 and lists start at 0.
- **The server's `Retry-After` wins**, still capped by `MAX_DELAY`: trust it, but don't let a hostile or
  buggy header park your process for an hour.
- **`.isdigit()`** because `Retry-After` is allowed to be an HTTP date (`Wed, 21 Oct 2026 07:28:00 GMT`)
  as well as a number of seconds. Handling only the numeric form is a fair interview choice — say that
  you know the other form exists and would parse it if it mattered.
- **The final message names the attempts and the last error**, so the log line tells you what happened
  without needing a debugger.

---

## When a test fails

| Failing test | What it's telling you |
|---|---|
| `test_backoff_exponential_and_capped` | used `base * attempt` instead of `base * 2 ** i`, or forgot `min(..., cap)` |
| `test_backoff_jitter_uses_rng` | called `random.random()` directly instead of the injected `rng` |
| `test_success_first_try_no_sleep` | you sleep before the first attempt |
| `test_retries_5xx_then_succeeds_with_backoff` | wrong delay sequence: check `attempts - 1` and `delays[attempt - 1]` |
| `test_429_honours_numeric_retry_after` | didn't read the header, or let the computed backoff win over it |
| `test_does_not_retry_other_4xx` | your retry rule is `>= 400` instead of `== 429 or >= 500` |
| `test_gives_up_after_attempts_without_final_sleep` | slept after the final attempt, or raised the wrong type / a message missing the attempt count or status |
| `test_retries_connection_errors` | only caught HTTP status codes, not `requests.ConnectionError` / `requests.Timeout` |
| `test_uses_injected_session_and_timeout` | ignored the `session` argument, or called `get()` without `timeout=` |

---

## The variant: what actually changes

The same retry policy, turned into a reusable `@retry` decorator. Five ideas:

1. **Three nested functions, and each layer exists for a reason.** `retry(...)` takes the *options* and
   returns `decorator`; `decorator(func)` takes the *function*; `wrapper(*args, **kwargs)` takes the
   *call*. That triple-decker is what "decorator with arguments" always looks like. If you can rebuild
   the skeleton, the body is easy:

   ```python
   def retry(options...):
       def decorator(func):
           def wrapper(*args, **kwargs):
               ...
           return wrapper
       return decorator
   ```
2. **`@functools.wraps(func)`** copies `__name__`, `__doc__` and friends onto the wrapper. Without it
   every decorated function is called `wrapper` in logs, tracebacks and `help()`.
3. **Validation happens at decoration time.** `if attempts < 1: raise ValueError` runs when the module is
   imported, not when the function is first called in production at 3am. Fail early, fail on your laptop.
4. **A bare `raise` on the last attempt**, not `raise exc`. Bare `raise` re-raises the current exception
   with its original traceback intact, so the stack shows where it really came from.
5. **The caller chooses which exceptions count.** `exceptions=(ConnectionError,)` means a `ValueError`
   from your own bug propagates immediately instead of being retried five times and buried.

`wrapper.last_attempts` is a counter stuck onto the function object (functions are objects, so you can
attach attributes). Handy for the tests and for a quick metric, but be aware it's shared state on the
function, not per-call: with concurrent callers it's a rough indicator, not a reliable count.
