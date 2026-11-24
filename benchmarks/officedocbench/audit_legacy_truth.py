"""Rebuild every scored legacy field from the source document.

The 69 original OfficeDocBench cases were first annotated from AILANG Parse's
own output (annotate.py / enrich_gt.py). This oracle replaces that: each
scored legacy value is recomputed from the input file by source_truth.py,
which shares no code or output with AILANG Parse. A value the source cannot
define without a parser convention is removed, so the scorer does not apply
it. ``legacy_verification`` on every case records the reader, the source
hash, which fields were recomputed and which are no longer scored.

    python audit_legacy_truth.py            # rebuild ground_truth/*.json
    python audit_legacy_truth.py --check    # CI: fail if any case differs
    python audit_legacy_truth.py --log F    # rebuild and write a change log
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path

from build_structure_truth import GT, ROOT
import source_truth

ORACLE = "audit_legacy_truth.py v2"

# Feature families each format's reader recomputes. Anything else is removed.
SCORED = {
    "docx": ["headings", "tables", "track_changes", "comments", "headers_footers",
             "footnotes_endnotes", "text_boxes", "images", "metadata"],
    "pptx": ["headings", "tables", "speaker_notes", "images", "metadata"],
    "xlsx": ["images", "metadata", "sheets"],
    "odt": ["headings", "tables", "track_changes", "headers_footers",
            "footnotes_endnotes", "text_boxes", "images", "lists", "metadata"],
    "odp": ["headings", "tables", "speaker_notes", "images", "metadata"],
    "ods": ["images", "metadata", "sheets"],
    "epub": ["headings", "tables", "images", "lists", "metadata"],
    "html": ["headings", "tables", "images", "lists", "metadata"],
    "md": ["headings", "tables", "images", "lists"],
    "csv": ["tables"],
    "tsv": ["tables"],
}

# Optional DOCX families: recomputed only on the cases that already carried
# them, so the rebuild does not widen any case's scope.
OPTIONAL = ["section_breaks", "bookmarks", "hyperlinks", "fields", "equations", "styles"]

# The families annotate.py gave each format (its FEATURE_MATRIX), i.e. the
# legacy scope. Families in this scope that SCORED omits are removed.
LEGACY_SCOPE = {
    "docx": {"headings", "tables", "track_changes", "comments", "headers_footers",
             "footnotes_endnotes", "text_boxes", "images", "lists", "metadata"},
    "pptx": {"headings", "tables", "speaker_notes", "text_boxes", "images", "lists", "metadata"},
    "xlsx": {"tables", "images", "metadata", "sheets"},
    "odt": {"headings", "tables", "track_changes", "headers_footers",
            "footnotes_endnotes", "text_boxes", "images", "lists", "metadata"},
    "odp": {"headings", "tables", "speaker_notes", "text_boxes", "images", "lists", "metadata"},
    "ods": {"tables", "images", "metadata", "sheets"},
    "epub": {"headings", "tables", "images", "lists", "metadata"},
    "html": {"headings", "tables", "images", "lists", "metadata"},
    "csv": {"tables"},
    "tsv": {"tables"},
    "md": {"headings", "tables", "images", "lists"},
}

BASE = ["headings", "tables", "track_changes", "comments", "headers_footers",
        "footnotes_endnotes", "speaker_notes", "text_boxes", "images", "lists",
        "metadata", "sheets"]

# Why a field is no longer scored. Written into each case's record.
REMOVED = {
    "text.paragraph_count": "counts a parser's paragraph segmentation (empty paragraphs, list items, cells), not a source quantity",
    "element_order": "a reading-order sequence in one parser's block granularity",
    "tables.total_rows": "'rows excluding header' is a parser convention",
    "lists:docx": "WordprocessingML has numbered paragraphs but no list container; list grouping is a parser convention (v2 list_items assertions cover levels)",
    "lists:pptx": "bullets are inherited from layouts/masters; which paragraphs form a list is a convention",
    "lists:odp": "slide outlines wrap each paragraph in its own text:list; the list count is not meaningful",
    "text_boxes:pptx": "every slide shape is a text frame; which are 'text boxes' is a convention",
    "text_boxes:odp": "every slide shape is a text frame; which are 'text boxes' is a convention",
    "tables:xlsx": "how many tables a worksheet holds is a parser convention (v2 table_cells assertions cover cells)",
    "tables:ods": "how many tables a worksheet holds is a parser convention",
    "equations": "OMML has no text form; every formula here uses layout (fractions, scripts, radicals) whose linear spelling is a convention",
    "styles": "counts a parser's run segmentation; v2 run assertions check explicit formatting instead",
}


def _present(count, **extra):
    return {"present": count > 0, "count": count, **extra}


def _heading_feature(headings):
    return {
        "present": bool(headings),
        "count": len(headings),
        "by_level": dict(sorted(Counter(str(level) for level, _ in headings).items())),
    }


def _features(facts, fmt, families):
    out = {}
    for name in families:
        if name == "headings":
            out[name] = _heading_feature(facts.headings)
        elif name == "tables":
            out[name] = {
                "present": facts.tables["count"] > 0,
                "count": facts.tables["count"],
                "has_merged_cells": facts.tables["has_merged_cells"],
            }
        elif name == "track_changes":
            changes = facts.track_changes
            out[name] = _present(
                len(changes),
                types=dict(sorted(Counter(c["type"] for c in changes).items())),
                authors=sorted({c["author"] for c in changes if c["author"]}),
            )
        elif name == "comments":
            value = _present(
                len(facts.comments),
                authors=sorted({c["author"] for c in facts.comments if c["author"]}),
                texts=[c["text"] for c in facts.comments],
            )
            if facts.comment_ranges:
                value["ranges"] = facts.comment_ranges
            out[name] = value
        elif name == "headers_footers":
            headers, footers = facts.headers_footers
            out[name] = {
                "present": headers + footers > 0,
                "header_count": headers,
                "footer_count": footers,
            }
        elif name == "footnotes_endnotes":
            value = _present(len(facts.notes))
            if facts.notes:
                value["texts"] = facts.notes
            out[name] = value
        elif name == "speaker_notes":
            out[name] = _present(len(facts.speaker_notes))
        elif name == "text_boxes":
            out[name] = _present(facts.text_boxes)
        elif name == "images":
            out[name] = _present(facts.images)
        elif name == "lists":
            lists = dict(facts.lists)
            out[name] = {"present": lists.pop("count") > 0, "count": facts.lists["count"], **lists}
        elif name == "metadata":
            out[name] = dict(facts.metadata)
        elif name == "sheets":
            out[name] = {"present": bool(facts.sheets), "names": facts.sheets}
        elif name == "section_breaks":
            out[name] = _present(facts.section_breaks)
        elif name == "bookmarks":
            out[name] = _present(len(facts.bookmarks), names=facts.bookmarks)
        elif name == "hyperlinks":
            out[name] = _present(len(facts.hyperlinks), links=facts.hyperlinks)
        elif name == "fields":
            out[name] = _present(
                len(facts.fields),
                display_texts=[f["display"] for f in facts.fields],
                field_types=[f["type"] for f in facts.fields],
            )
    return out


def legacy_cases():
    """Every corpus case that carries legacy (v1-era) fields."""
    names = json.loads((GT.parent / "corpus.json").read_text())["files"]
    return tuple(
        n
        for n in names
        if not json.loads((GT / (n + ".json")).read_text()).get("structure_only")
    )


CASES = legacy_cases()


def audited(source: Path, original: dict):
    fmt = original.get("format") or source.suffix[1:]
    facts = source_truth.read(source, fmt)
    gt = copy.deepcopy(original)
    gt.setdefault("file", source.name)
    gt["format"] = fmt
    old = gt.get("features", {})
    families = SCORED[fmt] + (
        [k for k in OPTIONAL if k in old and k not in ("equations", "styles")]
        if fmt == "docx"
        else []
    )
    recomputed = _features(facts, fmt, families)
    features = {}
    for name in BASE + [k for k in OPTIONAL if k in old]:
        features[name] = recomputed.get(name)
    removed = ["text.paragraph_count", "element_order"]
    removed += [name + ":" + fmt for name in sorted(LEGACY_SCOPE[fmt] - set(SCORED[fmt]))]
    if "tables" in SCORED[fmt]:
        removed.append("tables.total_rows")
    if "styles" in old:
        removed.append("styles")
    if "equations" in old:
        linear = [t for t in facts.equations if t is not None]
        if linear:
            features["equations"] = _present(len(linear), texts=linear)
        else:
            removed.append("equations")
    words = facts.words()
    phrases = [
        p
        for p in (old.get("text") or {}).get("key_phrases", [])
        if facts.contains_phrase(p)
    ]
    text = {"total_words": len(words)}
    if phrases:
        text["key_phrases"] = phrases
    gt["features"] = {"text": text, **features}
    gt["full_text_words"] = words
    gt.pop("element_order", None)
    gt.pop("notes", None)  # historical notes described the replaced annotation
    gt["verified"] = True

    if fmt in ("odt", "ods", "odp"):
        with zipfile.ZipFile(source) as z:
            if "styles.xml" not in z.namelist():
                gt["input_profile"] = "recovery"
                gt["input_note"] = (
                    "Hand-made minimal ODF package (mimetype, manifest, content.xml, "
                    "meta.xml; no styles.xml or settings.xml); tests recovery from a "
                    "minimal package as well as the content."
                )
            if fmt == "odt":
                body = source_truth.load(z, "content.xml").find(
                    "office:body/office:text", source_truth.NS
                )
                if not any(
                    source_truth.tokens(source_truth._odf_text(p))
                    for p in body.iter()
                    if p.tag in (source_truth.q("text:p"), source_truth.q("text:h"))
                ):
                    gt["allow_empty_output"] = True
    if fmt == "docx":
        with zipfile.ZipFile(source) as z:
            body = z.read("word/document.xml")
            refs = b"footnoteReference" in body or b"endnoteReference" in body
            if refs and not facts.notes:
                gt["input_profile"] = "recovery"
                gt["input_note"] = (
                    "References footnotes/endnotes but contains no note parts; "
                    "missing note text cannot be extracted."
                )

    fields = ["full_text_words", "features.text.total_words"]
    if phrases:
        fields.append("features.text.key_phrases (kept only where verbatim in one source paragraph)")
    fields += ["features." + k for k, v in features.items() if v is not None]
    gt["legacy_verification"] = {
        "method": (
            "Every scored legacy field recomputed from the source file by an "
            "independent reader; fields that depend on a parser's conventions "
            "are removed and not scored"
        ),
        "oracle": ORACLE,
        "reader": facts.reader,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "fields": fields,
        "not_scored": {k: REMOVED[k] for k in sorted(set(removed))},
    }
    return gt


def _diff(old, new, path=""):
    """Leaf-level differences, compact enough to publish as a change log."""
    if isinstance(old, dict) and isinstance(new, dict):
        out = []
        for key in sorted(set(old) | set(new)):
            out += _diff(old.get(key), new.get(key), f"{path}.{key}" if path else key)
        return out
    if old == new:
        return []
    if isinstance(old, list) and isinstance(new, list) and all(
        isinstance(x, str) for x in old + new
    ) and path.endswith(("full_text_words", "key_phrases")):
        return [{
            "field": path,
            "removed": sorted(set(old) - set(new)),
            "added": sorted(set(new) - set(old)),
        }]
    return [{"field": path, "old": old, "new": new}]


def main():
    check = "--check" in sys.argv
    log_path = sys.argv[sys.argv.index("--log") + 1] if "--log" in sys.argv else None
    bad, log = [], {}
    for name in CASES:
        sources = list((ROOT / "data/test_files").rglob(name))
        if len(sources) != 1:
            raise ValueError("Expected one source for " + name)
        dest = GT / (name + ".json")
        before = json.loads(dest.read_text())
        result = audited(sources[0], before)
        rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
        if check:
            if dest.read_text() != rendered:
                bad.append(name)
            continue
        changes = [
            d
            for d in _diff(before, result)
            if not d["field"].startswith("legacy_verification")
        ]
        if changes:
            log[name] = changes
        dest.write_text(rendered)
    if log_path:
        Path(log_path).write_text(json.dumps(log, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(CASES)} legacy annotations rebuilt from their sources")
    if bad:
        raise SystemExit("Legacy source truth needs updating: " + ", ".join(bad))


if __name__ == "__main__":
    main()
