#!/usr/bin/env bash
# Throughput of the docparse CLI on an archive-shaped mix of Office files.
#
#   bash benchmarks/throughput/run.sh [JOBS ...]      e.g.  run.sh 1 8 12 16
#
# Builds the corpus (gen_corpus.py) once under $WORK, then for each JOBS value
# runs that many `docparse` batch processes at once, each over the whole corpus,
# and records wall time. No AI, no network. Writes results/latest.json.
#
# Needs: the repo checkout (uses bin/docparse; DOCPARSE=... to override), python3 with
# python-docx, python-pptx, openpyxl and Pillow.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
DOCPARSE="${DOCPARSE:-$REPO/bin/docparse}"
WORK="${WORK:-${TMPDIR:-/tmp}/docparse-throughput}"
PY="${PYTHON:-python3}"
JOBS_LIST=("$@")
[ ${#JOBS_LIST[@]} -gt 0 ] || JOBS_LIST=(1 8 12 16)

now() { "$PY" -c 'import time; print(time.time())'; }

rm -rf "$WORK" && mkdir -p "$WORK"
"$PY" "$HERE/gen_corpus.py" "$WORK/corpus" >/dev/null
FILES=$(find "$WORK/corpus" -type f | wc -l | tr -d ' ')
BYTES=$(find "$WORK/corpus" -type f -exec cat {} + | wc -c | tr -d ' ')
OFFICE_ONLY=("$WORK"/corpus/{memo,report,big,deck}_*)

# Warm-up: the first run compiles the parser; that cost is not throughput.
"$DOCPARSE" "$WORK/corpus/memo_0.docx" --output-dir "$WORK/warm" >/dev/null 2>&1

run_case() {  # name jobs files...
  local name=$1 jobs=$2; shift 2
  rm -rf "$WORK/out"
  local start; start=$(now)
  for i in $(seq 1 "$jobs"); do
    mkdir -p "$WORK/out/$i"
    "$DOCPARSE" "$@" --output-dir "$WORK/out/$i" >/dev/null 2>"$WORK/err.$i.log" &
  done
  wait
  local secs; secs=$("$PY" -c "import time; print(round(time.time() - $start, 2))")
  local made; made=$(find "$WORK/out" -name '*.json' | wc -l | tr -d ' ')
  echo "{\"case\": \"$name\", \"jobs\": $jobs, \"files_in\": $(( $# * jobs )), \"outputs\": $made, \"seconds\": $secs}"
}

{
  run_case "office-only (no sheets)" 1 "${OFFICE_ONLY[@]}"
  for j in "${JOBS_LIST[@]}"; do run_case "full mix" "$j" "$WORK"/corpus/*; done
} > "$WORK/cases.jsonl"

"$PY" - "$WORK/cases.jsonl" "$HERE/results/latest.json" "$FILES" "$BYTES" "$REPO/ailang.toml" <<'PY'
import json, platform, subprocess, sys, datetime
cases_path, out_path, files, nbytes, toml = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
cases = [json.loads(l) for l in open(cases_path)]
mb_per_file = nbytes / files / 1e6
for c in cases:
    c["files_per_sec"] = round(c["outputs"] / c["seconds"], 1)
    c["mb_per_sec"] = round(c["outputs"] * mb_per_file / c["seconds"], 1) if c["case"] == "full mix" else None
def sh(cmd):
    try: return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()
    except Exception: return ""
cpu = sh("sysctl -n machdep.cpu.brand_string") or sh("grep -m1 'model name' /proc/cpuinfo | cut -d: -f2")
cores = sh("sysctl -n hw.ncpu") or sh("nproc")
version = ""
for line in open(toml):
    if line.startswith("version"):
        version = line.split("=")[1].strip().strip('"'); break
json.dump({
    "run_date": datetime.date.today().isoformat(),
    "ailang_parse_version": version,
    "ailang": sh("ailang --version | head -1"),
    "machine": {"cpu": cpu.strip(), "cores": int(cores or 0), "os": platform.system()},
    "corpus": {"files": files, "bytes": nbytes, "avg_kb": round(nbytes / files / 1024)},
    "cases": cases,
}, open(out_path, "w"), indent=2)
print(open(out_path).read())
PY
