"""Run the drill 12 reference on realistic input and print what it produces.

Output must be byte-identical every run, so `drill sample --check` can catch drift.
Two things here are inherently variable and are substituted for stable placeholders:
the measured duration from `timed` (shown as <measured>) and the OS-assigned port
(shown as <port>). Both substitutions are visible in the code below.
"""

import re
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import reference
import variant_reference

print("## The main problem: a metrics store and an endpoint\n")
print("Record some work. Counters take optional labels; `timed` feeds a summary:\n")
print("```python")
print("""m = Metrics()
m.inc("jobs_total")
m.inc("http_requests_total", {"method": "GET", "path": "/api/users", "code": "200"})
m.inc("http_requests_total", {"code": "200", "method": "GET", "path": "/api/users"})
#      ^ the SAME series as the line above: same labels, different order
m.inc("http_requests_total", {"code": "500", "path": "/api/orders", "method": "POST"})
m.inc("bytes_written_total", value=4096)
m.observe("job_seconds", 0.25)          # two explicit observations, so the
m.observe("job_seconds", 0.75)          # sample output stays reproducible

with timed(m, "scrape_seconds"):        # the real timer: duration is measured
    do_work()""")
print("```\n")

metrics = reference.Metrics()
metrics.inc("jobs_total")
metrics.inc("http_requests_total", {"method": "GET", "path": "/api/users", "code": "200"})
metrics.inc("http_requests_total", {"code": "200", "method": "GET", "path": "/api/users"})
metrics.inc("http_requests_total", {"code": "500", "path": "/api/orders", "method": "POST"})
metrics.inc("bytes_written_total", value=4096)
metrics.observe("job_seconds", 0.25)
metrics.observe("job_seconds", 0.75)

with reference.timed(metrics, "scrape_seconds"):
    sum(range(1000))

print("`render()` produces Prometheus text exposition format:\n")
print("```text")
rendered = metrics.render()
# The one measured value in the sample. Substituted so the file is byte-identical every run.
rendered = re.sub(r"(scrape_seconds_sum )\S+", r"\1<measured>", rendered)
print(rendered.rstrip())
print("```\n")

print("Reading that: the two `/api/users` increments landed on ONE series at 2.0, even though the\n"
      "second call passed the same labels in a different order — they're sorted into a tuple key,\n"
      "so label order carries no meaning, exactly as in Prometheus itself. Had they not been\n"
      "sorted you would get two half-counted series and a graph that silently understates traffic.\n"
      "Each metric family gets a single `# TYPE` line, and output is sorted,\n"
      "so two scrapes of unchanged state diff cleanly. A summary renders as two samples, `_sum`\n"
      "and `_count`: fixed memory per series however many observations arrive, at the cost of no\n"
      "real percentiles later. `scrape_seconds_sum` is the measured duration, replaced here with\n"
      "a placeholder so this page doesn't change on every run.\n")

print("Labels are escaped on the way out, because a value may contain quotes or newlines:\n")
print("```text")
escaped = reference.Metrics()
escaped.inc("errors_total", {"msg": 'he said "no such file"\nretrying', "path": "C:\\logs"})
print(escaped.render().rstrip())
print("```\n")

print("Reading that: backslashes are escaped before quotes, never after — do it the other way and\n"
      "the backslashes you just inserted get escaped a second time, corrupting every scrape.\n")

# ---------------------------------------------------------------- the HTTP server

print("## The main problem: serving it over HTTP\n")


def get(url):
    """Returns (status, content-type, body); an HTTPError IS the response for 4xx/5xx."""
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, response.headers["Content-Type"], response.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.headers["Content-Type"], e.read().decode()


def db_check():
    raise ConnectionError("db unreachable")        # a check that CRASHES, not one that returns False


checks = {"disk": lambda: True, "queue": lambda: False, "db": db_check}

healthy_server = reference.make_server(metrics, {"disk": lambda: True, "queue": lambda: True})
sick_server = reference.make_server(reference.Metrics(), checks)

for server in (healthy_server, sick_server):
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()

healthy = f"http://127.0.0.1:{healthy_server.server_address[1]}"
sick = f"http://127.0.0.1:{sick_server.server_address[1]}"

print("```python")
print("""server = make_server(metrics, {"disk": lambda: True, "queue": lambda: True})
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{server.server_address[1]}"      # port 0: the OS picks a free one""")
print("```\n")

print("Four real requests against the running server (the port is an OS-assigned one, shown\n"
      "here as `<port>`):\n")
print("```text")
status, content_type, body = get(healthy + "/metrics")
print(f"GET http://127.0.0.1:<port>/metrics   -> {status} {content_type}")
print(f"    body: {len(body.splitlines())} lines of exposition format, as above")
print()

status, content_type, body = get(healthy + "/healthz")
print(f"GET http://127.0.0.1:<port>/healthz   -> {status} {content_type}")
print(f"    body: {body}")
print()

status, content_type, body = get(sick + "/healthz")
print(f"GET http://127.0.0.1:<port>/healthz   -> {status} {content_type}      # the sick server")
print(f"    body: {body}")
print()

status, content_type, body = get(healthy + "/nope")
print(f"GET http://127.0.0.1:<port>/nope      -> {status} {content_type}")
print(f"    body: {body.rstrip()!r}")
print("```\n")

healthy_server.shutdown()
sick_server.shutdown()

print("Reading that: `/healthz` returns 503, not 500, and names which checks failed — `db` raised\n"
      "a ConnectionError and `queue` returned False, and both count as failures. A check that\n"
      "crashes must never become a 500: a 500 is indistinguishable from the endpoint itself being\n"
      "broken, and it loses the body that tells you which dependency to look at. The list is\n"
      "sorted, so an alert on the body text doesn't flap. Checks run per request, because a\n"
      "cached answer is not health.\n")

# ---------------------------------------------------------------- the variant

print("## The variant: reading a scrape back\n")

SCRAPE_1 = """\
# HELP http_requests_total Total requests.
# TYPE http_requests_total counter
http_requests_total{method="GET",path="/api/users"} 1000
http_requests_total{method="POST",path="/api/orders"} 40
http_requests_total{path="/search",query="a,b"} 7
process_start_time_seconds 1.789e+09
"""

SCRAPE_2 = """\
# TYPE http_requests_total counter
http_requests_total{method="GET",path="/api/users"} 1600
http_requests_total{method="POST",path="/api/orders"} 10
http_requests_total{path="/search",query="a,b"} 7
process_start_time_seconds 1.789e+09
"""

print("Two scrapes 60 seconds apart. Note the `/api/orders` counter went DOWN, which only\n"
      "happens when the process restarted:\n")
print("```text")
print(SCRAPE_1.rstrip())
print()
print("--- 60 seconds later ---")
print()
print(SCRAPE_2.rstrip())
print("```\n")

print("`parse_exposition(...)` then `counter_rate(prev, curr, seconds=60)`:\n")
print("```python")
previous = variant_reference.parse_exposition(SCRAPE_1)
current = variant_reference.parse_exposition(SCRAPE_2)
print(f"len(parse_exposition(scrape_1)) -> {len(previous)}   # comment lines ignored")
print()
rates = variant_reference.counter_rate(previous, current, 60)
print("counter_rate(prev, curr, 60) ->")
for (name, labels), rate in sorted(rates.items(), key=lambda item: (item[0][0], sorted(item[0][1]))):
    pairs = ",".join(f'{k}="{v}"' for k, v in sorted(labels))
    series = f"{name}{{{pairs}}}" if pairs else name       # no braces when unlabelled
    print(f"    {series:<54} {rate:>8.4f}/s")
print("```\n")

print("Reading that: `/api/users` climbed 1000 -> 1600 over 60s, so 10/s. `/api/orders` fell from\n"
      "40 to 10, which a counter cannot do — the process restarted, so the increase is taken as\n"
      "the current value (10 over 60s, 0.1667/s) rather than a nonsensical -0.5/s. Every alert\n"
      "built on a rate depends on that rule; without it, each deploy emits a huge negative spike.\n"
      "The unchanged series reports 0.0/s, and `query=\"a,b\"` survives with its comma intact,\n"
      "because label values are parsed as quoted strings rather than split on commas.")
