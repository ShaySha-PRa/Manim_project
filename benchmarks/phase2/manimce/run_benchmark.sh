#!/usr/bin/env bash
set -euo pipefail

# The default is deliberately sudo -n docker: normal socket access is unavailable.
exec python3 "$(dirname "$0")/run_benchmark.py"
