#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
web_root="$repo_root/apps/web"

case "$repo_root" in
  /mnt/*)
    staging_root="$(mktemp -d /tmp/manim-workbench-web-build.XXXXXX)"
    trap 'rm -rf "$staging_root"' EXIT

    mkdir -p "$staging_root/apps/web" "$staging_root/packages"
    rsync -a --exclude node_modules --exclude .next "$web_root/" "$staging_root/apps/web/"
    rsync -a "$repo_root/packages/contracts/" "$staging_root/packages/contracts/"
    ln -s "$repo_root/node_modules" "$staging_root/node_modules"
    ln -s "$web_root/node_modules" "$staging_root/apps/web/node_modules"

    cd "$staging_root/apps/web"
    "$repo_root/node_modules/.bin/next" build
    ;;
  *)
    cd "$web_root"
    next build
    ;;
esac
