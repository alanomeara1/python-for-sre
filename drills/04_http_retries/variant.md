# 04 · Variant: a reusable `@retry` decorator

The same retry loop, pulled out so any function can use it. Decorator factories (a function that
returns a decorator that returns a wrapper) come up a lot in interviews. Three nested `def`s is where
people freeze, so drill the shape until it's automatic.

## The task

> We keep copy-pasting retry loops around boto3 calls, DB connections and HTTP. Write a `@retry(...)`
> decorator: which exceptions to retry, how many attempts, exponential backoff with a cap.
> It must re-raise the original exception at the end, not swallow it.

```python
@retry(exceptions=(ConnectionError, TimeoutError), attempts=5, base_delay=0.2, max_delay=5.0)
def get_leader(cluster: str) -> str:
    ...
```

## Contract

```python
def retry(exceptions: tuple[type[BaseException], ...] = (Exception,), attempts: int = 3,
          base_delay: float = 0.1, max_delay: float = 5.0,
          sleep: Callable[[float], None] = time.sleep)
    # attempts < 1 -> ValueError, raised when retry(...) is called (decoration time, not call time)
    # the returned decorator wraps func with functools.wraps (keeps __name__, __doc__)
    # wrapper(*args, **kwargs):
    #   calls func; on an exception listed in `exceptions`: sleep min(base_delay * 2**(n-1), max_delay)
    #   and try again, where n is the attempt that just failed
    #   other exceptions propagate immediately, with no retry
    #   after the final attempt: re-raise that original exception (plain `raise`), no sleep
    # wrapper.last_attempts: int, how many calls the most recent invocation made
```

## Say this out loud

- "Three layers: `retry(config)` returns `decorator(func)`, which returns `wrapper(*args, **kwargs)`. Config, function, call."
- "`functools.wraps` so logs, tracebacks and `help()` show the real function name, not `wrapper`."
- "Bare `raise` inside the `except` re-raises with the original traceback. `raise exc` from outside would still work,
  but `raise RuntimeError('failed')` would throw away what actually went wrong."
- "Validate `attempts` at decoration time. A config bug should fail at import, not at 3am on the first retry."
- "`last_attempts` on the wrapper is handy for tests and metrics, but it's shared state. With threads I'd emit
  a metric per call instead."
