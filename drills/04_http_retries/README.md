# 04 · HTTP with retries: backoff, 5xx/429, Retry-After

**Why this drill:** "Call this flaky API reliably" tests whether you understand failure modes, not just
`requests.get`. What they're really asking: *which* failures do you retry, how long do you wait, and when
do you give up? Getting that wrong is how a retry loop turns a small blip into a retry storm.

## The task, as an interviewer would say it

> Our inventory service sometimes returns 503s and occasionally drops connections. Write a fetch
> that retries sensibly with exponential backoff, respects rate limiting, and gives up with a clear
> error. Don't retry things that will never succeed.

## Contract (what the tests call)

```python
MAX_DELAY = 30.0

class RetryError(Exception): ...

def backoff_delays(base: float, attempts: int, cap: float, rng: Callable[[], float] | None = None) -> list[float]
    # [base * 2**0, base * 2**1, ...] (`attempts` values), each capped at `cap`
    # rng given ("full jitter"): each capped delay is multiplied by rng()   (rng returns 0.0-1.0)

def fetch_with_retry(url: str, attempts: int = 3, base_delay: float = 0.5, timeout: float = 2.0,
                     sleep: Callable[[float], None] = time.sleep,
                     session: requests.Session | None = None) -> requests.Response
    # GET with timeout=timeout
    # retry on: requests.ConnectionError, requests.Timeout, status 429, status >= 500
    # return immediately on anything else (2xx, 3xx, and 4xx other than 429). The caller decides.
    # sleep backoff_delays(base_delay, attempts - 1, MAX_DELAY)[i] between attempts
    # ...unless the response has a numeric Retry-After header: sleep that many seconds (capped at MAX_DELAY)
    # never sleep after the final attempt
    # all attempts failed -> raise RetryError whose message names the attempts and the last error
```

## Patterns you are drilling

- `for attempt in range(1, attempts + 1):` plus a "was this the last one?" check
- `try / except (requests.ConnectionError, requests.Timeout) / else`
- `session.get(url, timeout=timeout)`. **Always** a timeout: requests' default is to wait forever.
- Exponential backoff: `min(base * 2 ** i, cap)`
- `sleep` as a parameter, so tests run instantly and can assert the exact delays

## Say this out loud (what the interviewer listens for)

- "4xx means *my* request is wrong, and retrying won't fix it. 429 is the exception: it's 'slow down', so honour Retry-After."
- "Exponential backoff with jitter. Without jitter, a thousand clients that failed together retry together:
  a thundering herd that keeps the service down."
- "I cap the delay and the attempts. A retry budget is a latency budget: 3 attempts at a 2s timeout plus backoff
  could be around 7.5s, and the *caller's* timeout has to be longer than that."
- "Only retry idempotent requests. GET is safe. Retrying a POST that created an order can create two orders."
- "Retries at every layer multiply: 3 retries in the client × 3 in the proxy × 3 in the service is 27 calls to a struggling backend."

## Traps

- No `timeout=`: one dead backend hangs your worker forever.
- Sleeping after the final attempt, which wastes the caller's time just to raise.
- `Retry-After` can also be an HTTP date. Say so, and handle only the numeric form unless asked.
- Catching bare `Exception`, which also retries your own bugs (`TypeError`) three times.
