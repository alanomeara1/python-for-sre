"""Run the drill 01 reference on realistic input and print what it produces.

Output must be byte-identical every run, so `drill sample --check` can catch drift:
no wall-clock times, no randomness, no temp paths in the output.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import reference
import variant_reference

ACCESS_LOG = """\
10.0.0.1 - - [17/Sep/2026:10:15:32 +0000] "GET /api/users HTTP/1.1" 200 512 0.023
10.0.0.2 - - [17/Sep/2026:10:15:33 +0000] "POST /api/login HTTP/1.1" 503 - 1.204
10.0.0.1 - - [17/Sep/2026:10:15:34 +0000] "GET /healthz HTTP/1.1" 200 2 0.001
<<< truncated by logrotate >>>
10.0.0.3 - - [17/Sep/2026:10:15:35 +0000] "GET /api/orders HTTP/1.1" 404 128 0.010
10.0.0.1 - - [17/Sep/2026:10:15:36 +0000] "GET /api/users HTTP/1.1" 500 64 0.502
10.0.0.2 - - [17/Sep/2026:10:15:37 +0000] "GET /api/users HTTP/1.1" 200 512 0.030
"""

AUTH_LOG = """\
Sep 17 10:15:32 bastion sshd[1234]: Failed password for invalid user admin from 203.0.113.5 port 52211 ssh2
Sep 17 10:15:40 bastion sshd[1234]: Failed password for root from 203.0.113.5 port 52212 ssh2
Sep 17 10:15:44 bastion sshd[1235]: Failed password for root from 203.0.113.5 port 52213 ssh2
Sep 17 10:15:51 bastion sshd[1236]: Failed password for invalid user oracle from 198.51.100.9 port 40112 ssh2
Sep 17 10:15:55 bastion sshd[1237]: Failed password for invalid user test from 198.51.100.9 port 40118 ssh2
Sep 17 10:16:01 bastion sshd[1250]: Accepted publickey for deploy from 10.0.0.4 port 50000 ssh2
Sep 17 10:16:09 bastion CRON[1300]: pam_unix(cron:session): session opened for user root
Sep 17 10:16:20 bastion sshd[1251]: Failed password for deploy from 10.0.0.4 port 50002 ssh2
"""

print("## The main problem: access log\n")
print("Input (note the corrupt line, and the `-` byte count on line 2):\n")
print("```text")
print(ACCESS_LOG.rstrip())
print("```\n")

print("One parsed line, `parse_line(...)`:\n")
print("```python")
record = reference.parse_line(ACCESS_LOG.splitlines()[0])
for key, value in record.items():
    print(f"{key:>10}: {value!r}")
print("```\n")

print("The whole file, `summarize_file(path, top_n=3)`:\n")
print("```json")
summary = reference.summarize(ACCESS_LOG.splitlines(), top_n=3)
print(json.dumps(summary, indent=2))
print("```\n")

print("Reading that: 6 requests parsed, 1 line unreadable, 2 of the 6 were 5xx, so a 33% error\n"
      "rate. 10.0.0.1 is the busiest client. The malformed line is counted, not fatal.\n")

print("## The variant: auth.log\n")
print("Input:\n")
print("```text")
print(AUTH_LOG.rstrip())
print("```\n")

print("`failures_by_ip(...)` and `ips_to_block(..., threshold=2)`:\n")
print("```python")
print(f"failures_by_ip(lines)            -> {variant_reference.failures_by_ip(AUTH_LOG.splitlines())}")
print(f"ips_to_block(lines, threshold=2) -> {variant_reference.ips_to_block(AUTH_LOG.splitlines(), threshold=2)}")
print("```\n")

print("Reading that: 10.0.0.4 failed once and also logged in successfully, so it's excluded from\n"
      "the block list even though it appears in the failure counts. 203.0.113.5 sorts first on 3\n"
      "failures, then 198.51.100.9 on 2.")
