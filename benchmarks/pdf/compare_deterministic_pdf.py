"""Head-to-head deterministic PDF benchmark: pdftotext vs poppler.

Runs both free local backends (`pdftotext` and `poppler`) across all real PDFs
in `data/test_files/` (including the 15 arXiv papers) plus synthetic fixtures
(`forms.pdf`, `slides.pdf`, `partial.pdf`), measuring:
  - Word retention of `poppler` relative to `pdftotext` (|P ∩ T| / |T|)
  - Structure recovered by `poppler` (headings, tables, lists, furniture sections)
  - Wall-clock latency (ms)
  - Whether a dual-deterministic word-loss guard (<95% word retention) fires

Usage:
    python3 benchmarks/pdf/compare_deterministic_pdf.py
    python3 benchmarks/pdf/compare_deterministic_pdf.py --json /tmp/det_pdf.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
import time
from collections import Counter
from pathlib import Path

from text_layer_fixtures import fixtures

REPO = Path(__file__).resolve().parent.parent.parent
CLI = REPO / "bin" / "docparse"
TEST_DIR = REPO / "data" / "test_files"


def extract_text_and_counts(blocks: list[dict]) -> tuple[Counter[str], dict[str, int]]:
    words: Counter[str] = Counter()
    counts = {"headings": 0, "tables": 0, "lists": 0, "furniture": 0, "blocks": 0}

    def walk(bs: list[dict]) -> None:
        for b in bs:
            t = b.get("type", "")
            counts["blocks"] += 1
            if t == "section":
                if b.get("kind") in ("header", "footer"):
                    counts["furniture"] += 1
                walk(b.get("blocks", []))
            elif t == "heading":
                counts["headings"] += 1
                words.update(re.findall(r"[a-z0-9]+", (b.get("text") or "").lower()))
            elif t == "table":
                counts["tables"] += 1
                for row in [b.get("headers", [])] + b.get("rows", []):
                    for c in row:
                        txt = c.get("text", "") if isinstance(c, dict) else str(c)
                        words.update(re.findall(r"[a-z0-9]+", txt.lower()))
            elif t == "list":
                counts["lists"] += 1
                for item in b.get("items", []):
                    words.update(re.findall(r"[a-z0-9]+", str(item).lower()))
            else:
                txt = b.get("text") or ""
                if txt:
                    words.update(re.findall(r"[a-z0-9]+", txt.lower()))

    walk(blocks)
    return words, counts


def run_batch(files: list[Path], backend: str, out_dir: Path) -> tuple[float, dict[str, dict]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    subprocess.run(
        [str(CLI), *map(str, files), "--pdf-backend", backend, "--output-dir", str(out_dir)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    elapsed = time.perf_counter() - t0
    parsed: dict[str, dict] = {}
    for f in files:
        jp = out_dir / f"{f.name}.json"
        if jp.exists():
            parsed[f.name] = json.loads(jp.read_text(encoding="utf-8"))
    return elapsed, parsed


def main() -> int:
    ap = argparse.ArgumentParser(description="Head-to-head pdftotext vs poppler PDF benchmark")
    ap.add_argument("--json", type=Path, help="Write JSON summary to this path")
    args = ap.parse_args()

    real_pdfs = sorted(TEST_DIR.rglob("*.pdf"))
    all_fx = fixtures()

    with tempfile.TemporaryDirectory(prefix="det-pdf-bench-") as tmp:
        tmp_path = Path(tmp)
        synth_pdfs: list[Path] = []
        for name in ("forms.pdf", "slides.pdf", "partial.pdf"):
            p = tmp_path / name
            p.write_bytes(all_fx[name])
            synth_pdfs.append(p)

        files = real_pdfs + synth_pdfs
        t_txt, txt_docs = run_batch(files, "pdftotext", tmp_path / "pdftotext")
        t_pop, pop_docs = run_batch(files, "poppler", tmp_path / "poppler")

    rows = []
    print(f"Batch of {len(files)} PDFs: pdftotext={t_txt:.2f}s, poppler={t_pop:.2f}s\n")
    print("| File | pdftotext words | poppler words | Word retention | Poppler H / T / L / Ftr | Guard (<95%) |")
    print("|---|---:|---:|---:|---|---|")

    guard_hits = 0
    for f in files:
        td = txt_docs.get(f.name)
        pd = pop_docs.get(f.name)
        if not td or not pd:
            print(f"| {f.name} | {'OK' if td else 'ERR'} | {'OK' if pd else 'ERR'} | — | — | ERR |")
            continue
        tw, _ = extract_text_and_counts(td.get("document", {}).get("blocks", []))
        pw, pc = extract_text_and_counts(pd.get("document", {}).get("blocks", []))
        t_total = sum(tw.values())
        p_total = sum(pw.values())
        overlap = sum((tw & pw).values())
        retention = (overlap / t_total) if t_total > 0 else 1.0
        flagged = retention < 0.95
        if flagged:
            guard_hits += 1
        rows.append(
            {
                "file": f.name,
                "pdftotext_words": t_total,
                "poppler_words": p_total,
                "word_retention": round(retention, 4),
                "poppler_structure": pc,
                "guard_triggered": flagged,
            }
        )
        struct = f"{pc['headings']}H / {pc['tables']}T / {pc['lists']}L / {pc['furniture']}F"
        print(
            f"| {f.name} | {t_total} | {p_total} | {retention * 100:.1f}% | {struct} | "
            f"{'YES' if flagged else 'no'} |"
        )

    mean_ret = sum(r["word_retention"] for r in rows) / len(rows) if rows else 0.0
    print(f"\nSummary: {len(rows)}/{len(files)} parsed by both | mean word retention={mean_ret * 100:.1f}% | guard (<95%) triggered on {guard_hits} file(s)")

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "pdftotext_batch_s": round(t_txt, 2),
                    "poppler_batch_s": round(t_pop, 2),
                    "mean_word_retention": round(mean_ret, 4),
                    "guard_hits": guard_hits,
                    "files": rows,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
