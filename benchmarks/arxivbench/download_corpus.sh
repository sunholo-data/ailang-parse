#!/usr/bin/env bash
# Download arXiv papers into the corpus directory.
#
# Usage:
#   bash benchmarks/arxivbench/download_corpus.sh [arxiv_id:slug] ...
#   bash benchmarks/arxivbench/download_corpus.sh --from papers.txt
#
# papers.txt format (one per line, comments allowed):
#   1412.6980  kingma_adam
#   1502.03167 ioffe_batchnorm
#   # comment line ignored
#
# Fetches both the source tarball (https://arxiv.org/e-print/ID) and the
# rendered PDF (https://arxiv.org/pdf/ID), extracts the tarball into
# data/test_files/arxiv/<slug>/, and places the PDF alongside.
#
# arXiv's polite-crawler guidance asks for:
#   - a non-default User-Agent
#   - minimum 3 seconds between requests
# We honor both.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
CORPUS_DIR="$REPO_DIR/data/test_files/arxiv"
UA="ailang-parse-arxivbench/0.1 (https://github.com/sunholo/ailang-parse; contact: ailang)"
DELAY=3

mkdir -p "$CORPUS_DIR"

# --- Parse args ---
declare -a entries
if [[ "${1:-}" == "--from" ]]; then
    shift
    list_file="${1:?--from requires a path}"
    while IFS= read -r line; do
        # Strip comments + blank lines
        line="${line%%#*}"
        line="$(echo "$line" | awk 'NF')"
        [[ -z "$line" ]] && continue
        entries+=("$line")
    done < "$list_file"
else
    entries=("$@")
fi

if [[ ${#entries[@]} -eq 0 ]]; then
    cat >&2 <<EOF
usage:
  $(basename "$0") <arxiv_id> <slug> [<arxiv_id> <slug> ...]
  $(basename "$0") --from papers.txt

Examples:
  $(basename "$0") 1412.6980 kingma_adam
  $(basename "$0") --from benchmarks/arxivbench/corpus_wanted.txt
EOF
    exit 2
fi

# --- Download loop ---
# Expect pairs (id, slug) — for CLI args they arrive alternating; for --from
# they arrive as single lines "id slug".
fetch_pair() {
    local id="$1"
    local slug="$2"
    local target_dir="$CORPUS_DIR/$slug"

    if [[ -d "$target_dir" ]] && [[ -n "$(ls -A "$target_dir" 2>/dev/null || true)" ]]; then
        echo "  [skip] $slug already exists at $target_dir" >&2
        return 0
    fi

    echo "  [fetch] $id -> $slug"
    mkdir -p "$target_dir"

    local tar_tmp
    tar_tmp="$(mktemp -t "arxiv_${slug}.XXXXXX")"

    # Source tarball
    curl -sS -L --fail --user-agent "$UA" \
        "https://arxiv.org/e-print/$id" -o "$tar_tmp" || {
        echo "    source fetch failed for $id" >&2
        rm -f "$tar_tmp"
        return 1
    }

    # arXiv source is usually gzipped tar. Sometimes it's a single gzipped
    # file (older submissions). file(1) tells us.
    local kind
    kind="$(file -b "$tar_tmp")"
    if echo "$kind" | grep -qi "gzip compressed"; then
        # Could be .tar.gz or a single .tex.gz
        if tar -tzf "$tar_tmp" >/dev/null 2>&1; then
            tar -xzf "$tar_tmp" -C "$target_dir"
        else
            # Single gzipped file; decompress as main.tex
            gunzip -c "$tar_tmp" > "$target_dir/main.tex"
        fi
    elif echo "$kind" | grep -qi "tar archive"; then
        tar -xf "$tar_tmp" -C "$target_dir"
    elif echo "$kind" | grep -qi "PDF"; then
        # PDF-only submission (the 11% we can't parse)
        echo "    note: $id is PDF-only, no .tex source" >&2
        cp "$tar_tmp" "$target_dir/source.pdf"
    else
        # Try as plain text with .tex extension
        cp "$tar_tmp" "$target_dir/main.tex"
    fi
    rm -f "$tar_tmp"

    # Also archive the original bundle for reproducibility
    cp /dev/null "$target_dir/.arxiv_id" 2>/dev/null || true
    echo "$id" > "$target_dir/.arxiv_id"

    sleep "$DELAY"

    # Rendered PDF
    echo "  [fetch] $id pdf"
    curl -sS -L --fail --user-agent "$UA" \
        "https://arxiv.org/pdf/$id" -o "$target_dir/arxiv.pdf" || {
        echo "    pdf fetch failed for $id (source is still usable)" >&2
    }

    sleep "$DELAY"
}

for entry in "${entries[@]}"; do
    # entry is either "id slug" or "id" alone (if slug missing, use id)
    read -r id slug _ <<<"$entry"
    if [[ -z "${slug:-}" ]]; then
        slug="$(echo "$id" | tr '/.' '__')"
    fi
    fetch_pair "$id" "$slug" || echo "  [error] $id failed" >&2
done

echo "Done. Corpus now at: $CORPUS_DIR"
ls -1 "$CORPUS_DIR" | sed 's/^/  /'
