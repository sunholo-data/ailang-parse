"""Source-verified structural assertions, shared by every provider.

Assertions are selective: a fixture may pin a blank cell or one styled phrase
without claiming to annotate every cell/run. Missing fields earn zero; no
positions, anchors, or formatting are inferred from the original input here.
"""

from __future__ import annotations

import re
from typing import Any

BENCHMARK_VERSION = "2.0.0"


def text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _same(expected: dict, actual: dict) -> bool:
    for key, value in expected.items():
        got = actual.get(key)
        if isinstance(value, str):
            if text(value) != text(got):
                return False
        elif got != value:
            return False
    return True


def score_structure(expected: dict, output: dict) -> dict:
    details = {}
    for kind, wants in expected.items():
        got = output.get("structure", {}).get(kind, [])
        if kind in ("containers", "element_order"):
            # Sequence alignment preserves identity as well as type. A
            # permutation of two paragraphs/sheets must lose credit.
            prev = [0] * (len(got) + 1)
            for want in wants:
                curr = [0]
                for j, item in enumerate(got):
                    curr.append(
                        prev[j] + 1 if _same(want, item) else max(prev[j + 1], curr[-1])
                    )
                prev = curr
            matched = prev[-1]
            score = 2 * matched / max(len(wants) + len(got), 1)
            if not wants and not got:
                score = 1.0
        else:
            # One-to-one matching prevents one repeated word/comment from
            # satisfying several independent expected records.
            free = [dict(item) for item in got]
            matched = 0
            for want in wants:

                def matches(item):
                    if kind == "runs":
                        return text(want.get("text", "")) in text(
                            item.get("text", "")
                        ) and _same(
                            {k: v for k, v in want.items() if k != "text"}, item
                        )
                    return _same(want, item)

                index = next((i for i, item in enumerate(free) if matches(item)), None)
                if index is not None:
                    matched += 1
                    if kind == "runs":
                        value = text(free[index].get("text", ""))
                        phrase = text(want.get("text", ""))
                        at = value.index(phrase)
                        free[index]["text"] = (
                            value[:at] + "\0" + value[at + len(phrase) :]
                        )
                    else:
                        free.pop(index)
            score = matched / len(wants) if wants else float(not got)
        details[kind] = {
            "score": round(score, 4),
            "matched": matched,
            "expected": len(wants),
            "actual": len(got),
        }
    return {
        "score": round(sum(d["score"] for d in details.values()) / len(details), 4)
        if details
        else 0.0,
        "applicable": bool(details),
        "details": details,
    }


def has_extracted_content(output: dict) -> bool:
    """A footer-only document or a blank slide deck is still a valid result."""
    buckets = (
        "text_elements",
        "headings",
        "tables",
        "lists",
        "images",
        "comments",
        "footnotes",
        "speaker_notes",
        "headers_footers",
        "text_boxes",
        "track_changes",
    )
    return any(output.get(k) for k in buckets) or any(
        output.get("structure", {}).values()
    )
