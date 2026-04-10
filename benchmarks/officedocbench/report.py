"""OfficeDocBench report generation — markdown, JSON, and LaTeX output."""

from __future__ import annotations

import statistics
from typing import Any


def _aggregate_scores(adapter_result: dict) -> dict[str, Any]:
    """Compute aggregate scores for an adapter."""
    ok_results = [r for r in adapter_result["results"] if r["status"] == "OK"]
    if not ok_results:
        return {"composite": 0, "count": 0, "feature_detection": 0,
                "structural_recall": 0, "structural_quality": 0,
                "content_fidelity": 0, "text_jaccard": 0,
                "element_count": 0, "metadata": 0}

    n = len(ok_results)

    def _avg(key: str) -> float:
        return sum(r["scores"].get(key, {}).get("score", 1.0) for r in ok_results) / n

    return {
        "composite": round(sum(r["scores"]["composite"] for r in ok_results) / n, 4),
        "count": n,
        "feature_detection": round(_avg("feature_detection"), 4),
        "structural_recall": round(_avg("structural_recall"), 4),
        "structural_quality": round(_avg("structural_quality"), 4),
        "content_fidelity": round(_avg("content_fidelity"), 4),
        "text_jaccard": round(_avg("text_jaccard"), 4),
        "element_count": round(_avg("element_count"), 4),
        "metadata": round(_avg("metadata"), 4),
    }


def _aggregate_by_format(adapter_result: dict) -> dict[str, dict]:
    """Compute scores grouped by format."""
    by_format: dict[str, list] = {}
    for r in adapter_result["results"]:
        fmt = r["format"]
        if r["status"] == "OK":
            by_format.setdefault(fmt, []).append(r)

    result = {}
    for fmt, results in sorted(by_format.items()):
        n = len(results)
        composite = sum(r["scores"]["composite"] for r in results) / n
        result[fmt] = {
            "composite": round(composite, 4),
            "count": n,
        }
    return result


def print_summary(all_results: list[dict]) -> None:
    """Print a comparative summary table."""
    print("\n# OfficeDocBench Results\n")
    print("| Tool | Files | Coverage | Composite | Adjusted | Feat. Det. | Struct. Recall | Struct. Quality | Content Fidelity | Text Jaccard | Elem. Count | Metadata |")
    print("|------|-------|----------|-----------|----------|------------|----------------|-----------------|------------------|--------------|-------------|----------|")

    for ar in all_results:
        agg = _aggregate_scores(ar)
        total = len(ar["results"])
        ok = agg["count"]
        unsupported = sum(1 for r in ar["results"] if r["status"] == "UNSUPPORTED")
        errors = sum(1 for r in ar["results"] if r["status"] == "ERROR")

        # Format coverage: fraction of benchmark files the adapter can handle
        coverage = ok / total if total > 0 else 0
        # Coverage-adjusted composite: penalizes tools that skip formats
        adjusted = agg["composite"] * coverage

        suffix = ""
        if unsupported:
            suffix += f" ({unsupported} unsup.)"
        if errors:
            suffix += f" ({errors} err)"

        print(
            f"| {ar['adapter']} "
            f"| {ok}/{total}{suffix} "
            f"| {coverage:.0%} "
            f"| **{agg['composite']:.1%}** "
            f"| {adjusted:.1%} "
            f"| {agg['feature_detection']:.1%} "
            f"| {agg['structural_recall']:.1%} "
            f"| {agg['structural_quality']:.1%} "
            f"| {agg['content_fidelity']:.1%} "
            f"| {agg['text_jaccard']:.1%} "
            f"| {agg['element_count']:.1%} "
            f"| {agg['metadata']:.1%} |"
        )

    print()


def print_timing(all_results: list[dict]) -> None:
    """Print a performance timing comparison table."""
    print("## Performance (Timing)\n")
    print("| Tool | Files | Median | Mean | Min | Max | Total |")
    print("|------|-------|--------|------|-----|-----|-------|")

    for ar in all_results:
        ok_results = [r for r in ar["results"] if r["status"] == "OK"]
        times = [r["time_ms"] for r in ok_results if "time_ms" in r]
        n = len(times)
        if not times:
            print(f"| {ar['adapter']} | {n} | — | — | — | — | — |")
            continue
        med = statistics.median(times)
        mean = statistics.mean(times)
        total = sum(times)

        def _fmt_time(ms: float) -> str:
            if ms >= 1000:
                return f"{ms/1000:.1f}s"
            return f"{ms:.1f}ms"

        print(
            f"| {ar['adapter']} "
            f"| {n} "
            f"| {_fmt_time(med)} "
            f"| {_fmt_time(mean)} "
            f"| {_fmt_time(min(times))} "
            f"| {_fmt_time(max(times))} "
            f"| {_fmt_time(total)} |"
        )

    print()

    # Per-file timing breakdown for largest files
    print("### Per-File Timing (top 10 slowest per tool)\n")
    for ar in all_results:
        ok_results = [r for r in ar["results"] if r["status"] == "OK" and "time_ms" in r]
        if not ok_results:
            continue
        ok_results.sort(key=lambda r: r["time_ms"], reverse=True)
        top = ok_results[:10]
        print(f"**{ar['adapter']}** v{ar.get('version', '?')}")
        print(f"| File | Time | Format |")
        print(f"|------|------|--------|")
        for r in top:
            t = r["time_ms"]
            tstr = f"{t/1000:.2f}s" if t >= 1000 else f"{t:.1f}ms"
            print(f"| {r['file']} | {tstr} | {r['format']} |")
        print()


def print_per_format(all_results: list[dict]) -> None:
    """Print per-format breakdown."""
    print("## Per-Format Breakdown\n")

    # Collect all formats
    all_formats = set()
    for ar in all_results:
        for r in ar["results"]:
            all_formats.add(r["format"])

    header = "| Format | " + " | ".join(ar["adapter"] for ar in all_results) + " |"
    separator = "|--------|" + "|".join("-------" for _ in all_results) + "|"
    print(header)
    print(separator)

    for fmt in sorted(all_formats):
        cells = []
        for ar in all_results:
            by_fmt = _aggregate_by_format(ar)
            if fmt in by_fmt:
                cells.append(f"{by_fmt[fmt]['composite']:.1%} ({by_fmt[fmt]['count']})")
            else:
                cells.append("—")
        print(f"| {fmt} | " + " | ".join(cells) + " |")

    print()


def print_feature_heatmap(all_results: list[dict]) -> None:
    """Print which features each tool detects."""
    print("## Feature Detection Heatmap\n")

    features = [
        "headings", "tables", "track_changes", "comments",
        "headers_footers", "footnotes_endnotes", "speaker_notes",
        "text_boxes", "images", "lists", "sheets",
        "hyperlinks", "styles", "equations", "bookmarks",
        "fields", "section_breaks",
    ]

    header = "| Feature | " + " | ".join(ar["adapter"] for ar in all_results) + " |"
    separator = "|---------|" + "|".join("-------" for _ in all_results) + "|"
    print(header)
    print(separator)

    for feat in features:
        cells = []
        for ar in all_results:
            ok_results = [r for r in ar["results"] if r["status"] == "OK"]
            detected = 0
            applicable = 0
            for r in ok_results:
                checks = r["scores"]["feature_detection"]["checks"]
                if feat in checks:
                    applicable += 1
                    if checks[feat]:
                        detected += 1
            if applicable > 0:
                cells.append(f"{detected}/{applicable}")
            else:
                cells.append("—")
        print(f"| {feat} | " + " | ".join(cells) + " |")

    print()


def print_latex(all_results: list[dict]) -> None:
    """Print a LaTeX table for paper inclusion."""
    print("% OfficeDocBench Results")
    print("\\begin{table}[h]")
    print("\\centering")
    print("\\caption{OfficeDocBench: Office structural parsing benchmark results}")
    print("\\label{tab:officedocbench}")

    n_tools = len(all_results)
    cols = "l" + "c" * n_tools
    print(f"\\begin{{tabular}}{{{cols}}}")
    print("\\toprule")

    headers = " & ".join(ar["adapter"] for ar in all_results)
    print(f"Metric & {headers} \\\\")
    print("\\midrule")

    metrics = [
        ("Composite", "composite"),
        ("Feature Detection", "feature_detection"),
        ("Structural Recall", "structural_recall"),
        ("Structural Quality", "structural_quality"),
        ("Content Fidelity", "content_fidelity"),
        ("Text Jaccard", "text_jaccard"),
        ("Element Count", "element_count"),
        ("Metadata", "metadata"),
    ]

    for label, key in metrics:
        cells = []
        for ar in all_results:
            agg = _aggregate_scores(ar)
            val = agg[key]
            # Bold the best score
            cells.append(f"{val:.1%}")
        print(f"{label} & " + " & ".join(cells) + " \\\\")

    print("\\bottomrule")
    print("\\end{tabular}")
    print("\\end{table}")
