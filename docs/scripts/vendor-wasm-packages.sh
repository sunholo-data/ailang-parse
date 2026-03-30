#!/usr/bin/env bash
# Vendor AILANG package sources for the WASM browser demo.
# Run after `ailang install` or `ailang lock` to update vendored files.
#
# WASM has no package resolution — modules must be loaded by name into
# an in-memory registry. This script copies package sources from the
# AILANG registry cache and syncs internal modules so the browser demo
# uses the same code paths as the server.
set -euo pipefail

CACHE="$HOME/.ailang/cache/registry"
ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
DEST="$ROOT/docs/ailang/pkg"

# sunholo/a2ui — vendored from package registry cache
mkdir -p "$DEST/sunholo/a2ui"
cp "$CACHE/sunholo/a2ui/0.1.0/components.ail" "$DEST/sunholo/a2ui/components.ail"

# a2ui_formatter — synced from source (includes JSON→Block decoder)
cp "$ROOT/docparse/services/a2ui_formatter.ail" "$ROOT/docs/ailang/docparse/services/a2ui_formatter.ail"

echo "Vendored WASM packages OK"
