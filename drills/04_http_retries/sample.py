"""Run the drill 04 reference on realistic input and print what it produces.

Output must be byte-identical every run, so `drill sample --check` can catch drift.
Everything runs against a local scripted server on a random port, with a fake `sleep`
that records delays instead of waiting. Two deliberate substitutions, marked below:
  - the server's real URL is displayed as http://payments.internal/charges
  - connection-error text is clipped, because it embeds a port and an object address.
"""

import io
import logging
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import reference
import variant_reference

DISPLAY_URL = "http://payments.internal/charges"


class ScriptedHandler(BaseHTTPRequestHandler):
    """Replies with the next (status, headers) from server.script; the last entry repeats."""

    def do_GET(self):
        script = self.server.script
        status, headers = script.pop(0) if len(script) > 1 else script[0]
        self.server.hits += 1
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), ScriptedHandler)
server.script, server.hits = [(200, {})], 0
SERVER_URL = f"http://127.0.0.1:{server.server_address[1]}/charges"
threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()


def closed_port_url() -> str:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}/charges"


REFUSED_URL = closed_port_url()          # bound once: a second call would pick a different port


def clip(message: str) -> str:
    """Hide the random ports, and the urllib3 detail that carries an object address."""
    message = message.replace(SERVER_URL, DISPLAY_URL).replace(REFUSED_URL, DISPLAY_URL)
    if "HTTPConnectionPool" in message:
        head, _, _ = message.partition("HTTPConnectionPool")
        return head + "<connection refused>"
    return message


def attempt(script, **kwargs):
    """Run one scenario against the scripted server, returning (outcome, recorded sleeps, hits)."""
    server.script, server.hits = script, 0
    sleeps = []
    try:
        response = reference.fetch_with_retry(SERVER_URL, sleep=sleeps.append, **kwargs)
        outcome = f"returned Response [{response.status_code}]"
    except reference.RetryError as exc:
        outcome = f"raised RetryError: {clip(str(exc))}"
    return outcome, sleeps, server.hits


print("## The main problem: a GET that survives a wobbly dependency\n")

print("The delay curve is a pure function, so it can be read without a network at all:\n")

print("```python")
print(f">>> backoff_delays(base=0.5, attempts=5, cap=4.0)\n{reference.backoff_delays(0.5, 5, cap=4.0)}")
print(f">>> backoff_delays(base=1.0, attempts=3, cap=10.0, rng=lambda: 0.5)   # full jitter")
print(f"{reference.backoff_delays(1.0, 3, cap=10.0, rng=lambda: 0.5)}")
print("```\n")

print("Reading that: doubling, then flat once it hits the cap. Without the cap, attempt ten\n"
      "would wait over eight minutes. Jitter multiplies each delay by a random fraction so a\n"
      "thousand clients that failed together don't all return at the same instant — which is\n"
      "how a struggling service gets knocked over a second time.\n")

print("### Four scenarios against a scripted server\n")

print("`sleep` is injected here, so the delays are recorded rather than waited out. `hits` is\n"
      "how many requests the server actually saw:\n")

print("```python")
for index, (label, script, kwargs) in enumerate([
    ("503, 502, then 200: recovers", [(503, {}), (502, {}), (200, {})], {"attempts": 3, "base_delay": 0.5}),
    ("429 with Retry-After: 7", [(429, {"Retry-After": "7"}), (200, {})], {}),
    ("404: a client error, so no retry", [(404, {})], {}),
    ("500 every time: gives up", [(500, {})], {"attempts": 4, "base_delay": 1.0}),
]):
    outcome, sleeps, hits = attempt(script, **kwargs)
    if index:
        print()
    print(f"# {label}")
    print(f">>> fetch_with_retry(url{''.join(f', {k}={v}' for k, v in kwargs.items())})")
    print(f"{outcome}")
    print(f"    slept: {sleeps}   server hits: {hits}")
print("```")

print("Reading that, line by line:\n"
      "- The 5xx run waited 0.5s then 1.0s — two gaps for three attempts, the off-by-one worth\n"
      "  remembering.\n"
      "- `Retry-After: 7` overrode the computed backoff. The server knows when it will be ready;\n"
      "  believing it beats guessing, within the 30s ceiling.\n"
      "- The 404 came back as a value after a single request. Retrying it would fail identically\n"
      "  three times and delay the real error. The *caller* decides what a 404 means.\n"
      "- The give-up case slept 1, 2, 4 and stopped — no sleep after the final attempt, because\n"
      "  waiting before giving up helps nobody.\n")

print("### When there is nothing listening at all\n")

sleeps = []
try:
    reference.fetch_with_retry(REFUSED_URL, attempts=3, base_delay=0.1, sleep=sleeps.append)
except reference.RetryError as exc:
    print("```python")
    print(">>> fetch_with_retry(url, attempts=3, base_delay=0.1)   # nothing listening")
    print(f"RetryError: {clip(str(exc))}")
    print(f"    slept: {sleeps}")
    print("```\n")

print("Reading that: a refused connection is retried like a 5xx, because it is usually a pod\n"
      "restarting. The final message names the attempt count and the last error, so the log\n"
      "line explains itself without anyone reaching for a debugger.\n")

print("## The variant: the same policy as a reusable decorator\n")

# Capture the decorator's own log records, which normally go to stderr.
log_capture = io.StringIO()
handler = logging.StreamHandler(log_capture)
handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
variant_reference.log.addHandler(handler)
variant_reference.log.setLevel(logging.WARNING)

sleeps = []
calls = {"n": 0}


@variant_reference.retry(exceptions=(ConnectionError,), attempts=4, base_delay=0.1, sleep=sleeps.append)
def fetch_inventory():
    calls["n"] += 1
    if calls["n"] < 3:
        raise ConnectionError("connection reset by peer")
    return {"widgets": 42}


print("A flaky call that succeeds on the third try:\n")
print("```python")
print("@retry(exceptions=(ConnectionError,), attempts=4, base_delay=0.1)")
print("def fetch_inventory(): ...")
print()
print(f">>> fetch_inventory()\n{fetch_inventory()}")
print(f"    calls made: {calls['n']}   slept: {sleeps}")
print("    log (stderr):")
for line in log_capture.getvalue().rstrip().splitlines():
    print(f"      {line}")
print("```\n")

print("Reading that: two warnings, then success on the third call, and `functools.wraps` kept\n"
      "the real function name in the log rather than reporting `wrapper`.\n")

print("An exception you did not list is never retried — it is your bug, not the network's:\n")

sleeps = []


@variant_reference.retry(exceptions=(ConnectionError,), attempts=4, sleep=sleeps.append)
def parse_response():
    raise ValueError("expected a list, got a dict")


print("```python")
try:
    parse_response()
except ValueError as exc:
    print(f">>> parse_response()\nValueError: {exc}")
    print(f"    slept: {sleeps}   (raised straight through, no retries)")
print("```\n")

print("And a nonsensical option fails at decoration time, when the module is imported, rather\n"
      "than at 3am on the first failure:\n")

print("```python")
try:
    variant_reference.retry(attempts=0)
except ValueError as exc:
    print(f">>> @retry(attempts=0)\nValueError: {exc}")
print("```\n")

print("Reading that: fail early and loudly. A decorator with `attempts=0` would silently\n"
      "return None for every call it wrapped, which is the kind of bug that takes a day to find.")

server.shutdown()
server.server_close()
