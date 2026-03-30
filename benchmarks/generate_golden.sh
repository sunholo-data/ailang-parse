#!/usr/bin/env bash
set -uo pipefail

# Generate golden expected outputs for the Office structural benchmark.
# Uses AILANG batch mode: compile once, run all inputs (~5-15x faster than sequential).

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
GOLDEN_DIR="$SCRIPT_DIR/office/golden"
TEST_DIR="$REPO_DIR/data/test_files"
OUTPUT_DIR="$REPO_DIR/docparse/data"

TIMEOUT=${TIMEOUT:-300}  # Timeout for entire batch run in seconds

# Stress test files excluded from day-to-day golden generation.
# These are large or slow files meant for dedicated performance testing.
EXCLUDE="poi_many_merges.xlsx"

mkdir -p "$GOLDEN_DIR"

cd "$REPO_DIR"

# Collect all test files, excluding stress tests
FILES=()
for f in "$TEST_DIR"/*.docx "$TEST_DIR"/*.pptx "$TEST_DIR"/*.xlsx \
         "$TEST_DIR"/*.odt "$TEST_DIR"/*.odp "$TEST_DIR"/*.ods \
         "$TEST_DIR"/*.epub "$TEST_DIR"/*.html "$TEST_DIR"/*.csv "$TEST_DIR"/*.tsv "$TEST_DIR"/*.md \
         "$TEST_DIR"/challenge/*.eml "$TEST_DIR"/challenge/*.mbox; do
  [ -f "$f" ] || continue
  fname="$(basename "$f")"
  # Skip excluded stress test files
  case "$EXCLUDE" in
    *"$fname"*) echo "  $fname ... SKIP (stress test)"; continue ;;
  esac
  FILES+=("$f")
done

TOTAL=${#FILES[@]}
echo "=== Generating golden outputs for $TOTAL files (batch mode) ==="
echo ""

# Create a timestamp marker so we can detect which outputs were freshly written
MARKER=$(mktemp)
sleep 1  # ensure marker is older than any output about to be written

# Run batch mode with portable timeout (background + watchdog)
START=$(date +%s)

ailang run --entry main --caps IO,FS,Env \
    --max-recursion-depth 50000 --batch \
    docparse/main.ail "${FILES[@]}" > /dev/null 2>&1 &
BATCH_PID=$!

# Watchdog: kill batch if it exceeds timeout
(sleep "$TIMEOUT" && kill "$BATCH_PID" 2>/dev/null) &
WATCHDOG_PID=$!

# Wait for batch to finish (ignore non-zero exit from partial failures)
wait "$BATCH_PID" 2>/dev/null
BATCH_RC=$?

# Clean up watchdog
kill "$WATCHDOG_PID" 2>/dev/null || true
wait "$WATCHDOG_PID" 2>/dev/null || true

END=$(date +%s)
ELAPSED=$((END - START))

if [ "$BATCH_RC" -ne 0 ]; then
  echo "  (batch exited with code $BATCH_RC — some files may have failed)"
  echo ""
fi

# Copy outputs and track results
PASS=0
FAIL=0
FAIL_LIST=()

for f in "${FILES[@]}"; do
  fname="$(basename "$f")"
  output_json="$OUTPUT_DIR/${fname}.json"

  if [ -f "$output_json" ] && [ "$output_json" -nt "$MARKER" ]; then
    cp "$output_json" "$GOLDEN_DIR/${fname}.json"
    echo "  $fname ... OK"
    PASS=$((PASS + 1))
  else
    echo "  $fname ... FAIL"
    FAIL=$((FAIL + 1))
    FAIL_LIST+=("$fname")
  fi
done

rm -f "$MARKER"

echo ""
echo "Generated $PASS golden outputs ($FAIL failures) in ${ELAPSED}s (batch mode)"
echo "Output: $GOLDEN_DIR/"

if [ ${#FAIL_LIST[@]} -gt 0 ]; then
  echo ""
  echo "Failed files:"
  for f in "${FAIL_LIST[@]}"; do
    echo "  - $f"
  done
fi
