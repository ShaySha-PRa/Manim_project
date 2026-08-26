"""Run the protected offline RenderJob typed-source revision boundary."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from manim_workbench_api.database_migrations.protected_render_job_migration import (
    run_protected_migration,
)

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Offline-only RenderJob typed-source migration. Stop API and Runner before use."
        )
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--mode", choices=("upgrade", "downgrade"), required=True)
    parser.add_argument(
        "--confirm-services-stopped",
        action="store_true",
        help="Confirm that API and Runner writes have been stopped.",
    )
    parser.add_argument(
        "--alembic-config",
        type=Path,
        default=ROOT / "alembic.ini",
    )
    arguments = parser.parse_args()
    evidence = run_protected_migration(
        database_path=arguments.database,
        backup_path=arguments.backup,
        alembic_config_path=arguments.alembic_config,
        mode=arguments.mode,
        services_stopped=arguments.confirm_services_stopped,
    )
    print(json.dumps(asdict(evidence), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
