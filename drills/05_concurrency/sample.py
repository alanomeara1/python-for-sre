"""Run the drill 05 reference on realistic input and print what it produces.

Output must be byte-identical every run, so `drill sample --check` can catch drift.
Everything runs against a local server on a random port. Three deliberate substitutions,
each marked below:
  - measured latencies are shown as <0.00s>: they are real elapsed time.
  - the random ports are displayed as service names.
  - requests' connection errors are clipped, because they embed a port and an object address.
"""

import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import reference
import variant_reference

SLOW_SECONDS = 0.3


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/slow"):
            time.sleep(SLOW_SECONDS)
        status = 500 if self.path.startswith("/error") else 200
        self.send_response(status)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


class QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass                                   # a client that timed out and hung up is expected here


server = QuietServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_address[1]}"


def closed_port_url() -> str:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}/health"


HEALTH, SLOW, ERROR = f"{BASE}/health", f"{BASE}/slow", f"{BASE}/error"
REFUSED = closed_port_url()

# Real URL -> what to print. The ports are assigned by the OS, so they can't appear.
DISPLAY = {
    HEALTH: "http://api.internal/health",
    SLOW: "http://reports.internal/slow",
    ERROR: "http://checkout.internal/error",
    REFUSED: "http://cache.internal/health",
}


def clip_error(error: str | None) -> str | None:
    """requests' messages embed the port and an object address; keep the class and the cause."""
    if error is None or "HTTPConnectionPool" not in error:
        return error
    kind = error.split(":", 1)[0]
    if "timed out" in error:
        return f"{kind}: read timed out"
    return f"{kind}: connection refused"


def display(result: dict) -> dict:
    """The real result dict, with the measured latency replaced by a fixed placeholder."""
    return {**result, "latency": "<0.00s>", "error": clip_error(result["error"])}


print("## The main problem: health-checking a fleet without waiting for it\n")

print("One endpoint at a time first, so the shape of a result is clear. Four outcomes, same\n"
      "four keys every time, so a caller never needs a defensive `.get()`:\n")

print("```python")
for index, (url, timeout, label) in enumerate([
    (HEALTH, 2, "healthy"),
    (ERROR, 2, "up, but returning 500"),
    (REFUSED, 2, "nothing listening"),
    (SLOW, 0.05, "too slow, so we cut it off"),
]):
    result = reference.check_endpoint(url, timeout=timeout)
    if index:
        print()
    print(f"# {label}")
    print(f">>> check_endpoint({DISPLAY[url]!r}, timeout={timeout})")
    print(f"{display(result)}")
print("```")

print("Reading that: `status` is `None` when there was no HTTP response at all, rather than 0,\n"
      "because 0 would be a lie. A 500 is `ok: False` but still carries its status, which is the\n"
      "difference between \"the service is broken\" and \"the service is gone\" — different pages,\n"
      "different runbooks. The last case is the one that matters in production: without\n"
      "`timeout=`, one blackholed host holds a worker thread until the process is restarted.\n")

print("### Eight slow endpoints at once\n")

slow_urls = [f"{SLOW}?n={i}" for i in range(8)]
results = reference.check_endpoints(slow_urls, max_workers=8, timeout=2)

print("```python")
print(">>> results = check_endpoints([8 urls, each ~300ms], max_workers=8, timeout=2)")
print(f">>> len(results)\n{len(results)}")
print(f">>> all(r['ok'] for r in results.values())\n{all(r['ok'] for r in results.values())}")
print("```\n")

print("Reading that: eight requests of roughly 300ms each finished in about the time of the\n"
      "slowest one, not eight times that, because the pool had eight workers waiting on the\n"
      "network in parallel. Drop `max_workers` to 1 and the same batch takes eight times as\n"
      "long — the drill's tests assert exactly that difference. No measured number is printed\n"
      "here, because it would change on every machine and every run.\n")

print("### One dead host must not sink the batch\n")

mixed = [HEALTH, ERROR, REFUSED]
results = reference.check_endpoints(mixed, timeout=2)

print("```python")
print(">>> check_endpoints([api, checkout, cache], timeout=2)")
for url in mixed:
    print(f"{DISPLAY[url]:<38} {display(results[url])}")
print("```\n")

print("Reading that: three results, one per URL, and the refused host did not stop the other\n"
      "two from reporting. That is the whole reason `check_endpoint` returns errors instead of\n"
      "raising them: `as_completed` hands back whatever finishes, in finish order, and the\n"
      "dictionary comprehension maps each future back to the URL it came from.\n")

print("## The variant: is the port even open?\n")

# A real listening socket gives an open port; a bound-then-closed one gives a refused port.
listener = socket.socket()
listener.bind(("127.0.0.1", 0))
listener.listen(1)
open_target = ("127.0.0.1", listener.getsockname()[1])

closed_socket = socket.socket()
closed_socket.bind(("127.0.0.1", 0))
closed_port = closed_socket.getsockname()[1]
closed_socket.close()
closed_target = ("127.0.0.1", closed_port)

TARGET_NAMES = {open_target: ("db.internal", 5432), closed_target: ("cache.internal", 6379)}

results = variant_reference.check_ports([open_target, closed_target], timeout=1.0)

print("```python")
print(">>> check_ports([('db.internal', 5432), ('cache.internal', 6379)], timeout=1.0)")
for target, result in sorted(results.items(), key=lambda kv: TARGET_NAMES[kv[0]]):
    shown = {**result, "latency": "<0.00s>",
             "error": None if result["error"] is None else result["error"].split(":", 1)[0] + ": connection refused"}
    print(f"{str(TARGET_NAMES[target]):<32} {shown}")

summary = variant_reference.summarize(results)
print()
print(">>> summarize(results)")
print(f"{ {state: [TARGET_NAMES[t] for t in targets] for state, targets in summary.items()} }")
print("```\n")

listener.close()

print("Reading that: this proves a TCP handshake completed, not that the service behind the\n"
      "port is healthy — a database mid-crash-recovery accepts connections and answers nothing.\n"
      "It is the right check for \"is the firewall rule live?\" and the wrong one for \"can I\n"
      "serve traffic?\". Note also that `summarize` sorts, so the output is stable enough to\n"
      "diff between runs, which is what makes it safe to feed to another tool.")

server.shutdown()
server.server_close()
