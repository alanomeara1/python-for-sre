"""Check many HTTP endpoints concurrently with a thread pool.

Spec: drills/05_concurrency/README.md
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


def check_endpoint(url: str, timeout: float) -> dict:
    raise NotImplementedError


def check_endpoints(urls: list[str], max_workers: int = 10, timeout: float = 2.0) -> dict[str, dict]:
    raise NotImplementedError
