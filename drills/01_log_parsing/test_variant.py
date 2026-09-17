def fail(ip, user="root", invalid=False, port=50000):
    who = f"invalid user {user}" if invalid else user
    return f"Sep 17 10:15:32 bastion sshd[1234]: Failed password for {who} from {ip} port {port} ssh2"


def accept(ip, user="deploy", method="publickey"):
    return f"Sep 17 10:16:01 bastion sshd[1250]: Accepted {method} for {user} from {ip} port 50000 ssh2"


NOISE = "Sep 17 10:16:09 bastion CRON[1300]: pam_unix(cron:session): session opened for user root"


def test_parse_failed_invalid_user(variant):
    e = variant.parse_event(fail("203.0.113.5", "admin", invalid=True))
    assert e == {"result": "failed", "user": "admin", "ip": "203.0.113.5", "invalid_user": True}


def test_parse_failed_valid_user(variant):
    e = variant.parse_event(fail("203.0.113.5", "root"))
    assert e == {"result": "failed", "user": "root", "ip": "203.0.113.5", "invalid_user": False}


def test_parse_accepted_both_methods(variant):
    assert variant.parse_event(accept("10.0.0.4"))["result"] == "accepted"
    assert variant.parse_event(accept("10.0.0.4", method="password"))["user"] == "deploy"


def test_parse_noise_is_none(variant):
    assert variant.parse_event(NOISE) is None
    assert variant.parse_event("") is None


def test_failures_by_ip(variant):
    lines = [fail("1.1.1.1"), fail("1.1.1.1"), fail("2.2.2.2"), accept("3.3.3.3"), NOISE]
    assert variant.failures_by_ip(lines) == {"1.1.1.1": 2, "2.2.2.2": 1}


def test_ips_to_block_threshold_order_and_tiebreak(variant):
    lines = [fail("9.9.9.9")] * 3 + [fail("5.5.5.5")] * 3 + [fail("7.7.7.7")] * 6 + [fail("8.8.8.8")] * 2
    assert variant.ips_to_block(lines, threshold=3) == ["7.7.7.7", "5.5.5.5", "9.9.9.9"]


def test_ips_to_block_excludes_successful_logins(variant):
    lines = [fail("10.0.0.4")] * 10 + [accept("10.0.0.4")] + [fail("6.6.6.6")] * 5
    assert variant.ips_to_block(lines, threshold=5) == ["6.6.6.6"]


def test_ips_to_block_single_pass_over_generator(variant):
    lines = [fail("6.6.6.6")] * 5 + [accept("10.0.0.4")]
    assert variant.ips_to_block(iter(lines), threshold=5) == ["6.6.6.6"]
