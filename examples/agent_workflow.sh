#!/bin/bash
# agent_workflow.sh — Complete AILANG Parse agent workflow example
#
# Demonstrates the full lifecycle an AI agent follows:
#   1. Discover API capabilities
#   2. Authenticate via device flow (RFC 8628)
#   3. List available test samples
#   4. Estimate cost before parsing
#   5. Parse a deterministic document (Office — no AI needed)
#   6. Parse an AI-powered document (PDF — requires AI backend)
#   7. Check quota usage
#
# Requirements:
#   - curl, python3
#   - A human to approve the device code in a browser
#
# Usage:
#   bash examples/agent_workflow.sh              # Interactive (prompts for approval)
#   DOCPARSE_API_KEY=dp_... bash examples/agent_workflow.sh  # Skip auth, use existing key

set -euo pipefail

API="${DOCPARSE_URL:-https://api.parse.sunholo.com}"

# ── Helpers ──────────────────────────────────────────────

# Unwrap serve-api envelope: {"result": "{...}", "module": "...", "elapsed_ms": N}
# Returns the parsed inner result as JSON.
unwrap() {
  python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
r = data.get('result', data)
if isinstance(r, str):
    try: r = json.loads(r)
    except: pass
json.dump(r, sys.stdout, indent=2)
print()
" 2>/dev/null
}

# Extract a single field from unwrapped JSON
field() {
  python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
r = data.get('result', data)
if isinstance(r, str):
    try: r = json.loads(r)
    except: pass
# Navigate into error object if present
if isinstance(r, dict) and 'error' in r and '$1' == 'code':
    print(r['error'].get('code', ''))
else:
    print(r.get('$1', '') if isinstance(r, dict) else '')
" 2>/dev/null
}

ok()   { printf "  ✓ %s\n" "$1"; }
fail() { printf "  ✗ %s\n" "$1"; }
info() { printf "  → %s\n" "$1"; }

# ═══════════════════════════════════════════════════════════
# Step 1: Discover
# ═══════════════════════════════════════════════════════════
echo "╔══════════════════════════════════════════════╗"
echo "║  AILANG Parse Agent Workflow Example          ║"
echo "╚══════════════════════════════════════════════╝"
echo ""
echo "=== Step 1: Discover API ==="

HEALTH=$(curl -s --max-time 10 "$API/api/v1/health")
VERSION=$(echo "$HEALTH" | field version)
info "API version: $VERSION"

CAPS=$(curl -s --max-time 10 "$API/api/v1/capabilities")
ENDPOINT_COUNT=$(echo "$CAPS" | python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
r = data.get('result', data)
if isinstance(r, str): r = json.loads(r)
print(len(r.get('endpoints', [])))
" 2>/dev/null)
ok "Capabilities: $ENDPOINT_COUNT endpoints discovered"

FORMATS=$(curl -s --max-time 10 "$API/api/v1/formats")
PARSE_FORMATS=$(echo "$FORMATS" | python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
r = data.get('result', data)
if isinstance(r, str): r = json.loads(r)
print(', '.join(r.get('parse', [])[:8]) + '...')
" 2>/dev/null)
ok "Formats: $PARSE_FORMATS"

# ═══════════════════════════════════════════════════════════
# Step 2: Authenticate
# ═══════════════════════════════════════════════════════════
echo ""
echo "=== Step 2: Authenticate ==="

if [ -n "${DOCPARSE_API_KEY:-}" ]; then
  ok "Using existing API key: ${DOCPARSE_API_KEY:0:10}..."
  API_KEY="$DOCPARSE_API_KEY"
else
  # Device authorization flow
  REQ=$(curl -s --max-time 15 -X POST "$API/api/v1/auth/device" \
    -H "Content-Type: application/json" \
    -d '{"args":["agent-example","parse"]}')

  DEVICE_CODE=$(echo "$REQ" | field device_code)
  USER_CODE=$(echo "$REQ" | field user_code)
  VERIFY_URL=$(echo "$REQ" | field verification_url)

  if [ -z "$DEVICE_CODE" ] || [ -z "$USER_CODE" ]; then
    fail "Could not get device code"
    echo "  Response: $REQ"
    exit 1
  fi

  ok "Device code obtained"
  echo ""
  echo "  ┌─────────────────────────────────────────┐"
  echo "  │  Open this URL in a browser:            │"
  echo "  │  $VERIFY_URL"
  echo "  │                                         │"
  echo "  │  User Code: $USER_CODE                  │"
  echo "  │                                         │"
  echo "  │  Sign in and click 'Approve'            │"
  echo "  └─────────────────────────────────────────┘"
  echo ""
  echo "  Polling for approval (up to 5 minutes)..."

  API_KEY=""
  for i in $(seq 1 60); do
    sleep 5
    POLL=$(curl -s --max-time 10 -X POST "$API/api/v1/auth/device/poll" \
      -H "Content-Type: application/json" \
      -d "{\"args\":[\"$DEVICE_CODE\"]}")

    STATUS=$(echo "$POLL" | field status)
    ERROR=$(echo "$POLL" | field code)

    if [ "$STATUS" = "approved" ]; then
      API_KEY=$(echo "$POLL" | field api_key)
      break
    elif [ "$ERROR" = "DEVICE_CODE_EXPIRED" ]; then
      fail "Device code expired. Run again."
      exit 1
    fi
    printf "."
  done
  echo ""

  if [ -z "$API_KEY" ]; then
    fail "Timed out waiting for approval."
    exit 1
  fi

  ok "Approved! API key: ${API_KEY:0:10}..."
  echo ""
  echo "  Save for reuse:  export DOCPARSE_API_KEY=\"$API_KEY\""
fi

# ═══════════════════════════════════════════════════════════
# Step 3: List Samples
# ═══════════════════════════════════════════════════════════
echo ""
echo "=== Step 3: List Test Samples ==="

SAMPLES=$(curl -s --max-time 10 "$API/api/v1/samples")
echo "$SAMPLES" | python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
r = data.get('result', data)
if isinstance(r, str): r = json.loads(r)
samples = r.get('samples', [])
for s in samples[:6]:
    label = s.get('label', '?')
    sid = s.get('id', '?')
    ai = ' (AI)' if s.get('ai_required') else ''
    print(f'  {sid:<25s} {label}{ai}')
if len(samples) > 6:
    print(f'  ... and {len(samples) - 6} more')
" 2>/dev/null
ok "$(echo "$SAMPLES" | python3 -c "
import json,sys; d=json.loads(sys.stdin.read()); r=d.get('result',d)
if isinstance(r,str): r=json.loads(r)
print(str(len(r.get('samples',[]))) + ' samples available')
" 2>/dev/null)"

# ═══════════════════════════════════════════════════════════
# Step 4: Estimate Cost
# ═══════════════════════════════════════════════════════════
echo ""
echo "=== Step 4: Estimate Cost (before parsing) ==="

# Estimate for a deterministic Office file (use actual file path)
EST_OFFICE=$(curl -s --max-time 10 -X POST "$API/api/v1/estimate" \
  -H "Content-Type: application/json" \
  -d '{"filepath":"data/test_files/sample.docx","outputFormat":"markdown"}')
echo "$EST_OFFICE" | python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
r = data.get('result', data)
if isinstance(r, str): r = json.loads(r)
if 'error' in r: print(f'  DOCX: (estimate unavailable: {r[\"error\"].get(\"message\",\"?\")})')
else: print(f'  DOCX: {r.get(\"estimated_credits\",\"?\")} credit(s), ~{r.get(\"estimated_ms\",\"?\")}ms, AI: {r.get(\"ai_required\",\"?\")}')
" 2>/dev/null

# Estimate for a PDF (AI-required)
EST_PDF=$(curl -s --max-time 10 -X POST "$API/api/v1/estimate" \
  -H "Content-Type: application/json" \
  -d '{"filepath":"data/test_files/simple_text.pdf","outputFormat":"markdown"}')
echo "$EST_PDF" | python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
r = data.get('result', data)
if isinstance(r, str): r = json.loads(r)
if 'error' in r: print(f'  PDF:  (estimate unavailable: {r[\"error\"].get(\"message\",\"?\")})')
else: print(f'  PDF:  {r.get(\"estimated_credits\",\"?\")} credit(s), ~{r.get(\"estimated_ms\",\"?\")}ms, AI: {r.get(\"ai_required\",\"?\")}')
" 2>/dev/null

ok "Estimates retrieved (check credits before committing)"

# ═══════════════════════════════════════════════════════════
# Step 5: Parse — Deterministic (Office, no AI)
# ═══════════════════════════════════════════════════════════
echo ""
echo "=== Step 5: Parse DOCX (deterministic, no AI) ==="

PARSE_DOCX=$(curl -s --max-time 30 -X POST "$API/api/v1/parse" \
  -H "Content-Type: application/json" \
  -d "{\"filepath\":\"sample_docx_formatting\",\"outputFormat\":\"markdown\",\"apiKey\":\"$API_KEY\"}")

# Check for errors
PARSE_ERROR=$(echo "$PARSE_DOCX" | field code)
if [ -n "$PARSE_ERROR" ] && [ "$PARSE_ERROR" != "" ]; then
  fail "Parse error: $PARSE_ERROR"
  echo "$PARSE_DOCX" | unwrap
else
  # Show first ~20 lines of markdown output
  echo "$PARSE_DOCX" | python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
r = data.get('result', data)
if isinstance(r, str):
    # @nowrap returns raw content
    lines = r.strip().split('\n')
    for line in lines[:15]:
        print('  ' + line)
    if len(lines) > 15:
        print(f'  ... ({len(lines) - 15} more lines)')
" 2>/dev/null
  ok "DOCX parsed (deterministic — same output every time)"

  # Show response metadata if available
  echo "$PARSE_DOCX" | python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
meta = data.get('meta', {})
if meta:
    print(f'  request_id: {meta.get(\"request_id\", \"n/a\")}')
    print(f'  replayable: {meta.get(\"replayable\", \"n/a\")}')
    print(f'  elapsed_ms: {data.get(\"elapsed_ms\", \"n/a\")}')
" 2>/dev/null
fi

# ═══════════════════════════════════════════════════════════
# Step 6: Parse — AI-Powered (PDF)
# ═══════════════════════════════════════════════════════════
echo ""
echo "=== Step 6: Parse PDF (AI-powered) ==="

PARSE_PDF=$(curl -s --max-time 60 -X POST "$API/api/v1/parse" \
  -H "Content-Type: application/json" \
  -d "{\"filepath\":\"sample_pdf\",\"outputFormat\":\"markdown\",\"apiKey\":\"$API_KEY\"}")

# PDF requires AI — may fail if server doesn't have --ai configured
PARSE_PDF_ERR_MSG=$(echo "$PARSE_PDF" | python3 -c "
import json, sys
d = json.loads(sys.stdin.read())
r = d.get('result', d)
if isinstance(r, str):
    try: r = json.loads(r)
    except: pass
if isinstance(r, dict):
    if 'error' in r and isinstance(r['error'], dict): print(r['error'].get('code', ''))
    elif 'error' in r and isinstance(r['error'], str): print(r['error'][:60])
    else: print('')
else: print('')
" 2>/dev/null)

if echo "$PARSE_PDF_ERR_MSG" | grep -qi "ai\|model\|AI_UNAVAILABLE"; then
  info "AI not configured on this server (expected for dev instances)"
  info "PDF parsing works when server has --ai gemini-2.5-flash"
  info "All 12 deterministic formats (Office/Web/Text) work without AI"
elif [ -n "$PARSE_PDF_ERR_MSG" ] && [ "$PARSE_PDF_ERR_MSG" != "" ]; then
  fail "Parse error: $PARSE_PDF_ERR_MSG"
  echo "$PARSE_PDF" | unwrap
else
  echo "$PARSE_PDF" | python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
r = data.get('result', data)
if isinstance(r, str):
    lines = r.strip().split('\n')
    for line in lines[:10]:
        print('  ' + line)
    if len(lines) > 10:
        print(f'  ... ({len(lines) - 10} more lines)')
" 2>/dev/null
  ok "PDF parsed (AI-powered — content depends on model)"
fi

# ═══════════════════════════════════════════════════════════
# Step 7: Check Quota
# ═══════════════════════════════════════════════════════════
echo ""
echo "=== Step 7: Check Remaining Quota ==="

QUOTA=$(curl -s --max-time 10 -X POST "$API/api/docparse/services/api_keys/checkQuota" \
  -H "Content-Type: application/json" \
  -d "{\"args\":[\"$API_KEY\"]}")
echo "$QUOTA" | python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
r = data.get('result', data)
if isinstance(r, str):
    try: r = json.loads(r)
    except: pass
if isinstance(r, dict):
    if r.get('allowed') == False or r.get('error'):
        print(f'  (Quota check failed — {r.get(\"error\", \"unknown\")})')
    else:
        print(f'  Allowed:         {r.get(\"allowed\", \"?\")}')
        print(f'  Tier:            {r.get(\"tier\", \"?\")}')
        print(f'  Requests today:  {r.get(\"requestsToday\", \"?\")}')
        print(f'  Daily limit:     {r.get(\"requestsPerDay\", \"?\")}')
        print(f'  AI budget/req:   {r.get(\"aiLimit\", \"?\")}')
        print(f'  FS budget/req:   {r.get(\"fsLimit\", \"?\")}')
" 2>/dev/null

# ═══════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════
echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  Workflow Complete                           ║"
echo "╠══════════════════════════════════════════════╣"
echo "║  API Key: ${API_KEY:0:20}...       ║"
echo "║  Reuse:   export DOCPARSE_API_KEY=...       ║"
echo "║                                              ║"
echo "║  Next steps:                                 ║"
echo "║  • Parse your own files (any of 13 formats)  ║"
echo "║  • Use GET /api/v1/tools for MCP/OpenAI defs ║"
echo "║  • Check GET /api/v1/pricing for tier limits  ║"
echo "╚══════════════════════════════════════════════╝"
