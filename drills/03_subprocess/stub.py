"""Run external commands safely, and find full filesystems from df output.

Spec: drills/03_subprocess/README.md
"""

import re
import subprocess
import time
from dataclasses import dataclass


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    duration: float
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        raise NotImplementedError


def run_command(cmd: list[str], timeout: float) -> CommandResult:
    raise NotImplementedError


def parse_df(output: str) -> list[dict]:
    raise NotImplementedError


def filesystems_over(df_output: str, threshold_percent: int) -> list[dict]:
    raise NotImplementedError
