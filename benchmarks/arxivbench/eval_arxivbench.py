#!/usr/bin/env python3
"""arxivbench — structural fidelity benchmark for scientific-paper parsers.

Given a corpus of arXiv paper directories (each containing a .tex source
and, optionally, a .pdf rendering), this harness:

  1. Extracts structural "truth" counts directly from the .tex source.
  2. Runs each configured adapter on its preferred input (.tex or .pdf).
  3. Scores adapter counts against truth per dimension (sections,
     equations, tables, citations, bibliography, lists, figures).
  4. Reports per-paper, per-adapter, and per-dimension coverage.

The whole point of the benchmark is the source-vs-OCR contrast, so
adapters that read .tex (AILANG, Pandoc) are compared on equal terms
while PDF-OCR baselines (Docling, LlamaParse, MarkItDown, Unstructured)
get scored on the same papers via the rendered .pdf.

Usage:
    uv run benchmarks/arxivbench/eval_arxivbench.py                   # AILANG only
    uv run benchmarks/arxivbench/eval_arxivbench.py --all             # all installed adapters
    uv run benchmarks/arxivbench/eval_arxivbench.py --adapter pandoc
    uv run benchmarks/arxivbench/eval_arxivbench.py --paper perelman_ricci
    uv run benchmarks/arxivbench/eval_arxivbench.py --json > results.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).parent
REPO_DIR = SCRIPT_DIR.parent.parent
CORPUS_DIR = REPO_DIR / "data" / "test_files" / "arxiv"
RESULTS_DIR = SCRIPT_DIR / "results"

# Load .env for API keys (LlamaParse)
_env_path = REPO_DIR / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())

sys.path.insert(0, str(SCRIPT_DIR))
from truth_extractor import extract_truth_from_file  # noqa: E402


DIMENSIONS = (
    "sections",
    "equations_display",
    "equations_inline",
    "tables",
    "figures",
    "citation_calls",
    "bibliography_entries",
    "lists",
    "theorems",
)


# Adapters keyed by CLI name. Lazy-loaded so unavailable deps don't crash.
def load_adapter(key: str):
    key = key.lower()
    if key in ("ailang", "docparse"):
        from adapters.docparse_adapter import DocParseAdapter
        return DocParseAdapter()
    if key == "pandoc":
        from adapters.pandoc_adapter import PandocAdapter
        return PandocAdapter()
    if key == "docling":
        from adapters.pdf_wrappers import DoclingAdapter
        return DoclingAdapter()
    if key == "llamaparse":
        from adapters.pdf_wrappers import LlamaParseAdapter
        return LlamaParseAdapter()
    if key == "markitdown":
        from adapters.pdf_wrappers import MarkItDownAdapter
        return MarkItDownAdapter()
    if key == "unstructured":
        from adapters.pdf_wrappers import UnstructuredAdapter
        return UnstructuredAdapter()
    if key == "liteparse":
        from adapters.pdf_wrappers import LiteParseAdapter
        return LiteParseAdapter()
    raise ValueError(f"unknown adapter: {key}")


ALL_ADAPTER_KEYS = ["ailang", "pandoc", "docling", "llamaparse", "markitdown", "unstructured", "liteparse"]


# --- Corpus discovery --------------------------------------------------------

def discover_papers(corpus_dir: Path, only: list[str] | None = None) -> list[dict[str, Any]]:
    """Return one entry per paper: {name, tex_path, pdf_path or None}.

    Multi-file corpora (devlin_bert, vaswani_attention) are currently
    skipped — the main .tex file alone under-represents them, and resolving
    \\input is deferred. Downstream: we'll reintroduce once \\input lands.
    """
    papers = []
    for d in sorted(corpus_dir.iterdir()):
        if not d.is_dir():
            continue
        if only and d.name not in only:
            continue

        # Pick the main .tex: prefer main.tex / <dirname>.tex / single-file dirs
        tex_files = sorted(d.glob("*.tex"))
        if not tex_files:
            continue
        if len(tex_files) == 1:
            main_tex = tex_files[0]
        else:
            # Try common names
            for candidate in ("main.tex", f"{d.name}.tex", "ms.tex", "paper.tex"):
                p = d / candidate
                if p.exists():
                    main_tex = p
                    break
            else:
                # Multi-file without a clear main.tex — skip for now
                # (these need \input resolution anyway).
                continue

        pdf = None
        pdfs = sorted(d.glob("*.pdf"))
        if pdfs:
            pdf = pdfs[0]

        papers.append({"name": d.name, "tex_path": main_tex, "pdf_path": pdf})
    return papers


# --- Scoring -----------------------------------------------------------------

def score(truth: dict[str, int], observed: dict[str, int]) -> dict[str, dict[str, Any]]:
    """Return per-dimension score. Score = min(observed, truth) / truth."""
    out = {}
    for dim in DIMENSIONS:
        t = truth.get(dim, 0)
        o = observed.get(dim, 0)
        if t == 0:
            # Nothing to preserve → 1.0 only if adapter also found nothing.
            # But inflating adapters that spuriously find things is undesirable,
            # so we treat "both zero" as not-scored (None) and "truth=0, obs>0"
            # as noise (score 0).
            if o == 0:
                pct = None
            else:
                pct = 0.0
        else:
            pct = min(o, t) / t
        out[dim] = {"truth": t, "observed": o, "score": pct}
    return out


# --- Main runner -------------------------------------------------------------

def run(adapters: list, papers: list[dict]) -> dict[str, Any]:
    results: dict[str, Any] = {
        "adapters": [{"key": a[0], "name": a[1].name(), "version": a[1].version(),
                      "input_kind": a[1].input_kind()} for a in adapters],
        "papers": [],
    }

    for paper in papers:
        truth = extract_truth_from_file(paper["tex_path"])
        paper_result = {
            "name": paper["name"],
            "tex_path": str(paper["tex_path"].relative_to(REPO_DIR)),
            "pdf_path": str(paper["pdf_path"].relative_to(REPO_DIR)) if paper["pdf_path"] else None,
            "truth": truth,
            "runs": {},
        }

        for key, adapter in adapters:
            inp = paper["tex_path"] if adapter.input_kind() == "tex" else paper["pdf_path"]
            if inp is None:
                paper_result["runs"][key] = {"status": "skipped", "reason": "no input file"}
                continue

            t0 = time.time()
            try:
                counts = adapter.parse(inp)
                elapsed = time.time() - t0
                scored = score(truth, counts)
                paper_result["runs"][key] = {
                    "status": "ok",
                    "elapsed_s": elapsed,
                    "counts": counts,
                    "scores": scored,
                }
            except Exception as e:
                paper_result["runs"][key] = {
                    "status": "error",
                    "elapsed_s": time.time() - t0,
                    "error": str(e)[:400],
                }

        results["papers"].append(paper_result)

    return results


# --- Reporting ---------------------------------------------------------------

def summarize(results: dict[str, Any]) -> dict[str, Any]:
    """Aggregate per-adapter per-dimension coverage across all papers."""
    out = {}
    for adapter_info in results["adapters"]:
        key = adapter_info["key"]
        agg: dict[str, dict[str, float]] = {d: {"sum": 0.0, "n": 0} for d in DIMENSIONS}
        papers_ok = 0
        papers_total = 0
        total_time = 0.0
        for paper in results["papers"]:
            run = paper["runs"].get(key, {})
            papers_total += 1
            if run.get("status") != "ok":
                continue
            papers_ok += 1
            total_time += run.get("elapsed_s", 0.0)
            for dim, s in run["scores"].items():
                if s["score"] is not None:
                    agg[dim]["sum"] += s["score"]
                    agg[dim]["n"] += 1
        dim_pct = {}
        for dim, v in agg.items():
            dim_pct[dim] = (v["sum"] / v["n"]) if v["n"] else None
        out[key] = {
            "name": adapter_info["name"],
            "version": adapter_info["version"],
            "input_kind": adapter_info["input_kind"],
            "papers_ok": papers_ok,
            "papers_total": papers_total,
            "total_time_s": total_time,
            "avg_time_s": total_time / papers_ok if papers_ok else 0.0,
            "coverage": dim_pct,
        }
    return out


def print_text_report(results: dict[str, Any]) -> None:
    summary = summarize(results)

    # Per-paper truth table
    print("\n=== Paper truth counts ===")
    header = ["paper", "sec", "eq_d", "eq_i", "tab", "fig", "cite", "bib", "list", "thm", "bytes"]
    print("  " + "  ".join(h.rjust(7) for h in header))
    for p in results["papers"]:
        t = p["truth"]
        row = [
            p["name"][:16].ljust(16),
            str(t["sections"]).rjust(5),
            str(t["equations_display"]).rjust(5),
            str(t["equations_inline"]).rjust(5),
            str(t["tables"]).rjust(5),
            str(t["figures"]).rjust(5),
            str(t["citation_calls"]).rjust(5),
            str(t["bibliography_entries"]).rjust(5),
            str(t["lists"]).rjust(5),
            str(t["theorems"]).rjust(5),
            f"{t['source_bytes']//1024}KB".rjust(7),
        ]
        print("  " + "  ".join(row))

    # Per-adapter coverage matrix
    print("\n=== Coverage (mean across papers where truth > 0) ===")
    header = ["adapter", "input", "papers", "sec", "eq_d", "eq_i", "tab", "fig", "cite", "bib", "list", "thm", "avg_s"]
    print("  " + "  ".join(h.ljust(8) for h in header))
    for key, s in summary.items():
        def pct(d):
            v = s["coverage"].get(d)
            return f"{v*100:.0f}%" if v is not None else "—"
        row = [
            s["name"][:14].ljust(14),
            s["input_kind"].ljust(5),
            f"{s['papers_ok']}/{s['papers_total']}".ljust(6),
            pct("sections").ljust(5),
            pct("equations_display").ljust(5),
            pct("equations_inline").ljust(5),
            pct("tables").ljust(5),
            pct("figures").ljust(5),
            pct("citation_calls").ljust(5),
            pct("bibliography_entries").ljust(5),
            pct("lists").ljust(5),
            pct("theorems").ljust(5),
            f"{s['avg_time_s']:.1f}".ljust(5),
        ]
        print("  " + "  ".join(row))

    # Errors
    errors = []
    for p in results["papers"]:
        for key, run in p["runs"].items():
            if run.get("status") == "error":
                errors.append((p["name"], key, run.get("error", "")))
    if errors:
        print("\n=== Errors ===")
        for name, key, msg in errors:
            print(f"  [{key}] {name}: {msg[:200]}")


# --- Entry point -------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", action="append",
                    help="adapter key (repeatable). Default: ailang. Use --all for everything installed.")
    ap.add_argument("--all", action="store_true",
                    help="run all adapters whose dependencies are available")
    ap.add_argument("--paper", action="append",
                    help="restrict to specific paper directory names (repeatable)")
    ap.add_argument("--exclude", action="append", default=[],
                    help="exclude paper directory names (repeatable)")
    ap.add_argument("--max-bytes", type=int, default=500_000,
                    help="skip papers whose .tex exceeds this size (default 500KB; set 0 for no limit)")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--out", type=Path, help="write JSON to this path")
    args = ap.parse_args()

    # Determine adapters
    if args.all:
        keys = ALL_ADAPTER_KEYS
    elif args.adapter:
        keys = args.adapter
    else:
        keys = ["ailang"]

    adapters = []
    for k in keys:
        try:
            adapters.append((k, load_adapter(k)))
        except Exception as e:
            print(f"  [skip] adapter {k}: {e}", file=sys.stderr)

    if not adapters:
        print("No adapters available.", file=sys.stderr)
        sys.exit(2)

    papers = discover_papers(CORPUS_DIR, only=args.paper)
    if args.exclude:
        papers = [p for p in papers if p["name"] not in args.exclude]
    if args.max_bytes:
        papers = [p for p in papers if p["tex_path"].stat().st_size <= args.max_bytes]
    if not papers:
        print(f"No papers found under {CORPUS_DIR}", file=sys.stderr)
        sys.exit(2)

    print(f"arxivbench: {len(adapters)} adapter(s), {len(papers)} paper(s)", file=sys.stderr)
    results = run(adapters, papers)

    RESULTS_DIR.mkdir(exist_ok=True)
    default_out = RESULTS_DIR / "latest.json"
    (args.out or default_out).write_text(json.dumps(results, indent=2, default=str))

    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        print_text_report(results)


if __name__ == "__main__":
    main()
