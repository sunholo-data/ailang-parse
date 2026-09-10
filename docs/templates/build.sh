#!/usr/bin/env bash
# Rebuild the reference documents from source/parts/, then regenerate the
# three proposal templates from proposal.md through docparse itself.
set -euo pipefail
cd "$(dirname "$0")"
export AILANG_NO_TRACE=1 OTEL_SDK_DISABLED=true
ailang run --quiet --entry main --caps IO,FS source/build.ail
for brand in sunholo holosun ailang; do
  docparse "$PWD/proposal.md" --convert "$PWD/output/$brand-proposal.docx" \
    --reference-doc "$PWD/output/references/$brand-reference.docx" \
    --table-style SunholoTable --output-dir "$PWD/.build/parsed-source"
done
