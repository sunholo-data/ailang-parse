#!/usr/bin/env bash
# audit.sh — Check design_docs/ folder structure against current version
# Usage: bash .claude/skills/audit-design-docs/scripts/audit.sh
set -euo pipefail

DESIGN_DIR="design_docs"
VERSION_FILE="ailang.toml"

# --- Step 1: Get current version ---
if [[ ! -f "$VERSION_FILE" ]]; then
  echo "ERROR: $VERSION_FILE not found" >&2
  exit 1
fi

CURRENT_VERSION=$(grep '^version' "$VERSION_FILE" | head -1 | sed 's/version *= *"\(.*\)"/\1/')
echo "=== AILANG Parse Design Doc Audit ==="
echo "Current version: v${CURRENT_VERSION}"
echo ""

# Parse version into comparable integer (0.8.2 → 8002)
version_to_int() {
  local v="$1"
  v="${v#v}"
  local major minor patch
  IFS='.' read -r major minor patch <<< "$v"
  echo $(( (${major:-0} * 1000000) + (${minor:-0} * 1000) + (${patch:-0}) ))
}

CURRENT_INT=$(version_to_int "$CURRENT_VERSION")
FINDINGS=0

finding() {
  local severity="$1" category="$2" file="$3" message="$4"
  echo "[$severity] $category: $file"
  echo "  → $message"
  echo ""
  FINDINGS=$((FINDINGS + 1))
}

# --- Step 2: Check implemented/ docs ---
echo "--- Checking implemented/ ---"
for f in $(find "$DESIGN_DIR/implemented" -name "*.md" -type f 2>/dev/null); do
  dir_version=$(echo "$f" | grep -oE 'v[0-9]+_[0-9]+_[0-9]+' | head -1 || true)

  if [[ -z "$dir_version" ]]; then
    finding "MEDIUM" "LOOSE_FILE" "$f" "Not in a version subfolder under implemented/"
    continue
  fi

  sem_version=$(echo "$dir_version" | sed 's/^v//' | tr '_' '.')
  doc_int=$(version_to_int "$sem_version")

  # Implemented version > current = impossible (hasn't shipped)
  if [[ "$doc_int" -gt "$CURRENT_INT" ]]; then
    finding "HIGH" "VERSION_MISMATCH" "$f" "In implemented/v${sem_version}/ but current is v${CURRENT_VERSION} — this version hasn't shipped yet"
  fi

  # Check Status: header — should not say planned/TODO at start of line
  status_line=$(grep -i '^[*]*Status[*]*:' "$f" | head -1 || true)
  if [[ -n "$status_line" ]]; then
    status_lower=$(echo "$status_line" | tr '[:upper:]' '[:lower:]')
    if echo "$status_lower" | grep -qE '^\*\*status\*\*: *(planned|todo|not.*(started|implemented))'; then
      finding "HIGH" "STATUS_CONTRADICTION" "$f" "Status says planned/TODO but file is in implemented/ — Status: $status_line"
    fi
  fi
done

# --- Step 3: Check planned/ docs ---
echo "--- Checking planned/ ---"
for f in $(find "$DESIGN_DIR/planned" -name "*.md" -type f 2>/dev/null); do
  # Skip known unversioned Go binary doc
  if [[ "$f" == *"go_binary"* ]]; then
    continue
  fi

  dir_version=$(echo "$f" | grep -oE 'v[0-9]+_[0-9]+_[0-9]+' | head -1 || true)

  if [[ -z "$dir_version" ]]; then
    finding "MEDIUM" "LOOSE_FILE" "$f" "Not in a version subfolder under planned/"
    continue
  fi

  sem_version=$(echo "$dir_version" | sed 's/^v//' | tr '_' '.')
  doc_int=$(version_to_int "$sem_version")

  # Planned version <= current = stale
  if [[ "$doc_int" -le "$CURRENT_INT" ]]; then
    finding "MEDIUM" "STALE_PLANNED" "$f" "Planned for v${sem_version} but current is v${CURRENT_VERSION} — should this be in implemented/ or re-versioned?"
  fi

  # Check Status: header — should not say done/completed
  status_line=$(grep -i '^[*]*Status[*]*:' "$f" | head -1 || true)
  if [[ -n "$status_line" ]]; then
    status_lower=$(echo "$status_line" | tr '[:upper:]' '[:lower:]')
    if echo "$status_lower" | grep -qE '^\*\*status\*\*: *(done|completed|implemented|shipped|accepted)'; then
      finding "HIGH" "STATUS_CONTRADICTION" "$f" "Status says done/completed but file is in planned/ — Status: $status_line"
    fi
  fi
done

# --- Step 4: Check archive/ ---
echo "--- Checking archive/ ---"
for f in $(find "$DESIGN_DIR/archive" -name "*.md" -type f 2>/dev/null); do
  status_line=$(grep -i '^[*]*Status[*]*:' "$f" | head -1 || true)
  if [[ -n "$status_line" ]]; then
    status_lower=$(echo "$status_line" | tr '[:upper:]' '[:lower:]')
    if echo "$status_lower" | grep -qE '^\*\*status\*\*: *(active|in.progress)'; then
      finding "HIGH" "STATUS_CONTRADICTION" "$f" "Status says active/in-progress but file is in archive/ — Status: $status_line"
    fi
  fi
done

# --- Summary ---
echo "=== Summary ==="
echo "Files checked: $(find "$DESIGN_DIR" -name "*.md" -type f | wc -l | tr -d ' ')"
echo "Findings: $FINDINGS"

if [[ "$FINDINGS" -eq 0 ]]; then
  echo "All design docs are correctly organized."
else
  echo ""
  echo "Run the audit-design-docs skill to review and fix the findings above."
fi

exit 0
