"""PDF structure round trip: how much document structure each PDF backend
recovers, scored against the DOCX the PDF was made from.

For every source DOCX: render it to PDF with LibreOffice, parse the source
DOCX (ground truth) and the PDF (once per backend), and compare:

  headings   recall of the source's heading texts among PDF headings, and the
             share of those found at the same level
  tables     table count agreement, and cell-text F1 over all cells
  lists      recall of source list items among PDF list items
  furniture  source header/footer lines that leaked into the PDF's body
             (should be 0: they belong in header/footer sections)
  text       word Jaccard of body text (header/footer excluded both sides)

Sources are our own documents only: the proposal templates and DOCX test
fixtures in this repo. Never add a document from a bug report.

Usage:
    python3 benchmarks/pdf/structure_roundtrip.py
    python3 benchmarks/pdf/structure_roundtrip.py --backends pdftotext,poppler
    python3 benchmarks/pdf/structure_roundtrip.py --backends ai     # paid, opt-in
    python3 benchmarks/pdf/structure_roundtrip.py --json results.json

Needs soffice (LibreOffice) and poppler. Backends that are not installed are
reported as unavailable, not as zero.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
CLI = REPO / "bin" / "docparse"

DEFAULT_SOURCES = [
    "docs/templates/output/ailang-proposal.docx",
    "docs/templates/output/holosun-proposal.docx",
    "docs/templates/output/sunholo-proposal.docx",
    "data/test_files/sample.docx",
    "data/test_files/docx-hdrftr.docx",
    "data/test_files/tables.docx",
    "data/test_files/pandoc_table_list.docx",
    "data/test_files/merged_cells.docx",
    "data/test_files/inline_formatting.docx",
    "data/test_files/table_header_rowspan.docx",
]
DEFAULT_BACKENDS = ["pdftotext", "poppler", "docling", "liteparse"]


def norm(text: str) -> str:
    """Comparison form: lower case, curly quotes straightened, digit runs
    folded (so page numbers and '44 324687' compare equal), whitespace
    collapsed."""
    t = text.lower().replace("’", "'").replace("‘", "'")
    t = re.sub(r"\d[\d ]*\d|\d", "#", t)
    return " ".join(t.split())


def words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def collect(blocks: list[dict], out: dict, in_furniture: bool = False) -> dict:
    """Walk a parsed block tree into the structures we score."""
    for b in blocks:
        t = b.get("type")
        if t == "section":
            furniture = b.get("kind") in ("header", "footer")
            collect(b.get("blocks", []), out, in_furniture or furniture)
            continue
        if in_furniture:
            for line in (b.get("text") or "").splitlines():
                if line.strip():
                    out["furniture"].add(norm(line))
            continue
        if t == "heading":
            out["headings"].append((norm(b.get("text", "")), b.get("level", 0)))
            out["text"].append(b.get("text", ""))
        elif t == "table":
            cells = [c for row in [b.get("headers", [])] + b.get("rows", []) for c in row]
            raw = [c.get("text", "") if isinstance(c, dict) else str(c) for c in cells]
            out["tables"].append([norm(x) for x in raw if norm(x)])
            out["text"].extend(raw)
        elif t == "list":
            items = [norm(i) for i in b.get("items", [])]
            out["list_items"].extend(items)
            out["text"].extend(b.get("items", []))
        elif b.get("text"):
            out["paras"].append(norm(b["text"]))
            out["text"].append(b["text"])
    return out


def structure(json_path: Path) -> dict:
    doc = json.loads(json_path.read_text())
    blocks = doc.get("document", {}).get("blocks", [])
    return collect(blocks, {"headings": [], "tables": [], "list_items": [], "paras": [],
                            "furniture": set(), "text": []})


def f1(truth: list[str], got: list[str]) -> float | None:
    if not truth and not got:
        return None
    t, g = Counter(truth), Counter(got)
    hit = sum((t & g).values())
    if hit == 0:
        return 0.0
    p, r = hit / sum(g.values()), hit / sum(t.values())
    return 2 * p * r / (p + r)


def score(src: dict, pdf: dict) -> dict:
    src_heads = {h for h, _ in src["headings"] if h}
    pdf_heads = dict(pdf["headings"])
    found = [h for h in src_heads if h in pdf_heads]
    src_levels = dict(src["headings"])
    src_items = [i for i in src["list_items"] if i]
    pdf_items = set(pdf["list_items"])
    leaked = sum(1 for p in pdf["paras"] + [h for h, _ in pdf["headings"]] if p in src["furniture"])
    n_src_t, n_pdf_t = len(src["tables"]), len(pdf["tables"])
    sw, pw = words(" ".join(src["text"])), words(" ".join(pdf["text"]))
    return {
        "heading_recall": len(found) / len(src_heads) if src_heads else None,
        "heading_level": (sum(1 for h in found if pdf_heads[h] == src_levels[h]) / len(found)) if found else None,
        "table_count": (min(n_src_t, n_pdf_t) / max(n_src_t, n_pdf_t)) if (n_src_t or n_pdf_t) else None,
        "table_cells_f1": f1([c for t in src["tables"] for c in t], [c for t in pdf["tables"] for c in t]),
        "list_recall": (sum(1 for i in src_items if i in pdf_items) / len(src_items)) if src_items else None,
        "furniture_leak": leaked if src["furniture"] else None,
        "text_jaccard": (len(sw & pw) / len(sw | pw)) if (sw or pw) else None,
    }


def run_cli(files: list[Path], out_dir: Path, backend: str | None) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [str(CLI), *map(str, files), "--output-dir", str(out_dir)]
    if backend:
        cmd += ["--pdf-backend", backend]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    return proc.stdout + proc.stderr


METRICS = ["heading_recall", "heading_level", "table_count", "table_cells_f1",
           "list_recall", "furniture_leak", "text_jaccard"]


def fmt(v, metric: str) -> str:
    if v is None:
        return "—"
    return f"{v:.0f}" if metric == "furniture_leak" else f"{v * 100:.0f}%"


def mean(vals: list) -> float | None:
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--backends", default=",".join(DEFAULT_BACKENDS))
    ap.add_argument("--sources", nargs="*", default=DEFAULT_SOURCES)
    ap.add_argument("--json", help="write per-file results here")
    ap.add_argument("--per-file", action="store_true", help="print a row per source file")
    args = ap.parse_args()
    if not shutil.which("soffice"):
        print("soffice (LibreOffice) is required to render the PDFs", file=sys.stderr)
        return 2

    sources = [REPO / s for s in args.sources]
    backends = [b for b in args.backends.split(",") if b]
    with tempfile.TemporaryDirectory(prefix="pdf-roundtrip-") as tmp:
        work = Path(tmp)
        pdf_dir = work / "pdf"
        pdf_dir.mkdir()
        subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(pdf_dir),
                        *map(str, sources)], capture_output=True, text=True, timeout=600)
        pdfs = [pdf_dir / f"{s.stem}.pdf" for s in sources]
        missing = [p.name for p in pdfs if not p.exists()]
        if missing:
            print(f"LibreOffice did not render: {', '.join(missing)}", file=sys.stderr)
        pairs = [(s, p) for s, p in zip(sources, pdfs) if p.exists()]

        run_cli([s for s, _ in pairs], work / "src", None)
        truth = {s.stem: structure(work / "src" / f"{s.name}.json") for s, _ in pairs
                 if (work / "src" / f"{s.name}.json").exists()}

        results: dict[str, dict] = {}
        for backend in backends:
            log = run_cli([p for _, p in pairs], work / backend, backend)
            per_file = {}
            for s, p in pairs:
                out = work / backend / f"{p.name}.json"
                if s.stem in truth and out.exists():
                    per_file[s.stem] = score(truth[s.stem], structure(out))
            if not per_file:
                reason = "not installed" if "not installed" in log else "failed"
                results[backend] = {"unavailable": reason}
                continue
            results[backend] = {"files": per_file, "parsed": len(per_file), "total": len(pairs)}

    print(f"PDF structure round trip — {len(pairs)} source documents rendered by LibreOffice\n")
    print("| Backend | Parsed | " + " | ".join(m.replace("_", " ") for m in METRICS) + " |")
    print("|---|---|" + "---|" * len(METRICS))
    for backend in backends:
        r = results[backend]
        if "unavailable" in r:
            print(f"| {backend} | {r['unavailable']} |" + " |" * len(METRICS))
            continue
        cells = []
        for m in METRICS:
            vals = [f[m] for f in r["files"].values()]
            cells.append(fmt(sum(v for v in vals if v is not None) if m == "furniture_leak"
                             and any(v is not None for v in vals) else mean(vals), m))
        print(f"| {backend} | {r['parsed']}/{r['total']} | " + " | ".join(cells) + " |")
    print("\nfurniture leak = total header/footer lines found in body text (lower is better; 0 is right).")

    if args.per_file:
        for backend in backends:
            r = results[backend]
            if "files" not in r:
                continue
            print(f"\n{backend}")
            print("| File | " + " | ".join(m.replace("_", " ") for m in METRICS) + " |")
            print("|---|" + "---|" * len(METRICS))
            for name, f in r["files"].items():
                print(f"| {name} | " + " | ".join(fmt(f[m], m) for m in METRICS) + " |")
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
