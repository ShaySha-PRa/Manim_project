from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "apps" / "web"
TARGET = ROOT / "runtime" / "phase8-browser-web"

if TARGET.exists():
    shutil.rmtree(TARGET)
shutil.copytree(
    SOURCE,
    TARGET,
    ignore=shutil.ignore_patterns(".next", "node_modules"),
)
