"""Decides WHICH file the drill tests run against.

Every drill has two test files:
    test_solution.py  -> uses the `solution` fixture
    test_variant.py   -> uses the `variant` fixture

DRILL_MODE picks the source of that module:
    attempt   (default) attempts/<drill>/solution.py or variant.py   <- your rep
    reference            drills/<drill>/reference.py or variant_reference.py
    stub                 drills/<drill>/stub.py or variant_stub.py   (must FAIL every test)
"""

import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).parent

FILES = {
    "attempt": {"solution": "solution.py", "variant": "variant.py"},
    "reference": {"solution": "reference.py", "variant": "variant_reference.py"},
    "stub": {"solution": "stub.py", "variant": "variant_stub.py"},
}


def _load(drill_dir: Path, kind: str):
    mode = os.environ.get("DRILL_MODE", "attempt")
    filename = FILES[mode][kind]
    if mode == "attempt":
        path = ROOT / "attempts" / drill_dir.name / filename
    else:
        path = drill_dir / filename
    if not path.exists():
        pytest.fail(f"No file to test: {path}\nRun: drill start {drill_dir.name[:2]}", pytrace=False)

    module_name = f"drill_{drill_dir.name}_{kind}_{mode}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def solution(request):
    return _load(request.path.parent, "solution")


@pytest.fixture(scope="module")
def variant(request):
    return _load(request.path.parent, "variant")
