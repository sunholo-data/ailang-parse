"""Hybrid & Resolution-Slicing PDF Benchmark.

Compares deterministic (`poppler`), selective hybrid (`hybrid`), and full AI
(`ai` at `low` and `medium` resolution via std/ai.callMediaResult) across:
  1. `digital`  — 4-page clean digital PDF (hybrid should make 0 AI calls)
  2. `partial`  — 4 digital pages + 2 scanned image pages with stamps
                  (hybrid should OCR ONLY pages 5-6)
  3. `scanned`  — 4 fully scanned pages with stamps
                  (hybrid should auto-escalate to full AI OCR)

Usage:
    python3 benchmarks/pdf/hybrid_benchmark.py
    GOOGLE_API_KEY="" GOOGLE_CLOUD_LOCATION=eu python3 benchmarks/pdf/hybrid_benchmark.py --ai
    GOOGLE_API_KEY="" GOOGLE_CLOUD_LOCATION=eu python3 benchmarks/pdf/hybrid_benchmark.py --ai --json /tmp/hybrid_bench.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from text_layer_fixtures import fixtures

REPO = Path(__file__).resolve().parent.parent.parent
CLI = REPO / "bin" / "docparse"


def run_one(
    pdf_path: Path, backend: str, out_dir: Path, resolution: str | None = None
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    if resolution is not None:
        env["DOCPARSE_AI_RESOLUTION"] = resolution
    t0 = time.perf_counter()
    proc = subprocess.run(
        [str(CLI), str(pdf_path), "--pdf-backend", backend, "--output-dir", str(out_dir)],
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
    )
    elapsed = time.perf_counter() - t0
    json_path = out_dir / f"{pdf_path.name}.json"
    blocks = 0
    warnings = 0
    if json_path.exists():
        doc = json.loads(json_path.read_text(encoding="utf-8"))
        blocks = len(doc.get("document", {}).get("blocks", []))
        warnings = len(doc.get("warnings", []))
    note = ""
    for line in (proc.stdout + "\n" + proc.stderr).splitlines():
        if "Parsed PDF" in line or "PDF_TEXT_LAYER_SPARSE" in line or "textless_pages" in line:
            note = line.strip()
            break
    return {
        "exit_code": proc.returncode,
        "seconds": round(elapsed, 2),
        "blocks": blocks,
        "warnings": warnings,
        "note": note,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Hybrid & slicing PDF benchmark")
    ap.add_argument(
        "--ai",
        action="store_true",
        help="Include live AI backends (hybrid, ai@low, ai@medium) — paid calls",
    )
    ap.add_argument("--json", type=Path, help="Write JSON results to this path")
    args = ap.parse_args()

    cases = [
        ("forms.pdf", "digital (4 pages)"),
        ("partial.pdf", "partial scan (4 digital + 2 scanned)"),
        ("scanned.pdf", "full scan (6 scanned pages)"),
    ]
    configs: list[tuple[str, str, str | None]] = [("poppler", "poppler", None)]
    if args.ai:
        configs += [
            ("hybrid", "hybrid", None),
            ("ai (low)", "ai", "low"),
            ("ai (medium)", "ai", "medium"),
        ]

    all_fixtures = fixtures()
    results: dict[str, dict[str, dict]] = {}
    with tempfile.TemporaryDirectory(prefix="hybrid-bench-") as tmp:
        tmp_path = Path(tmp)
        for key, label in cases:
            pdf_path = tmp_path / key
            pdf_path.write_bytes(all_fixtures[key])
            results[key] = {"label": label, "runs": {}}
            for cfg_name, backend, res in configs:
                out_dir = tmp_path / "out" / key / cfg_name.replace(" ", "_")
                results[key]["runs"][cfg_name] = run_one(pdf_path, backend, out_dir, res)

    print("\n| Fixture | Backend | Exit | Time (s) | Blocks | Warnings | Note |")
    print("|---|---|---:|---:|---:|---:|---|")
    for key, _ in cases:
        label = results[key]["label"]
        for cfg_name, _, _ in configs:
            r = results[key]["runs"][cfg_name]
            note = r["note"][:70] + ("…" if len(r["note"]) > 70 else "")
            print(
                f"| {label} | {cfg_name} | {r['exit_code']} | {r['seconds']:.2f} | "
                f"{r['blocks']} | {r['warnings']} | {note} |"
            )

    if args.json:
        args.json.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
