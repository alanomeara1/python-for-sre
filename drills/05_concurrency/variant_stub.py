"""Check TCP reachability of many host:port pairs concurrently.

Spec: drills/05_concurrency/variant.md
"""

import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed


def check_port(host: str, port: int, timeout: float) -> dict:
    raise NotImplementedError


def check_ports(targets: list[tuple[str, int]], timeout: float = 1.0,
                max_workers: int = 20) -> dict[tuple[str, int], dict]:
    raise NotImplementedError


def summarize(results: dict[tuple[str, int], dict]) -> dict[str, list[tuple[str, int]]]:
    raise NotImplementedError
