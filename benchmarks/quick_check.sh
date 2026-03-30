#!/bin/bash
# Quick smoke test: type-check + 5 representative files (one per format family)
# Run this during development. Use full benchmark (run_benchmarks.py) for releases.
#
# Usage: bash benchmarks/quick_check.sh              # deterministic only
#        bash benchmarks/quick_check.sh gemini-2.5-flash  # + audio/video AI tests

set -e
cd "$(dirname "$0")/.."

echo "=== Quick Check ==="
echo ""

# 1. Type-check all modules
echo "--- Type-checking ---"
ailang check docparse/ 2>&1 | tail -1
echo ""

# 2. Parse 5 representative files (one per format family)
QUICK_FILES=(
  "data/test_files/sample.docx"         # OOXML (DOCX)
  "data/test_files/test.odt"            # ODF
  "data/test_files/test.md"             # Markdown
  "data/test_files/test.html"           # HTML
  "data/test_files/test.csv"            # CSV
)

TMPDIR_BASE=$(mktemp -d /tmp/docparse_quick_XXXXXX)
echo "--- Smoke tests (5 files) ---"
PASS=0
FAIL=0
for f in "${QUICK_FILES[@]}"; do
  fname=$(basename "$f")
  OUTDIR="${TMPDIR_BASE}/${fname}"
  mkdir -p "$OUTDIR"
  START=$(python3 -c 'import time; print(int(time.time()*1000))')
  if DOCPARSE_OUTPUT_DIR="$OUTDIR" ailang run --entry main --caps IO,FS,Env docparse/main.ail "$f" > /dev/null 2>&1; then
    END=$(python3 -c 'import time; print(int(time.time()*1000))')
    ELAPSED=$((END - START))
    echo "  PASS  ${fname}  (${ELAPSED}ms)"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  ${fname}"
    FAIL=$((FAIL + 1))
  fi
done

echo ""

# 3. Quick conversion test (DOCX → HTML roundtrip)
echo "--- Conversion test ---"
TMPHTML=$(mktemp /tmp/docparse_quick_XXXXXX.html)
TMPOUT=$(mktemp -d /tmp/docparse_quick_XXXXXX)
if DOCPARSE_OUTPUT_DIR="$TMPOUT" ailang run --entry main --caps IO,FS,Env docparse/main.ail data/test_files/sample.docx --convert "$TMPHTML" > /dev/null 2>&1; then
  # Re-parse the HTML
  if DOCPARSE_OUTPUT_DIR="$TMPOUT" ailang run --entry main --caps IO,FS,Env docparse/main.ail "$TMPHTML" > /dev/null 2>&1; then
    echo "  PASS  DOCX → HTML → re-parse"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  HTML re-parse"
    FAIL=$((FAIL + 1))
  fi
else
  echo "  FAIL  DOCX → HTML conversion"
  FAIL=$((FAIL + 1))
fi
rm -rf "$TMPHTML" "$TMPOUT" "$TMPDIR_BASE"

# 4. AI media tests (optional — only run if --ai flag passed)
AI_MODEL="${1:-}"
if [ -n "$AI_MODEL" ]; then
  echo ""
  echo "--- AI media tests (${AI_MODEL}) ---"
  AI_FILES=(
    "data/test_files/sample.mp3"           # Audio
    "data/test_files/sample_speech.mp4"     # Video (with speech)
  )
  for f in "${AI_FILES[@]}"; do
    fname=$(basename "$f")
    OUTDIR="${TMPDIR_BASE}_ai/${fname}"
    mkdir -p "$OUTDIR"
    START=$(python3 -c 'import time; print(int(time.time()*1000))')
    if DOCPARSE_OUTPUT_DIR="$OUTDIR" ailang run --entry main --caps IO,FS,Env,AI --ai "$AI_MODEL" docparse/main.ail "$f" > /dev/null 2>&1; then
      END=$(python3 -c 'import time; print(int(time.time()*1000))')
      ELAPSED=$((END - START))
      echo "  PASS  ${fname}  (${ELAPSED}ms)"
      PASS=$((PASS + 1))
    else
      echo "  FAIL  ${fname}"
      FAIL=$((FAIL + 1))
    fi
  done
  rm -rf "${TMPDIR_BASE}_ai"
else
  echo ""
  echo "(Skipping AI media tests — pass model name to enable: bash benchmarks/quick_check.sh gemini-2.5-flash)"
fi

echo ""
echo "=== Results: ${PASS} passed, ${FAIL} failed ==="

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
