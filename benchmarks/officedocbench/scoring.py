"""OfficeDocBench scoring — per-feature numerical evaluation.

Six metric categories:
1. Feature Detection Rate (weight 0.20) — binary per feature
2. Structural Recall (weight 0.25) — completeness of extraction
3. Structural Quality (weight 0.15) — heading levels, author attribution, list types
4. Text Jaccard (weight 0.15) — word-level overlap
5. Element Count Accuracy (weight 0.15) — count precision across all feature types
6. Metadata Accuracy (weight 0.10) — exact match on fields
"""

from __future__ import annotations

import re
from typing import Any


WEIGHTS = {
    "feature_detection": 0.20,
    "structural_recall": 0.25,
    "structural_quality": 0.15,
    "text_jaccard": 0.15,
    "element_count": 0.15,
    "metadata": 0.10,
}


def score_file(ground_truth: dict, adapter_output: dict) -> dict[str, Any]:
    """Score an adapter's output against ground truth for a single file.

    Returns per-metric scores and a composite score in [0, 1].
    """
    features = ground_truth.get("features", {})
    gt_words = set(ground_truth.get("full_text_words", []))

    detection = score_feature_detection(features, adapter_output)
    recall = score_structural_recall(features, adapter_output)
    quality = score_structural_quality(features, adapter_output)
    jaccard = score_text_jaccard(gt_words, adapter_output)
    counts = score_element_counts(features, adapter_output)
    meta = score_metadata(features.get("metadata"), adapter_output.get("metadata", {}))

    # Composite weighted score
    composite = (
        WEIGHTS["feature_detection"] * detection["score"]
        + WEIGHTS["structural_recall"] * recall["score"]
        + WEIGHTS["structural_quality"] * quality["score"]
        + WEIGHTS["text_jaccard"] * jaccard["score"]
        + WEIGHTS["element_count"] * counts["score"]
        + WEIGHTS["metadata"] * meta["score"]
    )

    return {
        "composite": round(composite, 4),
        "feature_detection": detection,
        "structural_recall": recall,
        "structural_quality": quality,
        "text_jaccard": jaccard,
        "element_count": counts,
        "metadata": meta,
    }


def score_feature_detection(features: dict, output: dict) -> dict[str, Any]:
    """Binary per-feature: did the parser detect each present feature?"""
    checks = {}
    total = 0
    detected = 0

    # Headings
    gt_h = features.get("headings")
    if isinstance(gt_h, dict) and gt_h.get("present"):
        total += 1
        found = len(output.get("headings", [])) > 0
        checks["headings"] = found
        if found:
            detected += 1

    # Tables
    gt_t = features.get("tables")
    if isinstance(gt_t, dict) and gt_t.get("present"):
        total += 1
        found = len(output.get("tables", [])) > 0
        checks["tables"] = found
        if found:
            detected += 1

    # Track changes
    gt_tc = features.get("track_changes")
    if isinstance(gt_tc, dict) and gt_tc.get("present"):
        total += 1
        found = len(output.get("track_changes", [])) > 0
        checks["track_changes"] = found
        if found:
            detected += 1

    # Comments
    gt_c = features.get("comments")
    if isinstance(gt_c, dict) and gt_c.get("present"):
        total += 1
        found = len(output.get("comments", [])) > 0
        checks["comments"] = found
        if found:
            detected += 1

    # Headers/footers
    gt_hf = features.get("headers_footers")
    if isinstance(gt_hf, dict) and gt_hf.get("present"):
        total += 1
        found = len(output.get("headers_footers", [])) > 0
        checks["headers_footers"] = found
        if found:
            detected += 1

    # Footnotes/endnotes
    gt_fn = features.get("footnotes_endnotes")
    if isinstance(gt_fn, dict) and gt_fn.get("present"):
        total += 1
        found = len(output.get("footnotes", [])) > 0
        checks["footnotes_endnotes"] = found
        if found:
            detected += 1

    # Speaker notes
    gt_sn = features.get("speaker_notes")
    if isinstance(gt_sn, dict) and gt_sn.get("present"):
        total += 1
        found = len(output.get("speaker_notes", [])) > 0
        checks["speaker_notes"] = found
        if found:
            detected += 1

    # Text boxes
    gt_tb = features.get("text_boxes")
    if isinstance(gt_tb, dict) and gt_tb.get("present"):
        total += 1
        found = len(output.get("text_boxes", [])) > 0
        checks["text_boxes"] = found
        if found:
            detected += 1

    # Images
    gt_img = features.get("images")
    if isinstance(gt_img, dict) and gt_img.get("present"):
        total += 1
        found = len(output.get("images", [])) > 0
        checks["images"] = found
        if found:
            detected += 1

    # Lists
    gt_l = features.get("lists")
    if isinstance(gt_l, dict) and gt_l.get("present"):
        total += 1
        found = len(output.get("lists", [])) > 0
        checks["lists"] = found
        if found:
            detected += 1

    # Sheets
    gt_sh = features.get("sheets")
    if isinstance(gt_sh, dict) and gt_sh.get("present"):
        total += 1
        found = len(output.get("metadata", {}).get("sheet_names", [])) > 0
        checks["sheets"] = found
        if found:
            detected += 1

    score = detected / total if total > 0 else 1.0

    return {
        "score": round(score, 4),
        "detected": detected,
        "total": total,
        "checks": checks,
    }


def score_structural_recall(features: dict, output: dict) -> dict[str, Any]:
    """How completely were present features extracted?"""
    scores = {}
    total = 0
    weighted_sum = 0.0

    # Table recall: correct count + merged cell detection
    gt_t = features.get("tables")
    if isinstance(gt_t, dict) and gt_t.get("present"):
        expected = gt_t["count"]
        actual = len(output.get("tables", []))
        count_score = min(actual, expected) / expected if expected > 0 else 1.0
        # Bonus: merged cell detection
        if gt_t.get("has_merged_cells"):
            has_merges = any(t.get("has_merged_cells", False) for t in output.get("tables", []))
            merge_score = 1.0 if has_merges else 0.0
            table_score = 0.7 * count_score + 0.3 * merge_score
        else:
            table_score = count_score
        scores["tables"] = round(table_score, 4)
        total += 1
        weighted_sum += table_score

    # Track changes recall: correct count + type match
    gt_tc = features.get("track_changes")
    if isinstance(gt_tc, dict) and gt_tc.get("present"):
        expected = gt_tc["count"]
        actual = len(output.get("track_changes", []))
        count_score = min(actual, expected) / expected if expected > 0 else 1.0
        # Check type distribution match
        gt_types = gt_tc.get("types", {})
        actual_types: dict[str, int] = {}
        for c in output.get("track_changes", []):
            ct = c.get("type", "unknown")
            actual_types[ct] = actual_types.get(ct, 0) + 1
        type_match = 1.0 if gt_types == actual_types else 0.5 if actual_types else 0.0
        tc_score = 0.6 * count_score + 0.4 * type_match
        scores["track_changes"] = round(tc_score, 4)
        total += 1
        weighted_sum += tc_score

    # Comment recall
    gt_c = features.get("comments")
    if isinstance(gt_c, dict) and gt_c.get("present"):
        expected = gt_c["count"]
        actual = len(output.get("comments", []))
        scores["comments"] = round(min(actual, expected) / expected if expected > 0 else 1.0, 4)
        total += 1
        weighted_sum += scores["comments"]

    # Heading recall
    gt_h = features.get("headings")
    if isinstance(gt_h, dict) and gt_h.get("present"):
        expected = gt_h["count"]
        actual = len(output.get("headings", []))
        scores["headings"] = round(min(actual, expected) / expected if expected > 0 else 1.0, 4)
        total += 1
        weighted_sum += scores["headings"]

    # Headers/footers recall
    gt_hf = features.get("headers_footers")
    if isinstance(gt_hf, dict) and gt_hf.get("present"):
        expected = gt_hf.get("header_count", 0) + gt_hf.get("footer_count", 0)
        actual = len(output.get("headers_footers", []))
        scores["headers_footers"] = round(min(actual, expected) / expected if expected > 0 else 1.0, 4)
        total += 1
        weighted_sum += scores["headers_footers"]

    # Images recall
    gt_img = features.get("images")
    if isinstance(gt_img, dict) and gt_img.get("present"):
        expected = gt_img["count"]
        actual = len(output.get("images", []))
        scores["images"] = round(min(actual, expected) / expected if expected > 0 else 1.0, 4)
        total += 1
        weighted_sum += scores["images"]

    score = weighted_sum / total if total > 0 else 1.0

    return {
        "score": round(score, 4),
        "per_feature": scores,
    }


def score_structural_quality(features: dict, output: dict) -> dict[str, Any]:
    """Qualitative accuracy of extracted structures beyond count/presence.

    Scores heading-level distribution, track-change author attribution,
    comment author/text matching, and list type accuracy.
    """
    scores: dict[str, Any] = {}
    total = 0
    weighted_sum = 0.0

    # ── Heading level distribution ─────────────────────────────────
    # Does the parser assign the correct heading levels?
    gt_h = features.get("headings")
    if isinstance(gt_h, dict) and gt_h.get("present"):
        by_level = gt_h.get("by_level", {})
        if by_level:
            # Build actual level distribution from output
            actual_by_level: dict[str, int] = {}
            for h in output.get("headings", []):
                lvl = str(h.get("level", 0))
                actual_by_level[lvl] = actual_by_level.get(lvl, 0) + 1

            # Score: per-level accuracy (how many levels match?)
            all_levels = set(by_level.keys()) | set(actual_by_level.keys())
            if all_levels:
                level_scores = []
                for lvl in all_levels:
                    expected = by_level.get(lvl, 0)
                    actual = actual_by_level.get(lvl, 0)
                    if expected > 0 or actual > 0:
                        acc = min(actual, expected) / max(actual, expected)
                        level_scores.append(acc)
                heading_level_score = sum(level_scores) / len(level_scores) if level_scores else 1.0
            else:
                heading_level_score = 1.0

            scores["heading_levels"] = {
                "score": round(heading_level_score, 4),
                "expected": by_level,
                "actual": actual_by_level,
            }
            total += 1
            weighted_sum += heading_level_score

    # ── Track change author attribution ────────────────────────────
    gt_tc = features.get("track_changes")
    if isinstance(gt_tc, dict) and gt_tc.get("present"):
        gt_authors = set(gt_tc.get("authors", []))
        if gt_authors:
            actual_authors = set()
            for tc in output.get("track_changes", []):
                author = tc.get("author", "")
                if author:
                    actual_authors.add(author)

            if gt_authors:
                matched = len(gt_authors & actual_authors)
                author_score = matched / len(gt_authors)
            else:
                author_score = 1.0

            scores["tc_authors"] = {
                "score": round(author_score, 4),
                "expected": sorted(gt_authors),
                "actual": sorted(actual_authors),
            }
            total += 1
            weighted_sum += author_score

    # ── Comment author + text matching ─────────────────────────────
    gt_c = features.get("comments")
    if isinstance(gt_c, dict) and gt_c.get("present"):
        sub_scores = []

        # Author matching
        gt_c_authors = set(gt_c.get("authors", []))
        if gt_c_authors:
            actual_c_authors = set()
            for c in output.get("comments", []):
                author = c.get("author", "")
                if author:
                    actual_c_authors.add(author)
            author_score = len(gt_c_authors & actual_c_authors) / len(gt_c_authors)
            sub_scores.append(author_score)
            scores["comment_authors"] = {
                "score": round(author_score, 4),
                "expected": sorted(gt_c_authors),
                "actual": sorted(actual_c_authors),
            }

        # Text matching (word-level overlap per comment)
        gt_c_texts = gt_c.get("texts", [])
        if gt_c_texts:
            actual_c_texts = [c.get("text", "") for c in output.get("comments", [])]
            # Flatten to word sets and compute Jaccard
            gt_words_c = set()
            for t in gt_c_texts:
                gt_words_c |= set(re.findall(r"\b[a-zA-Z0-9]+\b", t.lower()))
            actual_words_c = set()
            for t in actual_c_texts:
                actual_words_c |= set(re.findall(r"\b[a-zA-Z0-9]+\b", t.lower()))
            if gt_words_c:
                overlap = len(gt_words_c & actual_words_c) / len(gt_words_c)
                sub_scores.append(overlap)
                scores["comment_text"] = {
                    "score": round(overlap, 4),
                    "gt_words": len(gt_words_c),
                    "actual_words": len(actual_words_c),
                }

        if sub_scores:
            comment_quality = sum(sub_scores) / len(sub_scores)
            total += 1
            weighted_sum += comment_quality

    # ── List type accuracy ─────────────────────────────────────────
    # Does the parser correctly distinguish ordered vs unordered lists?
    gt_l = features.get("lists")
    if isinstance(gt_l, dict) and gt_l.get("present"):
        actual_lists = output.get("lists", [])
        if actual_lists:
            # Check if any list items exist with ordered/unordered distinction
            has_ordered = any(li.get("ordered", False) for li in actual_lists)
            has_unordered = any(not li.get("ordered", True) for li in actual_lists)
            # Count total items extracted
            total_items = sum(len(li.get("items", [])) for li in actual_lists)
            # Score based on item extraction richness
            expected_count = gt_l.get("count", 0)
            if expected_count > 0:
                list_score = min(len(actual_lists), expected_count) / expected_count
            else:
                list_score = 1.0 if actual_lists else 0.0

            scores["list_structure"] = {
                "score": round(list_score, 4),
                "has_ordered": has_ordered,
                "has_unordered": has_unordered,
                "total_items": total_items,
                "list_count_expected": expected_count,
                "list_count_actual": len(actual_lists),
            }
            total += 1
            weighted_sum += list_score
        else:
            # Lists expected but none extracted
            scores["list_structure"] = {"score": 0.0, "total_items": 0}
            total += 1

    # ── Table row accuracy ─────────────────────────────────────────
    gt_t = features.get("tables")
    if isinstance(gt_t, dict) and gt_t.get("present") and gt_t.get("total_rows", 0) > 0:
        expected_rows = gt_t["total_rows"]
        actual_rows = sum(t.get("row_count", 0) for t in output.get("tables", []))
        row_score = min(actual_rows, expected_rows) / max(actual_rows, expected_rows, 1)
        scores["table_rows"] = {
            "score": round(row_score, 4),
            "expected": expected_rows,
            "actual": actual_rows,
        }
        total += 1
        weighted_sum += row_score

    score = weighted_sum / total if total > 0 else 1.0

    return {
        "score": round(score, 4),
        "details": scores,
    }


def score_text_jaccard(gt_words: set[str], output: dict) -> dict[str, Any]:
    """Word-level Jaccard similarity between ground truth and adapter output."""
    # Collect all text from adapter output
    actual_words: set[str] = set()
    for el in output.get("text_elements", []):
        actual_words |= set(re.findall(r"\b[a-zA-Z0-9]+\b", el.get("text", "").lower()))
    for h in output.get("headings", []):
        actual_words |= set(re.findall(r"\b[a-zA-Z0-9]+\b", h.get("text", "").lower()))
    for t in output.get("tables", []):
        actual_words |= set(re.findall(r"\b[a-zA-Z0-9]+\b", t.get("cell_text", "").lower()))
    for tc in output.get("track_changes", []):
        actual_words |= set(re.findall(r"\b[a-zA-Z0-9]+\b", tc.get("text", "").lower()))
    for c in output.get("comments", []):
        actual_words |= set(re.findall(r"\b[a-zA-Z0-9]+\b", c.get("text", "").lower()))
    for hf in output.get("headers_footers", []):
        actual_words |= set(re.findall(r"\b[a-zA-Z0-9]+\b", hf.get("text", "").lower()))
    for tb in output.get("text_boxes", []):
        actual_words |= set(re.findall(r"\b[a-zA-Z0-9]+\b", tb.get("text", "").lower()))
    for li in output.get("lists", []):
        for item in li.get("items", []):
            actual_words |= set(re.findall(r"\b[a-zA-Z0-9]+\b", item.lower()))
    for fn in output.get("footnotes", []):
        actual_words |= set(re.findall(r"\b[a-zA-Z0-9]+\b", fn.get("text", "").lower()))
    for sn in output.get("speaker_notes", []):
        actual_words |= set(re.findall(r"\b[a-zA-Z0-9]+\b", sn.get("text", "").lower()))

    intersection = gt_words & actual_words
    union = gt_words | actual_words
    jaccard = len(intersection) / len(union) if union else 1.0

    return {
        "score": round(jaccard, 4),
        "gt_words": len(gt_words),
        "actual_words": len(actual_words),
        "shared": len(intersection),
    }


def score_element_counts(features: dict, output: dict) -> dict[str, Any]:
    """Per-element-type count accuracy: 1 - |actual - expected| / max(actual, expected, 1)."""
    checks = {}
    total = 0
    score_sum = 0.0

    mapping = [
        ("headings", "headings", "count"),
        ("tables", "tables", "count"),
        ("track_changes", "track_changes", "count"),
        ("comments", "comments", "count"),
        ("images", "images", "count"),
        ("lists", "lists", "count"),
        ("text_boxes", "text_boxes", "count"),
        ("footnotes_endnotes", "footnotes", "count"),
        ("speaker_notes", "speaker_notes", "count"),
    ]

    for gt_key, output_key, count_field in mapping:
        gt_feat = features.get(gt_key)
        if isinstance(gt_feat, dict) and gt_feat.get("present"):
            expected = gt_feat.get(count_field, 0)
            actual = len(output.get(output_key, []))
            acc = 1 - abs(actual - expected) / max(actual, expected, 1)
            checks[gt_key] = {"expected": expected, "actual": actual, "accuracy": round(acc, 4)}
            total += 1
            score_sum += acc

    score = score_sum / total if total > 0 else 1.0

    return {
        "score": round(score, 4),
        "checks": checks,
    }


def score_metadata(gt_meta: dict | None, output_meta: dict) -> dict[str, Any]:
    """Exact match scoring for metadata fields."""
    if gt_meta is None:
        return {"score": 1.0, "checks": {}}

    fields = ["title", "author", "created", "modified"]
    total = 0
    matched = 0
    checks = {}

    for field in fields:
        gt_val = gt_meta.get(field, "")
        if not gt_val:
            continue
        total += 1
        actual_val = output_meta.get(field, "")
        match = gt_val == actual_val
        checks[field] = {"expected": gt_val, "actual": actual_val, "match": match}
        if match:
            matched += 1

    score = matched / total if total > 0 else 1.0

    return {
        "score": round(score, 4),
        "matched": matched,
        "total": total,
        "checks": checks,
    }
