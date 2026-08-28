#!/usr/bin/env bash
# Vendor AILANG WASM runtime, package sources, and parser modules for the
# in-browser demo and workbench.
#
# Mirrors the GitHub Actions deploy in .github/workflows/pages.yml so local
# and online builds use the same code paths. Run after upgrading AILANG
# (`ailang upgrade`) or whenever you want to refresh the browser bundle.
#
# Usage:
#   bash docs/scripts/vendor-wasm-packages.sh                # full refresh
#   bash docs/scripts/vendor-wasm-packages.sh --skip-wasm    # modules only
#   bash docs/scripts/vendor-wasm-packages.sh --check        # warn if stale, no changes
set -euo pipefail

ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
CACHE="$HOME/.ailang/cache/registry"
DEST="$ROOT/docs/ailang/pkg"
WASM_DIR="$ROOT/docs/wasm"
MODULES_DIR="$ROOT/docs/ailang/docparse"
PIN_FILE="$WASM_DIR/.ailang-version"
STALE_DAYS=7

SKIP_WASM=0
CHECK_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --skip-wasm) SKIP_WASM=1 ;;
    --check)     CHECK_ONLY=1 ;;
    -h|--help)
      sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
  esac
done

# ── Freshness check ──────────────────────────────────────────────────────
if [ -f "$WASM_DIR/ailang.wasm" ]; then
  # GNU stat (Linux) uses -c, BSD stat (macOS) uses -f. Try GNU first.
  WASM_MTIME=$(stat -c %Y "$WASM_DIR/ailang.wasm" 2>/dev/null || stat -f %m "$WASM_DIR/ailang.wasm")
  WASM_AGE_SECONDS=$(( $(date +%s) - WASM_MTIME ))
  WASM_AGE_DAYS=$(( WASM_AGE_SECONDS / 86400 ))
  if [ "$WASM_AGE_DAYS" -ge "$STALE_DAYS" ]; then
    echo "⚠️  Vendored ailang.wasm is ${WASM_AGE_DAYS} days old (>= ${STALE_DAYS}d threshold)"
    echo "    The deployed site auto-refreshes on each push; local copy does not."
    if [ "$CHECK_ONLY" -eq 1 ]; then
      echo "    Run: bash docs/scripts/vendor-wasm-packages.sh"
      exit 1
    fi
  else
    echo "✓ Vendored ailang.wasm is ${WASM_AGE_DAYS} days old"
  fi
elif [ "$CHECK_ONLY" -eq 1 ]; then
  echo "⚠️  No vendored ailang.wasm found at $WASM_DIR/ailang.wasm"
  echo "    Run: bash docs/scripts/vendor-wasm-packages.sh"
  exit 1
fi

if [ "$CHECK_ONLY" -eq 1 ]; then
  exit 0
fi

# ── 1. Download latest AILANG WASM runtime from GitHub releases ──────────
# Mirrors `.github/workflows/pages.yml` so local == deployed.
if [ "$SKIP_WASM" -eq 0 ]; then
  mkdir -p "$WASM_DIR"
  TMPDIR_WASM=$(mktemp -d)
  trap 'rm -rf "$TMPDIR_WASM"' EXIT

  if [ ! -f "$PIN_FILE" ]; then
    echo "✗ Missing $PIN_FILE — pin file is the single source of truth for the WASM version"
    exit 1
  fi
  RELEASE_TAG=$(head -n1 "$PIN_FILE" | tr -d '[:space:]')
  if [ -z "$RELEASE_TAG" ]; then
    echo "✗ $PIN_FILE is empty — write a release tag like 'v0.14.2' on line 1"
    exit 1
  fi
  echo "→ Pinned ailang release: $RELEASE_TAG (from $PIN_FILE)"

  echo "→ Downloading ailang-wasm.tar.gz..."
  curl -sfL --retry 3 --retry-delay 5 \
    -o "$TMPDIR_WASM/ailang-wasm.tar.gz" \
    "https://github.com/sunholo-data/ailang/releases/download/${RELEASE_TAG}/ailang-wasm.tar.gz"

  echo "→ Extracting to $WASM_DIR/"
  tar -xzf "$TMPDIR_WASM/ailang-wasm.tar.gz" -C "$TMPDIR_WASM"
  mv "$TMPDIR_WASM/ailang.wasm" "$WASM_DIR/"
  [ -f "$TMPDIR_WASM/wasm_exec.js" ]   && mv "$TMPDIR_WASM/wasm_exec.js"   "$WASM_DIR/"
  [ -f "$TMPDIR_WASM/ailang-repl.js" ] && mv "$TMPDIR_WASM/ailang-repl.js" "$WASM_DIR/"
  WASM_SIZE=$(stat -c %s "$WASM_DIR/ailang.wasm" 2>/dev/null || stat -f %z "$WASM_DIR/ailang.wasm")
  echo "  ailang.wasm: $((WASM_SIZE / 1024 / 1024)) MB"
fi

# ── 2. Copy latest parser modules from source ────────────────────────────
# This must mirror MODULES_TO_LOAD in docs/js/wasm-demo.js exactly. Every
# module loaded into the browser AILANG REPL must be vendored by name —
# the WASM bundle has no package resolution.
mkdir -p "$MODULES_DIR/types" "$MODULES_DIR/services"
MODULES=(
  "types/document.ail"
  "services/format_router.ail"
  "services/zip_extract.ail"
  "services/omml.ail"
  "services/docx_parser.ail"
  "services/pptx_parser.ail"
  "services/xlsx_parser.ail"
  "services/html_parser.ail"
  "services/csv_parser.ail"
  "services/markdown_parser.ail"
  "services/rtf_parser.ail"
  "services/eml_parser.ail"
  "services/tex_parser.ail"
  "services/xml_helpers.ail"
  "services/odf_text.ail"
  "services/odt_parser.ail"
  "services/odp_parser.ail"
  "services/ods_parser.ail"
  "services/epub_parser.ail"
  "services/markdown_writer.ail"
  "services/output_formatter.ail"
  "services/a2ui_formatter.ail"
  "services/docx_generator.ail"
  "services/docx_template.ail"
  "services/docparse_generate.ail"
  "services/docparse_browser.ail"
)
for m in "${MODULES[@]}"; do
  cp "$ROOT/docparse/$m" "$MODULES_DIR/$m"
done
echo "→ Copied ${#MODULES[@]} parser modules from source"

# Guard the invariant that just broke: every .ail under docs/ailang/docparse
# must be refreshed by this script, or it silently rots. The registry validator
# type-checks the WHOLE checkout, and a vendored copy nothing refreshes goes
# stale against the canonical tree — v0.33.0's publish failed on two of them.
# check-wasm-bindings.py enforces the other direction (vendored modules must
# actually be loaded by wasm-demo.js), so the two together pin the set exactly.
ORPHANS=$(cd "$MODULES_DIR" && find . -name '*.ail' | sed 's|^\./||' | sort > /tmp/vendored.$$ && \
  printf '%s\n' "${MODULES[@]}" | sort > /tmp/listed.$$ && \
  comm -23 /tmp/vendored.$$ /tmp/listed.$$; rm -f /tmp/vendored.$$ /tmp/listed.$$)
if [ -n "$ORPHANS" ]; then
  echo "✗ Vendored modules not in the MODULES list (they will go stale):"
  echo "$ORPHANS" | sed 's/^/    /'
  echo "  Add them above, or delete them from docs/ailang/docparse/."
  exit 1
fi

# ── 3. Vendor sunholo/a2ui from registry cache (if available) ────────────
# Resolve the version from ailang.lock (source of truth). Hardcoding the
# version here caused a silent WASM regression when the project bumped to
# 0.2.0 but the bundle kept shipping 0.1.0 (missing a2uiHeadingField etc.).
mkdir -p "$DEST/sunholo/a2ui"
A2UI_VERSION=$(python3 -c "
import json, sys
try:
    lock = json.load(open('$ROOT/ailang.lock'))
    for pkg in lock.get('packages', []):
        if pkg.get('name') == 'sunholo/a2ui':
            print(pkg['version']); sys.exit(0)
except Exception as e:
    print('', file=sys.stderr)
" 2>/dev/null)

if [ -z "$A2UI_VERSION" ]; then
  echo "✗ Could not resolve sunholo/a2ui version from ailang.lock — run 'ailang lock' first"
  exit 1
fi

if [ -f "$CACHE/sunholo/a2ui/$A2UI_VERSION/components.ail" ]; then
  cp "$CACHE/sunholo/a2ui/$A2UI_VERSION/components.ail" "$DEST/sunholo/a2ui/components.ail"
  echo "→ Refreshed sunholo/a2ui@$A2UI_VERSION from registry cache"
elif [ -f "$DEST/sunholo/a2ui/components.ail" ]; then
  echo "⚠ sunholo/a2ui@$A2UI_VERSION not in cache — keeping in-tree copy (may be stale)"
  echo "  Run 'ailang lock' to populate the registry cache, then re-vendor"
else
  echo "✗ sunholo/a2ui@$A2UI_VERSION not found in cache or vendor dir — run 'ailang lock' first"
  exit 1
fi

echo ""
echo "✓ Vendor complete — local browser bundle now matches deploy"
