# 01 · Variant: brute-force SSH detection from auth.log

Same patterns as the main drill (compiled regex, Counter, streaming), different log. Do this
once the main drill passes from memory. It proves you learned the *pattern*, not the text.

## The task

> Security asked which IPs are brute-forcing SSH on our bastion. Read auth.log, count failed
> password attempts per source IP, and give me a block list: IPs with at least `threshold`
> failures. Never block an IP that has also logged in successfully. That's probably us.

```
Sep 17 10:15:32 bastion sshd[1234]: Failed password for invalid user admin from 203.0.113.5 port 52211 ssh2
Sep 17 10:15:40 bastion sshd[1234]: Failed password for root from 203.0.113.5 port 52212 ssh2
Sep 17 10:16:01 bastion sshd[1250]: Accepted publickey for deploy from 10.0.0.4 port 50000 ssh2
Sep 17 10:16:09 bastion CRON[1300]: pam_unix(cron:session): session opened for user root
```

## Contract

```python
def parse_event(line: str) -> dict | None
    # Failed:   {"result": "failed",   "user": "admin", "ip": "203.0.113.5", "invalid_user": True}
    # Accepted: {"result": "accepted", "user": "deploy", "ip": "10.0.0.4", "invalid_user": False}
    # Anything else (CRON, other sshd noise) -> None

def failures_by_ip(lines: Iterable[str]) -> dict[str, int]

def ips_to_block(lines: Iterable[str], threshold: int = 5) -> list[str]
    # failures >= threshold, excluding any IP with an accepted login in the same input.
    # Order: most failures first, ties broken by IP string ascending.
```

`Accepted` lines can be `publickey` or `password`. Handle both.

Note: `lines` may be a one-shot generator, so `ips_to_block` must go through it only **once**.

## Say this out loud

- "One pass: I keep a failure Counter and an accepted set together, because the input might be a stream."
- "Sort key `(-count, ip)` gives count descending with a stable tiebreak, so the output is deterministic
  and safe to diff or feed to automation."
- "I wouldn't auto-apply this list. I'd feed it to fail2ban or a WAF with an expiry, because a NAT'd office IP would lock everyone out."
