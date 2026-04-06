"""OfficeDocBench report generation — markdown, JSON, and LaTeX output."""

from __future__ import annotations

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
    print("| Tool | Files | Composite | Feat. Det. | Struct. Recall | Struct. Quality | Content Fidelity | Text Jaccard | Elem. Count | Metadata |")
    print("|------|-------|-----------|------------|----------------|-----------------|------------------|--------------|-------------|----------|")

    for ar in all_results:
        agg = _aggregate_scores(ar)
        unsupported = sum(1 for r in ar["results"] if r["status"] == "UNSUPPORTED")
        errors = sum(1 for r in ar["results"] if r["status"] == "ERROR")

        suffix = ""
        if unsupported:
            suffix += f" ({unsupported} unsupported)"
        if errors:
            suffix += f" ({errors} errors)"

        print(
            f"| {ar['adapter']} "
            f"| {agg['count']}{suffix} "
            f"| **{agg['composite']:.1%}** "
            f"| {agg['feature_detection']:.1%} "
            f"| {agg['structural_recall']:.1%} "
            f"| {agg['structural_quality']:.1%} "
            f"| {agg['content_fidelity']:.1%} "
            f"| {agg['text_jaccard']:.1%} "
            f"| {agg['element_count']:.1%} "
            f"| {agg['metadata']:.1%} |"
        )

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
