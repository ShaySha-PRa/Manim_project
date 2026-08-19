"""Frozen compute entrypoint. Docker mounts this file; user code never reaches it."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, "/input")
from kernels import run_kernel, write_npz  # type: ignore  # noqa: E402


def main() -> None:
    op = sys.argv[1]
    params = json.loads(Path("/input/params.json").read_text(encoding="utf-8"))
    input_text = Path("/input/input.txt").read_text(encoding="utf-8")
    result = run_kernel(op, params, input_text or None)
    write_npz(Path("/output/result.npz"), result)


if __name__ == "__main__":
    main()
