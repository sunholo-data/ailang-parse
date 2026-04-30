#!/bin/bash
# Download AILANG WASM runtime at the version pinned in .ailang-version.
# Run from docs/ directory: bash wasm/download.sh
# The .wasm file is .gitignored — this fetches it for local dev.

set -euo pipefail
WASM_DIR="$(dirname "$0")"
cd "$WASM_DIR"

if [ ! -f .ailang-version ]; then
  echo "ERROR: docs/wasm/.ailang-version not found — pin file is the single source of truth"
  exit 1
fi
RELEASE_TAG=$(head -n1 .ailang-version | tr -d '[:space:]')
if [ -z "$RELEASE_TAG" ]; then
  echo "ERROR: docs/wasm/.ailang-version is empty"
  exit 1
fi

echo "Downloading ailang-wasm.tar.gz ($RELEASE_TAG, pinned)..."
curl -sfL --retry 3 \
  -o ailang-wasm.tar.gz \
  "https://github.com/sunholo-data/ailang/releases/download/${RELEASE_TAG}/ailang-wasm.tar.gz"

echo "Extracting..."
tar -xzf ailang-wasm.tar.gz

# Move ailang.wasm to this directory
if [ -f ailang.wasm ]; then
  echo "ailang.wasm: $(ls -lh ailang.wasm | awk '{print $5}')"
else
  echo "ERROR: ailang.wasm not found in tarball"
  exit 1
fi

rm -f ailang-wasm.tar.gz
echo "Done. WASM runtime ready."
