#!/usr/bin/env bash
set -euo pipefail

# Download test files from open-source repos to expand benchmark corpus.
# Idempotent: skips files that already exist.
# See SOURCES.md for attribution and licensing.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
TARGET_DIR="$REPO_DIR/data/test_files"

mkdir -p "$TARGET_DIR"

download() {
  local url="$1"
  local dest="$2"
  if [ -f "$dest" ]; then
    echo "  EXISTS $(basename "$dest")"
  else
    echo -n "  GET    $(basename "$dest") ... "
    if curl -sfL "$url" -o "$dest"; then
      echo "OK ($(wc -c < "$dest" | tr -d ' ') bytes)"
    else
      echo "FAIL"
      rm -f "$dest"
    fi
  fi
}

PASS=0
FAIL=0

# ============================================================
# Pandoc test files (github.com/jgm/pandoc, GPL-2.0)
# ============================================================
echo ""
echo "=== Pandoc DOCX test files ==="
PANDOC_BASE="https://raw.githubusercontent.com/jgm/pandoc/main/test/docx"

download "$PANDOC_BASE/notes.docx" "$TARGET_DIR/pandoc_notes.docx"
download "$PANDOC_BASE/track_changes_insertion.docx" "$TARGET_DIR/pandoc_tc_insertion.docx"
download "$PANDOC_BASE/track_changes_deletion.docx" "$TARGET_DIR/pandoc_tc_deletion.docx"
download "$PANDOC_BASE/inline_images.docx" "$TARGET_DIR/pandoc_inline_images.docx"
download "$PANDOC_BASE/table_with_list_cell.docx" "$TARGET_DIR/pandoc_table_list.docx"

echo ""
echo "=== Pandoc table test files (HTML + Markdown) ==="
PANDOC_TABLES="https://raw.githubusercontent.com/jgm/pandoc/main/test/tables"

download "$PANDOC_TABLES/planets.html5" "$TARGET_DIR/pandoc_planets.html"
download "$PANDOC_TABLES/nordics.html5" "$TARGET_DIR/pandoc_nordics.html"
download "$PANDOC_TABLES/planets.markdown" "$TARGET_DIR/pandoc_planets.md"

# ============================================================
# Apache POI test files (github.com/apache/poi, Apache-2.0)
# ============================================================
echo ""
echo "=== Apache POI XLSX test files ==="
POI_XLSX="https://raw.githubusercontent.com/apache/poi/trunk/test-data/spreadsheet"

download "$POI_XLSX/TwoSheetsNoneHidden.xlsx" "$TARGET_DIR/poi_two_sheets.xlsx"
download "$POI_XLSX/57893-many-merges.xlsx" "$TARGET_DIR/poi_many_merges.xlsx"

echo ""
echo "=== Apache POI PPTX test files ==="
POI_PPTX="https://raw.githubusercontent.com/apache/poi/trunk/test-data/slideshow"

download "$POI_PPTX/table_test.pptx" "$TARGET_DIR/poi_table.pptx"
download "$POI_PPTX/SampleShow.pptx" "$TARGET_DIR/poi_sampleshow.pptx"
download "$POI_PPTX/45545_Comment.pptx" "$TARGET_DIR/poi_comment.pptx"

echo ""
echo "=== Apache POI DOCX test files ==="
POI_DOCX="https://raw.githubusercontent.com/apache/poi/trunk/test-data/document"

download "$POI_DOCX/footnotes.docx" "$TARGET_DIR/poi_footnotes.docx"

# ============================================================
# Hand-crafted test files (created inline)
# ============================================================
echo ""
echo "=== Hand-crafted test files ==="

# TSV variant
if [ ! -f "$TARGET_DIR/test.tsv" ]; then
  cat > "$TARGET_DIR/test.tsv" << 'TSVEOF'
Name	Age	City	Score
Alice	30	London	95.5
Bob	25	Paris	87.3
Charlie	35	Berlin	91.0
Diana	28	Madrid	88.7
Eve	32	Rome	93.2
TSVEOF
  echo "  CREATE test.tsv"
else
  echo "  EXISTS test.tsv"
fi

# CSV with embedded quotes and commas
if [ ! -f "$TARGET_DIR/test_quoted.csv" ]; then
  cat > "$TARGET_DIR/test_quoted.csv" << 'CSVEOF'
Name,Description,Value
"Smith, John","He said ""hello""",100
"O'Brien, Jane","Line 1
Line 2",200
Simple,No special chars,300
"Comma, City","State, Country",400
CSVEOF
  echo "  CREATE test_quoted.csv"
else
  echo "  EXISTS test_quoted.csv"
fi

# Complex HTML with nested tables, definition lists, semantic elements
if [ ! -f "$TARGET_DIR/test_complex.html" ]; then
  cat > "$TARGET_DIR/test_complex.html" << 'HTMLEOF'
<!DOCTYPE html>
<html lang="en">
<head><title>Complex HTML Test</title></head>
<body>
  <header><h1>Document Title</h1><p>Subtitle text</p></header>
  <nav><ul><li>Chapter 1</li><li>Chapter 2</li></ul></nav>
  <main>
    <article>
      <h2>Section One</h2>
      <p>First paragraph with <strong>bold</strong> and <em>italic</em> text.</p>
      <blockquote><p>A notable quotation from someone important.</p></blockquote>
      <table>
        <thead><tr><th>Product</th><th>Price</th><th>Stock</th></tr></thead>
        <tbody>
          <tr><td>Widget A</td><td>$10.00</td><td>150</td></tr>
          <tr><td>Widget B</td><td>$25.50</td><td>42</td></tr>
          <tr><td>Widget C</td><td>$5.75</td><td>300</td></tr>
        </tbody>
      </table>
      <h3>Nested Table Example</h3>
      <table>
        <tr><td>Outer Cell 1</td><td>
          <table>
            <tr><td>Inner A</td><td>Inner B</td></tr>
            <tr><td>Inner C</td><td>Inner D</td></tr>
          </table>
        </td></tr>
        <tr><td>Outer Cell 2</td><td>Simple text</td></tr>
      </table>
      <dl>
        <dt>Term 1</dt><dd>Definition for term 1</dd>
        <dt>Term 2</dt><dd>Definition for term 2</dd>
      </dl>
    </article>
    <article>
      <h2>Section Two</h2>
      <ol>
        <li>First ordered item</li>
        <li>Second ordered item
          <ul>
            <li>Nested unordered A</li>
            <li>Nested unordered B</li>
          </ul>
        </li>
        <li>Third ordered item</li>
      </ol>
      <pre><code>function hello() {
  console.log("Hello, World!");
}</code></pre>
    </article>
  </main>
  <footer><p>Footer text &copy; 2025</p></footer>
</body>
</html>
HTMLEOF
  echo "  CREATE test_complex.html"
else
  echo "  EXISTS test_complex.html"
fi

# Code-heavy Markdown with fenced blocks, blockquotes, nested lists
if [ ! -f "$TARGET_DIR/test_code.md" ]; then
  cat > "$TARGET_DIR/test_code.md" << 'MDEOF'
# Code Examples

## Python

```python
def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n-1) + fibonacci(n-2)
```

## JavaScript

```javascript
const greet = (name) => `Hello, ${name}!`;
console.log(greet("World"));
```

## Blockquote with attribution

> The best way to predict the future is to invent it.
>
> — Alan Kay

## Nested Lists

1. Languages
   - Compiled
     - Go
     - Rust
   - Interpreted
     - Python
     - Ruby
2. Frameworks
   - Web: React, Vue
   - Mobile: Flutter, SwiftUI

## Table

| Language | Year | Paradigm |
|----------|------|----------|
| Python | 1991 | Multi |
| Go | 2009 | Concurrent |
| Rust | 2010 | Systems |
| AILANG | 2025 | Functional |

## Inline code

Use `pip install ailang` to install. The `--caps` flag sets capabilities.
MDEOF
  echo "  CREATE test_code.md"
else
  echo "  EXISTS test_code.md"
fi

# ============================================================
# Summary
# ============================================================
echo ""
TOTAL=$(find "$TARGET_DIR" -type f \( -name "*.docx" -o -name "*.pptx" -o -name "*.xlsx" \
  -o -name "*.odt" -o -name "*.odp" -o -name "*.ods" \
  -o -name "*.epub" -o -name "*.html" -o -name "*.csv" -o -name "*.tsv" \
  -o -name "*.md" \) | wc -l | tr -d ' ')
echo "Total test files: $TOTAL"
echo ""
echo "Next steps:"
echo "  bash benchmarks/generate_golden.sh    # Generate golden outputs"
echo "  uv run benchmarks/run_benchmarks.py --suite office  # Verify 100%"
