#!/bin/bash
# Regenerate all demo files then verify them
# Requires AI capability (uses Gemini to generate content)
set -e
cd "$(dirname "$0")/../../../.."

EXAMPLES_DIR="data/examples"
AI_MODEL="${AI_MODEL:-gemini-2.5-flash}"

echo "=== Regenerate & Verify Documents ==="
echo "AI Model: $AI_MODEL"
echo ""

# Type-check all modules first
echo "--- Type-checking all modules ---"
ailang check docparse/ 2>&1 | tail -1
echo ""

# Regenerate AI-generated demos
echo "--- Regenerating demo files ---"

echo "  DOCX: demo_report..."
DOCPARSE_OUTPUT_DIR="$EXAMPLES_DIR" ailang run --entry main --caps IO,FS,Env,AI --ai "$AI_MODEL" \
  docparse/main.ail --generate "$EXAMPLES_DIR/demo_report.docx" \
  --prompt "Professional quarterly business report with executive summary, Q1-Q4 revenue table, 5 key highlights, and outlook" \
  > /dev/null 2>&1 && echo "    OK" || echo "    FAIL"

echo "  PPTX: demo_pitch..."
DOCPARSE_OUTPUT_DIR="$EXAMPLES_DIR" ailang run --entry main --caps IO,FS,Env,AI --ai "$AI_MODEL" \
  docparse/main.ail --generate "$EXAMPLES_DIR/demo_pitch.pptx" \
  --prompt "5-slide pitch deck: title, problem, solution with features, comparison table, call to action" \
  > /dev/null 2>&1 && echo "    OK" || echo "    FAIL"

echo "  XLSX: demo_data..."
DOCPARSE_OUTPUT_DIR="$EXAMPLES_DIR" ailang run --entry main --caps IO,FS,Env,AI --ai "$AI_MODEL" \
  docparse/main.ail --generate "$EXAMPLES_DIR/demo_data.xlsx" \
  --prompt "Employee directory: 8 employees with Name, Department, Role, Start Date across 2 sheets" \
  > /dev/null 2>&1 && echo "    OK" || echo "    FAIL"

echo "  HTML: demo_page..."
DOCPARSE_OUTPUT_DIR="$EXAMPLES_DIR" ailang run --entry main --caps IO,FS,Env,AI --ai "$AI_MODEL" \
  docparse/main.ail --generate "$EXAMPLES_DIR/demo_page.html" \
  --prompt "Documentation page with h1 title, overview, h2 Installation with 4 steps, h2 Supported Formats table, h2 FAQ with 3 questions" \
  > /dev/null 2>&1 && echo "    OK" || echo "    FAIL"

echo "  ODT: demo_letter..."
DOCPARSE_OUTPUT_DIR="$EXAMPLES_DIR" ailang run --entry main --caps IO,FS,Env,AI --ai "$AI_MODEL" \
  docparse/main.ail --generate "$EXAMPLES_DIR/demo_letter.odt" \
  --prompt "Formal business letter with letterhead, 3 paragraphs about product benefits, feature comparison table, and closing" \
  > /dev/null 2>&1 && echo "    OK" || echo "    FAIL"

# Regenerate converted demos (no AI needed)
echo "  PPTX: converted_sample (from DOCX)..."
DOCPARSE_OUTPUT_DIR="$EXAMPLES_DIR" ailang run --entry main --caps IO,FS,Env \
  docparse/main.ail data/test_files/sample.docx --convert "$EXAMPLES_DIR/converted_sample.pptx" \
  > /dev/null 2>&1 && echo "    OK" || echo "    FAIL"

echo "  HTML: converted_sample (from DOCX)..."
DOCPARSE_OUTPUT_DIR="$EXAMPLES_DIR" ailang run --entry main --caps IO,FS,Env \
  docparse/main.ail data/test_files/sample.docx --convert "$EXAMPLES_DIR/converted_sample.html" \
  > /dev/null 2>&1 && echo "    OK" || echo "    FAIL"

echo "  ODT: converted_sample (from DOCX)..."
DOCPARSE_OUTPUT_DIR="$EXAMPLES_DIR" ailang run --entry main --caps IO,FS,Env \
  docparse/main.ail data/test_files/sample.docx --convert "$EXAMPLES_DIR/converted_sample.odt" \
  > /dev/null 2>&1 && echo "    OK" || echo "    FAIL"

# Clean up JSON/MD side effects
rm -f "$EXAMPLES_DIR"/*.json "$EXAMPLES_DIR"/*.md

echo ""

# Run verification
echo "--- Running verification loop ---"
uv run --with python-pptx --with openpyxl --with python-docx benchmarks/verify_generated.py
