#!/bin/bash
# Download AILANG WASM runtime from latest release.
# Run from docs/ directory: bash wasm/download.sh
# The .wasm file is .gitignored — this fetches it for local dev.

set -euo pipefail
WASM_DIR="$(dirname "$0")"
cd "$WASM_DIR"

echo "Fetching latest AILANG release..."
RELEASE_TAG=$(curl -sfL \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/sunholo-data/ailang/releases/latest | \
  python3 -c "import json,sys; print(json.loads(sys.stdin.read())['tag_name'])")

echo "Downloading ailang-wasm.tar.gz ($RELEASE_TAG)..."
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
