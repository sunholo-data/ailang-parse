#!/usr/bin/env bash
# End-to-end regression for two email defects, through the real CLI.
#
# 1. A Maildir message (`<time>.<unique>.<host>,U=<uid>:2,<flags>`) or an
#    extensionless message was refused as format "unknown": content sniffing
#    only knew binary magic numbers. It must parse as email, exit 0.
# 2. A message/rfc822 attachment (a forwarded message) got attachment-meta
#    but no attachment-data, so it could not be extracted. Its data must
#    decode to the forwarded message's bytes, --no-attachment-data must still
#    drop it, and the forwarded message must still be parsed inline.
#
# The Maildir name is created at run time: a ':' in a committed filename
# breaks checkout on Windows. All fixture content is invented.
#
# Usage: bash tests/test_eml_maildir_rfc822.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="$ROOT/bin/docparse"
FIX="$ROOT/tests/fixtures/eml"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PASS=0
FAIL=0
ok()   { echo "  PASS  $1"; PASS=$((PASS + 1)); }
bad()  { echo "  FAIL  $1"; FAIL=$((FAIL + 1)); }

# run <outdir> <args...> : run the CLI from <outdir>, capture stdout+exit code
run() {
  local out="$1"; shift
  mkdir -p "$out"
  set +e
  (cd "$out" && DOCPARSE_OUTPUT_DIR="$out" "$CLI" "$@") > "$out/stdout.txt" 2>&1
  echo $? > "$out/exit.txt"
  set -e
}

echo "── Maildir-named message"
MAILDIR_NAME='1757340000.12345_1.studio,U=42:2,S'
mkdir -p "$WORK/cur"
cp "$FIX/maildir_message.eml" "$WORK/cur/$MAILDIR_NAME"
run "$WORK/o1" "$WORK/cur/$MAILDIR_NAME"
[ "$(cat "$WORK/o1/exit.txt")" = 0 ] && ok "exit 0" || bad "exit $(cat "$WORK/o1/exit.txt")"
grep -q '^Format:   email (eml, detected from content)' "$WORK/o1/stdout.txt" \
  && ok "banner says email" || bad "banner: $(grep '^Format' "$WORK/o1/stdout.txt")"
if grep -q 'AI multimodal' "$WORK/o1/stdout.txt"; then bad "banner mentions AI"; else ok "no AI strategy line"; fi
python3 - "$WORK/o1/$MAILDIR_NAME.json" <<'PY' && ok "JSON is the email" || bad "JSON content"
import json, sys
d = json.load(open(sys.argv[1]))["document"]
assert d["format"] == "eml", d["format"]
assert d["metadata"]["title"] == "Quarterly planning notes", d["metadata"]
text = json.dumps(d["blocks"])
assert "The planning session moved to Thursday" in text
PY

echo "── Extensionless message"
cp "$FIX/maildir_message.eml" "$WORK/cur/message"
run "$WORK/o2" "$WORK/cur/message"
[ "$(cat "$WORK/o2/exit.txt")" = 0 ] && ok "exit 0" || bad "exit $(cat "$WORK/o2/exit.txt")"
grep -q '^Format:   email' "$WORK/o2/stdout.txt" && ok "banner says email" || bad "banner"

echo "── Non-mail text with an unknown extension is still refused"
printf 'Meeting notes: Thursday\nFrom: the team\n\nAgenda\n' > "$WORK/cur/notes.weird"
run "$WORK/o3" "$WORK/cur/notes.weird"
[ "$(cat "$WORK/o3/exit.txt")" = 1 ] && ok "exit 1" || bad "exit $(cat "$WORK/o3/exit.txt")"
grep -q 'parse_refused' "$WORK/o3/stdout.txt" && ok "parse_refused" || bad "no parse_refused"
if grep -q 'AI multimodal' "$WORK/o3/stdout.txt"; then bad "refusal announced an AI strategy"; else ok "no AI strategy before refusal"; fi

# check_rfc822 <json> <expected-bytes-file> <expect-data:1|0>
check_rfc822() {
  python3 - "$@" <<'PY'
import base64, json, sys
path, expected_path, expect_data = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
blocks = json.load(open(path))["document"]["blocks"]
def walk(bs):
    for b in bs:
        yield b
        yield from walk(b.get("blocks") or b.get("children") or [])
def styled(style):
    return [b.get("text") for b in walk(blocks) if b.get("style") == style]
metas = styled("attachment-meta")
assert any("(message/rfc822)" in m for m in metas), metas
data, exts = styled("attachment-data"), styled("attachment-ext")
if expect_data:
    assert exts and exts[0] == "eml", exts
    got = base64.b64decode(data[0])
    want = open(expected_path, "rb").read()
    assert got == want, (got[:80], want[:80])
else:
    assert data == [] and exts == [], (data, exts)
# The forwarded message is still descended into, nested attachment included.
assert len(metas) >= 1
print("    metas:", metas)
PY
}

echo "── message/rfc822, base64 (challenge_email_in_email.eml)"
EIE="$ROOT/data/test_files/challenge/challenge_email_in_email.eml"
python3 - "$EIE" "$WORK/eie_inner.bin" <<'PY'
import base64, sys
text = open(sys.argv[1]).read()
payload = text.split('Content-Transfer-Encoding: base64\n\n', 1)[1].split('\n------=_Part_011', 1)[0]
open(sys.argv[2], "wb").write(base64.b64decode("".join(payload.split())))
PY
run "$WORK/o4" "$EIE"
check_rfc822 "$WORK/o4/challenge_email_in_email.eml.json" "$WORK/eie_inner.bin" 1 \
  && ok "data decodes to the forwarded message" || bad "base64 rfc822 data"
run "$WORK/o5" "$EIE" --no-attachment-data
check_rfc822 "$WORK/o5/challenge_email_in_email.eml.json" "$WORK/eie_inner.bin" 0 \
  && ok "--no-attachment-data drops it" || bad "--no-attachment-data"

echo "── message/rfc822, 7bit, with a nested attachment"
SEVEN="$FIX/forward_rfc822_7bit.eml"
python3 - "$SEVEN" "$WORK/seven_inner.bin" <<'PY'
import sys
text = open(sys.argv[1]).read()
inner = text.split('filename="venue-options.eml"\n\n', 1)[1].split('\n--OUTER-7BIT--', 1)[0]
open(sys.argv[2], "wb").write(inner.encode())
PY
run "$WORK/o6" "$SEVEN"
check_rfc822 "$WORK/o6/forward_rfc822_7bit.eml.json" "$WORK/seven_inner.bin" 1 \
  && ok "data decodes to the forwarded message" || bad "7bit rfc822 data"
grep -q 'venues.csv (text/csv)' "$WORK/o6/stdout.txt" && ok "nested attachment still parsed" || bad "nested attachment missing"
run "$WORK/o7" "$SEVEN" --no-attachment-data
check_rfc822 "$WORK/o7/forward_rfc822_7bit.eml.json" "$WORK/seven_inner.bin" 0 \
  && ok "--no-attachment-data drops it" || bad "--no-attachment-data (7bit)"

echo "── Determinism"
run "$WORK/o8" "$SEVEN"
cmp -s "$WORK/o6/forward_rfc822_7bit.eml.json" "$WORK/o8/forward_rfc822_7bit.eml.json" \
  && ok "same input, byte-identical JSON" || bad "JSON differs between runs"
run "$WORK/o9" "$WORK/cur/$MAILDIR_NAME"
cmp -s "$WORK/o1/$MAILDIR_NAME.json" "$WORK/o9/$MAILDIR_NAME.json" \
  && ok "Maildir JSON byte-identical" || bad "Maildir JSON differs between runs"

echo ""
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
