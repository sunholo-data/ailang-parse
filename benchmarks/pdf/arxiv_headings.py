"""arXiv headings: how many of a paper's section headings each PDF backend
finds, and how many of the headings it reports are real.

This is the hard counterpart to structure_roundtrip.py. That benchmark renders
our own styled DOCX files, where a heading is larger and bolder than the body.
Research papers are harder: two columns, numbered and small-caps headings,
math fonts, figures and floats in the reading order. It also reports
precision, which the round trip does not.

For every paper in data/test_files/arxiv that has both LaTeX source and a PDF:
parse the LaTeX with our own parser (ground truth), parse the PDF once per
backend, and compare heading texts.

  parsed     papers the backend returned a result for
  recall     truth headings found among the backend's headings
  precision  backend headings that are truth headings
  s/paper    wall time per paper, CLI start-up included

Matching ignores section numbers, case, spacing and punctuation, because a PDF
shows "3.1 Method" or small caps "I NTRODUCTION" where the source says "Method"
and "Introduction".

The truth is not exact, so read differences between backends, not absolute
values: the stored LaTeX can be another version than the PDF, class files add
headings the source never names ("Abstract", "References"), and a backend that
merges a heading with the next column's text gets no credit for it.

PDFs are not in the repo. Fetch them once (arXiv asks for 3 s between requests):

    python3 benchmarks/pdf/arxiv_headings.py --fetch

Usage:
    python3 benchmarks/pdf/arxiv_headings.py
    python3 benchmarks/pdf/arxiv_headings.py --backends poppler,docling --per-file
    python3 benchmarks/pdf/arxiv_headings.py --backends ai      # paid, opt-in
    python3 benchmarks/pdf/arxiv_headings.py --json results.json
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "arxivbench"))
import structure_roundtrip as sr  # noqa: E402
from eval_arxivbench import discover_papers  # noqa: E402

CORPUS = sr.REPO / "data" / "test_files" / "arxiv"
DEFAULT_BACKENDS = ["pdftotext", "poppler", "docling", "liteparse"]
USER_AGENT = "ailang-parse-benchmarks/0.1 (https://github.com/sunholo-data/ailang-parse)"
MIN_TRUTH = 3  # a paper with fewer source headings says nothing about recall

# Section numbering as it appears in a PDF, after sr.norm folded digits to '#':
# "#.#. ", "a.# ", "b. ", "a " (an appendix letter), "appendix a: ". A leading
# article "A" goes too, on both sides, so it costs nothing.
_NUMBERING = re.compile(r"^(?:#(?:\.#)*\.?\s+|[a-z](?:\.#)+\.?\s+|[a-z]\.?\s+|appendix\s+[a-z#]\.?:?\s*)")


def key(text: str) -> str:
    """Comparison key for a heading: numbering dropped, letters only."""
    n = sr.norm(text)
    for _ in range(2):
        n = _NUMBERING.sub("", n)
    return re.sub(r"[^a-z]", "", n)


def heading_keys(json_path: Path) -> set[str]:
    return {key(h) for h, _ in sr.structure(json_path)["headings"]} - {""}


def fetch_pdfs() -> int:
    """Download the PDF for every corpus paper that records its arXiv id."""
    fetched = 0
    for d in sorted(p for p in CORPUS.iterdir() if p.is_dir()):
        id_file = d / ".arxiv_id"
        if not id_file.exists() or list(d.glob("*.pdf")):
            continue
        arxiv_id = id_file.read_text().strip()
        req = urllib.request.Request(f"https://arxiv.org/pdf/{arxiv_id}", headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
        except OSError as e:
            print(f"  {d.name}: {e}", file=sys.stderr)
            continue
        if not data.startswith(b"%PDF"):
            print(f"  {d.name}: arXiv did not return a PDF", file=sys.stderr)
            continue
        (d / f"{d.name}.pdf").write_bytes(data)
        print(f"  {d.name}: {len(data) // 1024} KB")
        fetched += 1
        time.sleep(3)
    return fetched


def prf(hit: int, truth: int, claimed: int) -> tuple[float | None, float | None]:
    return (hit / truth if truth else None, hit / claimed if claimed else None)


def pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:.0f}%"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--backends", default=",".join(DEFAULT_BACKENDS))
    ap.add_argument("--papers", nargs="*", help="corpus directory names (default: all with a PDF)")
    ap.add_argument("--fetch", action="store_true", help="download missing PDFs from arXiv, then exit")
    ap.add_argument("--json", help="write per-file results here")
    ap.add_argument("--per-file", action="store_true", help="print a row per paper")
    args = ap.parse_args()
    if args.fetch:
        print(f"fetched {fetch_pdfs()} PDFs into {CORPUS}")
        return 0

    papers = [p for p in discover_papers(CORPUS, args.papers or None) if p["pdf_path"]]
    if not papers:
        print("No corpus paper has a PDF. Run with --fetch first.", file=sys.stderr)
        return 2
    backends = [b for b in args.backends.split(",") if b]

    with tempfile.TemporaryDirectory(prefix="pdf-arxiv-") as tmp:
        work = Path(tmp)
        # Stage under the paper's name: several corpus files are called main.tex.
        truth: dict[str, set[str]] = {}
        pdfs: dict[str, Path] = {}
        for p in papers:
            out = work / "tex" / p["name"]
            sr.run_cli([p["tex_path"]], out, None)
            parsed = sorted(out.glob("*.json"))
            keys = heading_keys(parsed[0]) if parsed else set()
            if len(keys) < MIN_TRUTH:
                continue
            truth[p["name"]] = keys
            pdfs[p["name"]] = work / "pdf" / f"{p['name']}.pdf"
            pdfs[p["name"]].parent.mkdir(exist_ok=True)
            shutil.copy(p["pdf_path"], pdfs[p["name"]])

        results: dict[str, dict] = {}
        for backend in backends:
            t0 = time.time()
            log = sr.run_cli(sorted(pdfs.values()), work / backend, backend)
            seconds = time.time() - t0
            per_file = {}
            for name, pdf in pdfs.items():
                out = work / backend / f"{pdf.name}.json"
                if not out.exists():
                    continue
                got = heading_keys(out)
                per_file[name] = {"truth": len(truth[name]), "claimed": len(got),
                                  "hit": len(got & truth[name])}
            if not per_file:
                results[backend] = {"unavailable": "not installed" if "not installed" in log else "failed"}
                continue
            results[backend] = {"files": per_file, "parsed": len(per_file), "total": len(pdfs),
                                "seconds_per_paper": seconds / len(pdfs)}

    print(f"arXiv headings — {len(pdfs)} papers, {sum(len(t) for t in truth.values())} source headings\n")
    print("| Backend | Parsed | heading recall | heading precision | s/paper |")
    print("|---|---|---|---|---|")
    for backend in backends:
        r = results[backend]
        if "unavailable" in r:
            print(f"| {backend} | {r['unavailable']} | | | |")
            continue
        # Recall is over every paper: one the backend failed on found nothing.
        hit = sum(f["hit"] for f in r["files"].values())
        claimed = sum(f["claimed"] for f in r["files"].values())
        total_truth = sum(len(t) for t in truth.values())
        rec, prec = prf(hit, total_truth, claimed)
        r["heading_recall"], r["heading_precision"] = rec, prec
        print(f"| {backend} | {r['parsed']}/{r['total']} | {hit}/{total_truth} = {pct(rec)} | "
              f"{hit}/{claimed} = {pct(prec)} | {r['seconds_per_paper']:.1f} |")
    print("\nRecall counts a paper the backend failed on as zero headings found.")

    if args.per_file:
        for backend in backends:
            r = results[backend]
            if "files" not in r:
                continue
            print(f"\n{backend}\n| Paper | source headings | found | reported |\n|---|---|---|---|")
            for name in pdfs:
                f = r["files"].get(name)
                print(f"| {name} | {len(truth[name])} | {f['hit'] if f else 'failed'} | {f['claimed'] if f else ''} |")
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
