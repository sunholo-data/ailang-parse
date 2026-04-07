#!/usr/bin/env bash
# Serve docs/ over HTTP for local development.
#
# Why: WASM (and most fetch() calls) won't work when opening HTML via file://
# because browsers block cross-origin requests on the local filesystem. The
# workbench and homepage demo both need an HTTP origin to load ailang.wasm.
#
# Usage:
#   bash docs/serve.sh            # default port 8765
#   bash docs/serve.sh 9000       # custom port

set -euo pipefail

PORT="${1:-8765}"
DOCS_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Serving $DOCS_DIR on http://localhost:$PORT"
echo ""
echo "  Workbench: http://localhost:$PORT/workbench.html"
echo "  Homepage:  http://localhost:$PORT/"
echo "  Playground: http://localhost:$PORT/playground.html"
echo ""
echo "Press Ctrl+C to stop."
echo ""

cd "$DOCS_DIR"
exec python3 -m http.server "$PORT"
