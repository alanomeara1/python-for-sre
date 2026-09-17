# Patterns: the idioms you should be able to type without thinking

These are flashcards. `drill flash 5` shows five random prompts; **type the answer in a scratch
file before you reveal it**, then compare character for character. The code block is the whole
answer. If yours works but looks different, learn this shape anyway: it's the shape
interviewers recognise.

Format rule (the `flash` command parses it): `### prompt`, then a single python code block.

## Script skeleton

### Minimal production script: logging, main() returning an exit code, the __main__ guard

```python
import logging
import sys

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log.info("starting")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### argparse: positional path, int option with default, boolean flag, parse a given argv

```python
import argparse

parser = argparse.ArgumentParser(description="Clean old files")
parser.add_argument("path")
parser.add_argument("--days", type=int, default=7, help="age threshold")
parser.add_argument("--dry-run", action="store_true")
args = parser.parse_args(argv)          # argv=None means sys.argv[1:]
print(args.path, args.days, args.dry_run)
```

### Read a required environment variable, fail clearly if missing; optional one with a default

```python
import os

token = os.environ.get("API_TOKEN")
if not token:
    sys.exit("API_TOKEN is not set")
region = os.environ.get("AWS_REGION", "eu-west-1")
```

### Log an exception with its traceback, then re-raise

```python
try:
    deploy()
except Exception:
    log.exception("deploy failed")      # logs at ERROR with the traceback
    raise
```

## Files and text

### Stream a large file line by line, skipping blank lines

```python
with open(path, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        process(line)
```

### pathlib: every *.log file under a directory tree, with size and mtime

```python
from pathlib import Path

for p in Path(root).rglob("*.log"):
    if p.is_file():
        st = p.stat()
        print(p, st.st_size, st.st_mtime)
```

### Write a file atomically (so readers never see half a file)

```python
import os
import tempfile

fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
with os.fdopen(fd, "w") as f:
    f.write(data)
os.replace(tmp, path)                   # atomic rename on the same filesystem
```

### Load JSON from a file, and dump a dict as pretty JSON to stdout

```python
import json

with open("config.json") as f:
    config = json.load(f)
print(json.dumps(config, indent=2, sort_keys=True))
```

### Load every document from a multi-doc YAML file safely

```python
import yaml

with open("manifests.yaml") as f:
    docs = [d for d in yaml.safe_load_all(f) if d]
```

### Read a CSV into dicts keyed by header

```python
import csv

with open("incidents.csv", newline="") as f:
    for row in csv.DictReader(f):
        print(row["id"], row["severity"])
```

## Regex

### Compile a regex with named groups once; match a line and get a dict

```python
import re

LINE_RE = re.compile(r"(?P<ip>\S+) .* \"(?P<method>[A-Z]+) (?P<path>\S+) .*\" (?P<status>\d{3})")

m = LINE_RE.match(line)
if m:
    record = m.groupdict()
    status = int(record["status"])
```

### Find all ERROR codes like E1234 in a string

```python
codes = re.findall(r"\bE\d{4}\b", text)
```

## Collections

### Count occurrences and get the top 3

```python
from collections import Counter

counts = Counter(ip for ip in ips)
top = counts.most_common(3)             # [(ip, n), ...]
```

### Group items into lists by a key

```python
from collections import defaultdict

by_host = defaultdict(list)
for event in events:
    by_host[event["host"]].append(event)
```

### Sort dicts by count descending, then name ascending

```python
rows.sort(key=lambda r: (-r["count"], r["name"]))
```

### Keep only the last N seconds of timestamps (sliding window)

```python
from collections import deque

window = deque()
window.append(now)
while window and window[0] <= now - 60:
    window.popleft()
rate = len(window)
```

### Top 5 largest items from a stream without sorting everything

```python
import heapq

biggest = heapq.nlargest(5, files, key=lambda f: f.size)
```

### Dataclass for a result record, with a default

```python
from dataclasses import dataclass, field


@dataclass
class CheckResult:
    name: str
    ok: bool
    latency: float = 0.0
    errors: list[str] = field(default_factory=list)
```

## Time

### Parse an ISO timestamp, get "now" in UTC, compute age in minutes

```python
from datetime import datetime, timezone

started = datetime.fromisoformat("2026-09-17T10:15:00+00:00")
now = datetime.now(timezone.utc)
age_minutes = (now - started).total_seconds() / 60
```

### Parse an nginx timestamp like 17/Sep/2026:10:15:32 +0000

```python
ts = datetime.strptime("17/Sep/2026:10:15:32 +0000", "%d/%b/%Y:%H:%M:%S %z")
```

### Time a block of code correctly

```python
import time

start = time.monotonic()               # never time.time() for durations: wall clocks jump
do_work()
elapsed = time.monotonic() - start
```

## Processes

### Run a command safely: list args, capture text, timeout, raise on failure

```python
import subprocess

result = subprocess.run(
    ["kubectl", "get", "pods", "-o", "json"],
    capture_output=True, text=True, timeout=30, check=True,
)
pods = json.loads(result.stdout)
```

### Handle a command that fails or hangs

```python
try:
    subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=True)
except subprocess.TimeoutExpired:
    log.error("timed out: %s", cmd)
except subprocess.CalledProcessError as e:
    log.error("exit %s: %s", e.returncode, e.stderr.strip())
```

## HTTP

### GET JSON with requests: timeout, raise on HTTP error

```python
import requests

resp = requests.get(url, timeout=5)
resp.raise_for_status()
data = resp.json()
```

### Retry with exponential backoff and jitter

```python
import random
import time

for attempt in range(1, attempts + 1):
    try:
        return call()
    except ConnectionError:
        if attempt == attempts:
            raise
        delay = min(cap, base * 2 ** (attempt - 1))
        time.sleep(delay * random.uniform(0.5, 1.0))
```

### A retry decorator with arguments

```python
import functools


def retry(attempts=3, exceptions=(Exception,)):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(1, attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions:
                    if attempt == attempts:
                        raise
        return wrapper
    return decorator
```

### Session with automatic retries on 5xx (urllib3 Retry)

```python
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

session = requests.Session()
retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
session.mount("https://", HTTPAdapter(max_retries=retries))
```

## Concurrency

### Check many URLs in parallel with a thread pool, handling each failure separately

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

results = {}
with ThreadPoolExecutor(max_workers=10) as pool:
    futures = {pool.submit(check, url): url for url in urls}
    for future in as_completed(futures):
        url = futures[future]
        try:
            results[url] = future.result()
        except Exception as e:
            results[url] = {"ok": False, "error": str(e)}
```

### Protect a shared counter across threads

```python
import threading

lock = threading.Lock()
with lock:
    counts[name] += 1
```

## Generators and context managers

### Generator that yields batches of n from any iterable

```python
from itertools import islice


def batched(iterable, n):
    it = iter(iterable)
    while batch := list(islice(it, n)):
        yield batch
```

### Context manager that logs how long a block took

```python
import contextlib


@contextlib.contextmanager
def timed(name):
    start = time.perf_counter()
    try:
        yield
    finally:
        log.info("%s took %.3fs", name, time.perf_counter() - start)
```

## AWS

### Iterate every EC2 instance with a paginator (never assume one page)

```python
import boto3

ec2 = boto3.client("ec2", region_name="eu-west-1")
for page in ec2.get_paginator("describe_instances").paginate():
    for reservation in page["Reservations"]:
        for instance in reservation["Instances"]:
            tags = {t["Key"]: t["Value"] for t in instance.get("Tags", [])}
            print(instance["InstanceId"], instance["State"]["Name"], tags.get("Name"))
```

### Catch a specific AWS error code

```python
from botocore.exceptions import ClientError

try:
    s3.get_bucket_encryption(Bucket=name)
except ClientError as e:
    if e.response["Error"]["Code"] != "ServerSideEncryptionConfigurationNotFoundError":
        raise
    print(f"{name}: no default encryption")
```

## Testing

### pytest: parametrize a pure function

```python
import pytest


@pytest.mark.parametrize("used, expected", [(50, 0), (85, 1), (95, 2)])
def test_evaluate(used, expected):
    assert evaluate(used, warn=80, crit=90)[0] == expected
```

### pytest: temp files and replacing a function for one test

```python
from types import SimpleNamespace


def test_disk_check(tmp_path, monkeypatch):
    (tmp_path / "a.log").write_text("x")
    fake = SimpleNamespace(total=100, used=95, free=5)
    monkeypatch.setattr(shutil, "disk_usage", lambda path: fake)
    assert main([str(tmp_path)]) == 2
```
