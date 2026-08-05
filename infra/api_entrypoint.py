#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
from pathlib import Path

SERVICE_UID = 10001
SERVICE_GID = 10001
DATA_DIRECTORY = Path("/data")


def main() -> None:
    if os.geteuid() == 0:
        os.chown(DATA_DIRECTORY, SERVICE_UID, SERVICE_GID)
        os.setgroups([])
        os.setgid(SERVICE_GID)
        os.setuid(SERVICE_UID)
    if os.geteuid() != SERVICE_UID or os.getegid() != SERVICE_GID:
        raise RuntimeError("API entrypoint did not reach the service identity")
    subprocess.run(["alembic", "upgrade", "head"], check=True)
    os.execvp(
        "uvicorn",
        [
            "uvicorn",
            "manim_workbench_api.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
        ],
    )


if __name__ == "__main__":
    main()
