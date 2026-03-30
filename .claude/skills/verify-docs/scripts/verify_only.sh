#!/bin/bash
# Verify generated documents without regenerating
set -e
cd "$(dirname "$0")/../../../.."

echo "=== Verify Generated Documents ==="
echo ""

# Type-check generators first
echo "--- Type-checking generators ---"
ailang check docparse/services/docx_generator.ail \
             docparse/services/pptx_generator.ail \
             docparse/services/xlsx_generator.ail \
             docparse/services/odt_generator.ail \
             docparse/services/odp_generator.ail \
             docparse/services/ods_generator.ail \
             docparse/services/html_generator.ail \
             docparse/services/xml_helpers.ail \
             docparse/services/ai_generator.ail 2>&1 | tail -1
echo ""

# Run verification
echo "--- Running verification loop ---"
uv run --with python-pptx --with openpyxl --with python-docx benchmarks/verify_generated.py
