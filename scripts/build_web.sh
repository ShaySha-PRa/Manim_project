#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
web_root="$repo_root/apps/web"

prepare_standalone_assets() {
  local build_root="$1"
  local standalone_root="$build_root/.next/standalone/apps/web"

  mkdir -p "$standalone_root/.next/static"
  rsync -a --delete "$build_root/.next/static/" "$standalone_root/.next/static/"
  if [[ -d "$build_root/public" ]]; then
    mkdir -p "$standalone_root/public"
    rsync -a --delete "$build_root/public/" "$standalone_root/public/"
  fi
}

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
    prepare_standalone_assets "$staging_root/apps/web"
    ;;
  *)
    cd "$web_root"
    next build
    prepare_standalone_assets "$web_root"
    ;;
esac
