from __future__ import annotations

import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class CommandResult:
    command: tuple[str, ...]
    returncode: int
    output: str
    duration_seconds: float


class CommandRunner(Protocol):
    def run(self, command: Sequence[str], *, timeout_seconds: int) -> CommandResult: ...


class CommandTimedOut(Exception):
    def __init__(self, command: Sequence[str], output: str) -> None:
        super().__init__("command timed out")
        self.command = tuple(command)
        self.output = output


class SubprocessCommandRunner:
    def run(self, command: Sequence[str], *, timeout_seconds: int) -> CommandResult:
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                list(command),
                cwd=Path.cwd(),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            output = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            raise CommandTimedOut(command, output) from exc
        return CommandResult(
            command=tuple(command),
            returncode=completed.returncode,
            output=completed.stdout,
            duration_seconds=time.perf_counter() - started,
        )
