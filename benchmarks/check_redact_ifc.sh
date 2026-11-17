#!/usr/bin/env bash
# The redaction guarantee, proved by trying to break it.
#
# docparse/redact/ claims: document content (labelled <doc_content> by
# redact/source) cannot be written, logged or sent without passing the one
# declassifier, redact/core.redactOutcome. This script writes each way of
# breaking that into a scratch copy of the package and asserts `ailang check`
# REJECTS it with the right error, then that the clean pipeline passes. If a
# leak ever type-checks, the guarantee has stopped holding: CI goes red.
#
# It is also the toolchain guard. On AILANG < 0.58.0 labels stop at module
# boundaries and cases 1, 2 and 4b compile clean (measured on v0.57.4), which
# is why ailang.toml declares ailang >= 0.58.0.
#
# Then it shows the stop-gap lint (check_redact_confinement.py) catching what the
# compiler cannot yet, and runs the redactor on fixtures with a fresh TMPDIR to
# show it writes no file.
#
# Usage (repo root): bash benchmarks/check_redact_ifc.sh
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/redact-ifc.XXXXXX")"
trap 'rm -rf "$SCRATCH"' EXIT INT TERM
cp -R "$ROOT/ailang.toml" "$ROOT/ailang.lock" "$ROOT/docparse" "$SCRATCH/"
[ -d "$ROOT/.ailang" ] && cp -R "$ROOT/.ailang" "$SCRATCH/" 2>/dev/null

pass=0
fail=0
ok()  { echo "  ok   $1"; pass=$((pass + 1)); }
bad() { echo "  FAIL $1"; printf '%s\n' "$2" | grep -v 'DEPRECATED\|readFileBytes\|readFileBase64\|skew\|^\s*$' | head -4 | sed 's/^/       /'; fail=$((fail + 1)); }

PROBE="$SCRATCH/docparse/redact/probe.ail"
HDR='import std/result (Ok, Err)
import docparse/redact/source (redactSource)
import docparse/redact/core (redactOutcome)
import docparse/redact/egress (writeRedactedJson, logRedacted)
import docparse/redact/policy (defaultRedactPolicy)
import docparse/services/orchestrator (ParseOutcome)
import docparse/services/output_formatter (formatResult)'

# expect_reject DESC EXPECTED-SUBSTRING BODY
expect_reject() {
  printf 'module docparse/redact/probe\n%s\n%s\n' "$HDR" "$3" > "$PROBE"
  local out; out=$(cd "$SCRATCH" && ailang check docparse/redact/probe.ail 2>&1)
  if printf '%s' "$out" | grep -qF -- "$2"; then ok "$1"; else bad "$1 (expected: $2)" "$out"; fi
  rm -f "$PROBE"
}

echo "IFC: leaks the compiler must reject"

expect_reject "1. unredacted document rendered to egress" \
  'reaches parameter "body" of imported function docparse/redact/egress.writeRedactedJson' \
  'export func p(path: string) -> unit ! {FS} = match redactSource(path) {
  Ok(o) => writeRedactedJson("/tmp/o.json", formatResult({document: o.document, warnings: o.warnings, aiCallsUsed: 0})),
  Err(_) => () }'

expect_reject "2. labelled text logged" \
  'reaches parameter "msg" of imported function docparse/redact/egress.logRedacted' \
  'export func p(path: string) -> unit ! {FS, IO} = match redactSource(path) {
  Ok(o) => logRedacted(o.document.metadata.title), Err(_) => () }'

# 3. The core writing a file without declaring FS: an effect error. (Declaring
#    FS there compiles; that is rule 1 of the lint, shown below.)
CORE="$SCRATCH/docparse/redact/core.ail"
cp "$CORE" "$CORE.orig"
sed -i.bak 's#^import std/list#import std/fs (writeFile)\nimport std/list#' "$CORE" && rm -f "$CORE.bak"
printf '\nexport func leakWrite(s: string) -> unit = writeFile("/dev/null", s)\n' >> "$CORE"
out=$(cd "$SCRATCH" && ailang check docparse/redact/core.ail 2>&1)
if printf '%s' "$out" | grep -qF "Missing effects: FS"; then ok "3. the core cannot write a file (effect error)"; else bad "3. the core cannot write a file" "$out"; fi
cp "$CORE.orig" "$CORE"

expect_reject "4a. laundering: labelled value returned under a cleaner label" \
  'declares return label <clean>, hiding <doc_content>' \
  'export func launder(o: ParseOutcome<doc_content>) -> string<clean> = o.document.filename'

expect_reject "4b. laundering: a helper with a plain return keeps the label" \
  'reaches parameter "body" of imported function docparse/redact/egress.writeRedactedJson' \
  'func strip(o: ParseOutcome<doc_content>) -> string = o.document.filename
export func p(path: string) -> unit ! {FS} = match redactSource(path) {
  Ok(o) => writeRedactedJson("/tmp/o.json", strip(o)), Err(_) => () }'

expect_reject "5. a declassifier scoped to another label cannot drop <doc_content>" \
  'hiding <doc_content>; declared authority Declassify[label=pii]' \
  'func strip(o: ParseOutcome<doc_content>) -> string ! {Declassify[label=pii]} = o.document.filename'

printf 'module docparse/redact/probe\n%s\n%s\n' "$HDR" 'export func p(path: string) -> unit ! {FS, Declassify[label=doc_content]} = match redactSource(path) {
  Ok(o) => { let r = redactOutcome(defaultRedactPolicy(), o);
             writeRedactedJson("/tmp/o.json", formatResult({document: r.document, warnings: r.warnings, aiCallsUsed: 0})) },
  Err(_) => () }' > "$PROBE"
out=$(cd "$SCRATCH" && ailang check docparse/redact/probe.ail 2>&1)
if printf '%s' "$out" | grep -qF "No errors found"; then ok "6. the clean pipeline (source -> redactOutcome -> egress) compiles"; else bad "6. clean pipeline compiles" "$out"; fi
rm -f "$PROBE"

echo ""
echo "Stop-gap lint: what the compiler cannot check yet"

# lint_rejects DESC FILE SED-EXPR | APPEND-TEXT
lint_case() {
  local desc="$1" file="$SCRATCH/docparse/redact/$2" mode="$3" arg="$4"
  cp "$file" "$file.orig"
  if [ "$mode" = sed ]; then sed -i.bak "$arg" "$file" && rm -f "$file.bak"; else printf '%s\n' "$arg" >> "$file"; fi
  local out; out=$(python3 "$ROOT/benchmarks/check_redact_confinement.py" "$SCRATCH" 2>&1)
  if [ $? -ne 0 ]; then ok "$desc"; else bad "$desc (lint passed)" "$out"; fi
  cp "$file.orig" "$file" && rm -f "$file.orig"
}
lint_case "core declares FS (compiles, lint refuses)" core.ail append \
  'export func leakWrite(s: string) -> unit ! {FS} = ()'
lint_case "policy imports std/fs" policy.ail sed \
  's#^import docparse/types/document#import std/fs (writeFile)\nimport docparse/types/document#'
lint_case "a second declassifier" core.ail append \
  'export func alsoDeclassify(s: string) -> string ! {Declassify[label=doc_content]} = s'
lint_case "egress parameter without {not doc_content}" egress.ail append \
  'export func writeAny(path: string{not doc_content}, body: string) -> unit ! {FS} = writeFile(path, body)'
lint_case "source imports more than the parse entry" source.ail sed \
  's#^import docparse/services/orchestrator (parseDocumentPure, defaultParseOptions, ParseOutcome)#import docparse/services/orchestrator (parseDocumentPure, parseDocument, defaultParseOptions, ParseOutcome)#'
touch "$SCRATCH/docparse/redact/extra.ail"
out=$(python3 "$ROOT/benchmarks/check_redact_confinement.py" "$SCRATCH" 2>&1)
if [ $? -ne 0 ]; then ok "an unreviewed module in docparse/redact/"; else bad "unreviewed module" "$out"; fi
rm -f "$SCRATCH/docparse/redact/extra.ail"
out=$(python3 "$ROOT/benchmarks/check_redact_confinement.py" "$SCRATCH" 2>&1)
if [ $? -eq 0 ]; then ok "the real tree passes the lint"; else bad "real tree passes the lint" "$out"; fi

echo ""
echo "No files written"
IMG=/tmp/docparse-images
before=$(ls -1 "$IMG" 2>/dev/null | sort)
RUNTMP="$(mktemp -d "${TMPDIR:-/tmp}/redact-run.XXXXXX")"
out=$(cd "$ROOT" && TMPDIR="$RUNTMP" ailang run --quiet --entry main --caps IO,FS --max-recursion-depth 50000 \
      scripts/verify_redaction.ail 2>&1)
after=$(ls -1 "$IMG" 2>/dev/null | sort)
if printf '%s' "$out" | grep -q "redaction: all checks passed"; then ok "redactor behaviour (scripts/verify_redaction.ail)"; else bad "redactor behaviour" "$(printf '%s' "$out" | grep FAIL)"; fi
if [ -z "$(ls -A "$RUNTMP")" ]; then ok "nothing written under a fresh TMPDIR"; else bad "fresh TMPDIR stays empty" "$(ls -A "$RUNTMP")"; fi
if [ "$before" = "$after" ]; then ok "no image temp files written ($IMG unchanged)"; else bad "image temp dir unchanged" "$(comm -13 <(echo "$before") <(echo "$after") | head -3)"; fi
rm -rf "$RUNTMP"

echo ""
echo "redaction IFC: $pass passed, $fail failed"
[ "$fail" -eq 0 ] || exit 1
