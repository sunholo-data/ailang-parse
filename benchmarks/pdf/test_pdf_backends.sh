#!/usr/bin/env bash
# Integration tests for --pdf-backend flag.
# Runs each backend on simple_text.pdf and asserts the produced JSON has the
# four expected headings.

set -u
cd "$(dirname "$0")/../.."

PDF=data/test_files/simple_text.pdf
OUT_JSON=docparse/data/simple_text.pdf.json
EXPECTED_HEADINGS=("Document Analysis Report" "Introduction" "Key Findings" "Conclusion")

PASS=0
FAIL=0

assert_headings_present() {
  local backend=$1
  if [ ! -f "$OUT_JSON" ]; then
    echo "  [$backend] FAIL: $OUT_JSON not produced"
    FAIL=$((FAIL+1)); return
  fi
  local missing=0
  for h in "${EXPECTED_HEADINGS[@]}"; do
    if ! grep -qF "\"text\":\"$h\"" "$OUT_JSON"; then
      echo "  [$backend] missing heading: $h"
      missing=$((missing+1))
    fi
  done
  if [ "$missing" -eq 0 ]; then
    echo "  [$backend] PASS"
    PASS=$((PASS+1))
  else
    echo "  [$backend] FAIL: $missing/${#EXPECTED_HEADINGS[@]} headings missing"
    FAIL=$((FAIL+1))
  fi
}

run_backend_test() {
  local backend=$1
  echo "--- backend: $backend ---"
  rm -f "$OUT_JSON"
  if ./bin/docparse "$PDF" --pdf-backend "$backend" > /tmp/docparse-$backend.log 2>&1; then
    assert_headings_present "$backend"
  else
    echo "  [$backend] FAIL: CLI exit non-zero. Last 20 lines of log:"
    tail -20 /tmp/docparse-$backend.log | sed 's/^/    /'
    FAIL=$((FAIL+1))
  fi
}

echo "=== PDF backend integration tests ==="
run_backend_test docling
run_backend_test liteparse
run_backend_test ai

echo
echo "=== Summary: $PASS passed, $FAIL failed ==="
exit $FAIL
