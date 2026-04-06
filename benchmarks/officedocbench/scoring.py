"""OfficeDocBench scoring — per-feature numerical evaluation.

Seven metric categories:
1. Feature Detection Rate (weight 0.15) — binary per feature
2. Structural Recall (weight 0.20) — completeness of extraction
3. Structural Quality (weight 0.15) — heading levels, author attribution, list types
4. Content Fidelity (weight 0.15) — key phrases, paragraph structure, element ordering,
   hyperlinks, style preservation (aspirational: scores what GT data is available)
5. Text Jaccard (weight 0.10) — word-level overlap
6. Element Count Accuracy (weight 0.15) — count precision across all feature types
7. Metadata Accuracy (weight 0.10) — exact match on fields + sheet names
"""

from __future__ import annotations

import re
from typing import Any


WEIGHTS = {
    "feature_detection": 0.15,
    "structural_recall": 0.20,
    "structural_quality": 0.15,
    "content_fidelity": 0.15,
    "text_jaccard": 0.10,
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
    fidelity = score_content_fidelity(ground_truth, adapter_output)
    jaccard = score_text_jaccard(gt_words, adapter_output)
    counts = score_element_counts(features, adapter_output)
    meta = score_metadata(features.get("metadata"), adapter_output.get("metadata", {}),
                          features.get("sheets"))

    # Composite weighted score
    composite = (
        WEIGHTS["feature_detection"] * detection["score"]
        + WEIGHTS["structural_recall"] * recall["score"]
        + WEIGHTS["structural_quality"] * quality["score"]
        + WEIGHTS["content_fidelity"] * fidelity["score"]
        + WEIGHTS["text_jaccard"] * jaccard["score"]
        + WEIGHTS["element_count"] * counts["score"]
        + WEIGHTS["metadata"] * meta["score"]
    )

    return {
        "composite": round(composite, 4),
        "feature_detection": detection,
        "structural_recall": recall,
        "structural_quality": quality,
        "content_fidelity": fidelity,
        "text_jaccard": jaccard,
        "element_count": counts,
        "metadata": meta,
    }


def score_feature_detection(features: dict, output: dict) -> dict[str, Any]:
    """Binary per-feature: did the parser detect each present feature?"""
    checks = {}
    total = 0
    detected = 0

    feature_map = [
        ("headings", "headings"),
        ("tables", "tables"),
        ("track_changes", "track_changes"),
        ("comments", "comments"),
        ("headers_footers", "headers_footers"),
        ("footnotes_endnotes", "footnotes"),
        ("speaker_notes", "speaker_notes"),
        ("text_boxes", "text_boxes"),
        ("images", "images"),
        ("lists", "lists"),
    ]

    for gt_key, output_key in feature_map:
        gt_feat = features.get(gt_key)
        if isinstance(gt_feat, dict) and gt_feat.get("present"):
            total += 1
            found = len(output.get(output_key, [])) > 0
            checks[gt_key] = found
            if found:
                detected += 1

    # Sheets (special: check metadata.sheet_names)
    gt_sh = features.get("sheets")
    if isinstance(gt_sh, dict) and gt_sh.get("present"):
        total += 1
        found = len(output.get("metadata", {}).get("sheet_names", [])) > 0
        checks["sheets"] = found
        if found:
            detected += 1

    # Aspirational: hyperlinks
    gt_links = features.get("hyperlinks")
    if isinstance(gt_links, dict) and gt_links.get("present"):
        total += 1
        found = len(output.get("hyperlinks", [])) > 0
        checks["hyperlinks"] = found
        if found:
            detected += 1

    # Aspirational: styles
    gt_styles = features.get("styles")
    if isinstance(gt_styles, dict) and gt_styles.get("present"):
        total += 1
        found = any(
            el.get("bold") or el.get("italic") or el.get("formatting")
            for el in output.get("text_elements", [])
        )
        checks["styles"] = found
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
    comment author/text matching, list type accuracy, and table row accuracy.
    """
    scores: dict[str, Any] = {}
    total = 0
    weighted_sum = 0.0

    # ── Heading level distribution ─────────────────────────────────
    gt_h = features.get("headings")
    if isinstance(gt_h, dict) and gt_h.get("present"):
        by_level = gt_h.get("by_level", {})
        if by_level:
            actual_by_level: dict[str, int] = {}
            for h in output.get("headings", []):
                lvl = str(h.get("level", 0))
                actual_by_level[lvl] = actual_by_level.get(lvl, 0) + 1

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
            matched = len(gt_authors & actual_authors)
            author_score = matched / len(gt_authors)
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

        gt_c_texts = gt_c.get("texts", [])
        if gt_c_texts:
            actual_c_texts = [c.get("text", "") for c in output.get("comments", [])]
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
    gt_l = features.get("lists")
    if isinstance(gt_l, dict) and gt_l.get("present"):
        actual_lists = output.get("lists", [])
        if actual_lists:
            has_ordered = any(li.get("ordered", False) for li in actual_lists)
            has_unordered = any(not li.get("ordered", True) for li in actual_lists)
            total_items = sum(len(li.get("items", [])) for li in actual_lists)
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


def score_content_fidelity(ground_truth: dict, adapter_output: dict) -> dict[str, Any]:
    """Content-level accuracy beyond word overlap.

    Scores key phrase recall, paragraph count accuracy, element ordering,
    hyperlink extraction, and style preservation. Aspirational metrics
    score 0 when ground truth data is absent — they represent targets.
    """
    features = ground_truth.get("features", {})
    details: dict[str, Any] = {}
    total = 0
    weighted_sum = 0.0

    # ── Key Phrase Recall (Tier 1: GT exists in text.key_phrases) ──
    # Stricter than word Jaccard: tests multi-word phrase boundaries
    text_feat = features.get("text") or {}
    key_phrases = text_feat.get("key_phrases", [])
    if key_phrases:
        # Collect all text from adapter output as one blob for substring matching
        all_text = _collect_all_text(adapter_output).lower()
        matched = 0
        missed = []
        for phrase in key_phrases:
            # Normalize: lowercase, collapse whitespace
            normalized = " ".join(phrase.lower().split())
            if len(normalized) < 3:
                continue  # Skip trivially short phrases
            if normalized in all_text:
                matched += 1
            else:
                # Try word-level match (phrase words appear in sequence)
                phrase_words = re.findall(r"\b[a-zA-Z0-9]+\b", normalized)
                if len(phrase_words) >= 2:
                    # Check if all words appear in text
                    all_present = all(w in all_text for w in phrase_words)
                    if all_present:
                        matched += 0.5  # Partial credit: words present but not as phrase
                    else:
                        missed.append(normalized[:60])
                else:
                    missed.append(normalized[:60])

        phrase_count = len([p for p in key_phrases if len(" ".join(p.lower().split())) >= 3])
        phrase_score = matched / phrase_count if phrase_count > 0 else 1.0
        details["key_phrases"] = {
            "score": round(min(phrase_score, 1.0), 4),
            "matched": round(matched, 1),
            "total": phrase_count,
            "missed": missed[:5],  # Show first 5 missed phrases
        }
        total += 1
        weighted_sum += min(phrase_score, 1.0)

    # ── Paragraph Count Accuracy (Tier 1: GT exists in text.paragraph_count) ──
    paragraph_count = text_feat.get("paragraph_count", 0)
    if paragraph_count > 0:
        actual_paragraphs = len(adapter_output.get("text_elements", []))
        para_score = min(actual_paragraphs, paragraph_count) / max(actual_paragraphs, paragraph_count, 1)
        details["paragraph_count"] = {
            "score": round(para_score, 4),
            "expected": paragraph_count,
            "actual": actual_paragraphs,
        }
        total += 1
        weighted_sum += para_score

    # ── Element Ordering (Tier 2 aspirational: GT field = element_order) ──
    # When present, checks that extracted elements appear in document order
    gt_order = ground_truth.get("element_order", [])
    if gt_order:
        actual_order = _build_element_order(adapter_output)
        order_score = _score_ordering(gt_order, actual_order)
        details["element_ordering"] = {
            "score": round(order_score, 4),
            "gt_elements": len(gt_order),
            "actual_elements": len(actual_order),
        }
        total += 1
        weighted_sum += order_score

    # ── Hyperlink Extraction (Tier 2 aspirational: GT field = features.hyperlinks) ──
    gt_links = features.get("hyperlinks")
    if isinstance(gt_links, dict) and gt_links.get("present"):
        expected_links = gt_links.get("links", [])
        actual_links = adapter_output.get("hyperlinks", [])
        if expected_links:
            # Match by URL
            expected_urls = {l.get("url", "").lower() for l in expected_links if l.get("url")}
            actual_urls = {l.get("url", "").lower() for l in actual_links if l.get("url")}
            url_recall = len(expected_urls & actual_urls) / len(expected_urls) if expected_urls else 1.0

            # Match by anchor text
            expected_texts = {l.get("text", "").lower() for l in expected_links if l.get("text")}
            actual_texts = {l.get("text", "").lower() for l in actual_links if l.get("text")}
            text_recall = len(expected_texts & actual_texts) / len(expected_texts) if expected_texts else 1.0

            link_score = 0.6 * url_recall + 0.4 * text_recall
            details["hyperlinks"] = {
                "score": round(link_score, 4),
                "url_recall": round(url_recall, 4),
                "text_recall": round(text_recall, 4),
                "expected_count": len(expected_links),
                "actual_count": len(actual_links),
            }
            total += 1
            weighted_sum += link_score

    # ── Style/Formatting Preservation (Tier 2 aspirational: GT field = features.styles) ──
    gt_styles = features.get("styles")
    if isinstance(gt_styles, dict) and gt_styles.get("present"):
        expected_styled = gt_styles.get("styled_runs", [])
        if expected_styled:
            actual_elements = adapter_output.get("text_elements", [])
            # Check if any output elements carry formatting info
            has_any_formatting = any(
                el.get("bold") or el.get("italic") or el.get("formatting")
                for el in actual_elements
            )
            # Check specific style matches
            expected_bold = sum(1 for s in expected_styled if s.get("bold"))
            expected_italic = sum(1 for s in expected_styled if s.get("italic"))
            actual_bold = sum(1 for el in actual_elements if el.get("bold"))
            actual_italic = sum(1 for el in actual_elements if el.get("italic"))

            style_score = 0.0
            if has_any_formatting:
                bold_acc = min(actual_bold, expected_bold) / max(expected_bold, 1) if expected_bold else 1.0
                italic_acc = min(actual_italic, expected_italic) / max(expected_italic, 1) if expected_italic else 1.0
                style_score = (bold_acc + italic_acc) / 2
            details["style_preservation"] = {
                "score": round(style_score, 4),
                "has_formatting": has_any_formatting,
                "expected_bold": expected_bold,
                "expected_italic": expected_italic,
                "actual_bold": actual_bold,
                "actual_italic": actual_italic,
            }
            total += 1
            weighted_sum += style_score

    # ── Cell-Level Table Accuracy (Tier 2 aspirational: GT field = features.tables.cells) ──
    gt_t = features.get("tables")
    if isinstance(gt_t, dict) and gt_t.get("cells"):
        expected_cells = gt_t["cells"]  # [[row_idx, col_idx, text], ...]
        actual_tables = adapter_output.get("tables", [])
        # Flatten all actual cell text
        actual_cell_texts = set()
        for tbl in actual_tables:
            cell_text = tbl.get("cell_text", "")
            actual_cell_texts |= set(re.findall(r"\b[a-zA-Z0-9]+\b", cell_text.lower()))
        expected_cell_texts = set()
        for cell in expected_cells:
            if len(cell) >= 3:
                expected_cell_texts |= set(re.findall(r"\b[a-zA-Z0-9]+\b", str(cell[2]).lower()))

        if expected_cell_texts:
            cell_recall = len(expected_cell_texts & actual_cell_texts) / len(expected_cell_texts)
            details["cell_accuracy"] = {
                "score": round(cell_recall, 4),
                "expected_words": len(expected_cell_texts),
                "actual_words": len(actual_cell_texts),
            }
            total += 1
            weighted_sum += cell_recall

    score = weighted_sum / total if total > 0 else 1.0

    return {
        "score": round(score, 4),
        "dimensions_scored": total,
        "details": details,
    }


def _collect_all_text(output: dict) -> str:
    """Collect all extracted text from adapter output into a single string."""
    parts = []
    for el in output.get("text_elements", []):
        parts.append(el.get("text", ""))
    for h in output.get("headings", []):
        parts.append(h.get("text", ""))
    for t in output.get("tables", []):
        parts.append(t.get("cell_text", ""))
    for tc in output.get("track_changes", []):
        parts.append(tc.get("text", ""))
    for c in output.get("comments", []):
        parts.append(c.get("text", ""))
    for hf in output.get("headers_footers", []):
        parts.append(hf.get("text", ""))
    for tb in output.get("text_boxes", []):
        parts.append(tb.get("text", ""))
    for li in output.get("lists", []):
        for item in li.get("items", []):
            parts.append(item)
    for fn in output.get("footnotes", []):
        parts.append(fn.get("text", ""))
    for sn in output.get("speaker_notes", []):
        parts.append(sn.get("text", ""))
    return " ".join(parts)


def _build_element_order(output: dict) -> list[dict]:
    """Build an ordered list of elements from adapter output for ordering comparison."""
    elements = []
    for el in output.get("text_elements", []):
        elements.append({"type": "text", "text": el.get("text", "")[:50]})
    for h in output.get("headings", []):
        elements.append({"type": "heading", "text": h.get("text", "")[:50]})
    for t in output.get("tables", []):
        elements.append({"type": "table", "text": t.get("cell_text", "")[:50]})
    for li in output.get("lists", []):
        items_text = " ".join(li.get("items", []))
        elements.append({"type": "list", "text": items_text[:50]})
    return elements


def _score_ordering(gt_order: list[dict], actual_order: list[dict]) -> float:
    """Score element ordering using longest common subsequence ratio."""
    if not gt_order or not actual_order:
        return 0.0

    # Build simplified type sequences for LCS
    gt_types = [e.get("type", "") for e in gt_order]
    actual_types = [e.get("type", "") for e in actual_order]

    # LCS length
    m, n = len(gt_types), len(actual_types)
    # Use space-efficient LCS
    prev = [0] * (n + 1)
    curr = [0] * (n + 1)
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if gt_types[i - 1] == actual_types[j - 1]:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = max(prev[j], curr[j - 1])
        prev, curr = curr, [0] * (n + 1)

    lcs_len = prev[n]
    return lcs_len / max(m, n) if max(m, n) > 0 else 1.0


def score_text_jaccard(gt_words: set[str], output: dict) -> dict[str, Any]:
    """Word-level Jaccard similarity between ground truth and adapter output."""
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


def score_metadata(gt_meta: dict | None, output_meta: dict,
                   gt_sheets: dict | None = None) -> dict[str, Any]:
    """Exact match scoring for metadata fields + sheet name accuracy."""
    if gt_meta is None:
        gt_meta = {}

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

    # Sheet name accuracy (Tier 1: GT exists in sheets.names)
    if isinstance(gt_sheets, dict) and gt_sheets.get("names"):
        expected_names = set(gt_sheets["names"])
        actual_names = set(output_meta.get("sheet_names", []))
        total += 1
        name_match = expected_names == actual_names
        partial = len(expected_names & actual_names) / len(expected_names) if expected_names else 1.0
        checks["sheet_names"] = {
            "expected": sorted(expected_names),
            "actual": sorted(actual_names),
            "match": name_match,
            "partial_score": round(partial, 4),
        }
        if name_match:
            matched += 1
        else:
            matched += partial  # Partial credit for partial matches

    score = matched / total if total > 0 else 1.0

    return {
        "score": round(score, 4),
        "matched": round(matched, 2),
        "total": total,
        "checks": checks,
    }
