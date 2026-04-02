#!/bin/bash
# quickstart.sh — Fastest path to your first AILANG Parse API call
#
# Device auth flow (user approves in browser, key is tied to Firebase identity):
#   bash examples/quickstart.sh
#
# With existing key (skip auth):
#   DOCPARSE_API_KEY=dp_... bash examples/quickstart.sh

set -euo pipefail

API="${DOCPARSE_URL:-https://api.parse.sunholo.com}"
KEY="${DOCPARSE_API_KEY:-}"

# Helper: unwrap serve-api double-encoded envelope
unwrap() { python3 -c "import sys,json; d=json.load(sys.stdin); r=d.get('result',d); print(json.dumps(json.loads(r)) if isinstance(r,str) else json.dumps(r))" 2>/dev/null; }
field() { python3 -c "import sys,json; r=json.loads(sys.stdin.read()); print(r.get('$1',''))" 2>/dev/null; }

if [ -z "$KEY" ]; then
  echo "Getting API key via device auth flow..."
  echo ""

  RESP=$(curl -s --max-time 30 -X POST "$API/api/v1/auth/device" \
    -H "Content-Type: application/json" \
    -d '{"args":["quickstart","parse"]}' | unwrap)

  DC=$(echo "$RESP" | field device_code)
  UC=$(echo "$RESP" | field user_code)
  URL=$(echo "$RESP" | field verification_url)

  echo "  Open: $URL"
  echo "  Code: $UC"
  echo ""
  echo "  Sign in and click Approve, then come back here."
  echo "  Waiting..."

  for i in $(seq 1 60); do
    sleep 5
    POLL=$(curl -s --max-time 10 -X POST "$API/api/v1/auth/device/poll" \
      -H "Content-Type: application/json" -d "{\"args\":[\"$DC\"]}" | unwrap)
    STATUS=$(echo "$POLL" | field status)
    if [ "$STATUS" = "approved" ]; then
      KEY=$(echo "$POLL" | field api_key)
      echo ""
      echo "  Approved! Key: $KEY"
      echo "  Save it: export DOCPARSE_API_KEY=\"$KEY\""
      break
    fi
    printf "."
  done
  echo ""

  if [ -z "$KEY" ]; then
    echo "Timed out. Run again after approving."
    exit 1
  fi
fi

echo ""
echo "── Parse a built-in sample (DOCX → Markdown) ──"
echo ""

curl -s --max-time 30 -X POST "$API/api/v1/parse" \
  -H "Content-Type: application/json" \
  -d "{\"filepath\":\"sample_docx_formatting\",\"outputFormat\":\"markdown\",\"apiKey\":\"$KEY\"}" \
  | python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
r = data.get('result', data)
if isinstance(r, str):
    print(r[:1000])
    if len(r) > 1000: print('...')
else:
    print(json.dumps(r, indent=2)[:1000])
" 2>/dev/null

echo ""
echo ""
echo "── Try other formats ──"
echo ""
echo "  # Parse any of 22 built-in samples:"
echo "  sample_docx_formatting, sample_docx_tables, sample_docx_comments,"
echo "  sample_docx_track_changes, sample_docx_footnotes, sample_docx_hyperlinks,"
echo "  sample_docx_real_world, sample_pptx_notes, sample_pptx_formatting,"
echo "  sample_xlsx_merged, sample_xlsx_formulas, sample_xlsx_formats,"
echo "  sample_csv, sample_markdown, sample_html, sample_odt, sample_odp,"
echo "  sample_ods, sample_epub, sample_eml,"
echo "  sample_pdf (AI), sample_mp3 (AI), sample_mp4 (AI)"
echo ""
echo "  # Or download a test file and parse by URL/path:"
echo "  # https://github.com/sunholo-data/docparse/raw/main/data/test_files/sample.docx"
echo "  # https://github.com/sunholo-data/docparse/raw/main/data/test_files/tables.docx"
echo "  # https://github.com/sunholo-data/docparse/raw/main/data/test_files/simple_text.pdf"
echo ""
echo "  # Output formats: blocks, markdown, html, a2ui"
echo "  curl -X POST $API/api/v1/parse \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"filepath\":\"sample_pptx_notes\",\"outputFormat\":\"markdown\",\"apiKey\":\"$KEY\"}'"
