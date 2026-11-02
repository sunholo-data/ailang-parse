"""Unit tests for the PDF backend adapter (assets/pdf_backends/adapter.py).

Stdlib only, and no PDF engine needed: docling items and liteparse text items
are faked with SimpleNamespace, and the poppler backend is fed small inline
XML documents. All text is invented.

    python3 -m unittest tests/test_pdf_adapter.py
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

_ADAPTER = Path(__file__).resolve().parent.parent / "assets" / "pdf_backends" / "adapter.py"
_spec = importlib.util.spec_from_file_location("pdf_adapter", _ADAPTER)
adapter = importlib.util.module_from_spec(_spec)
sys.modules["pdf_adapter"] = adapter
_spec.loader.exec_module(adapter)


def label(v: str) -> NS:
    return NS(value=v)


def ditem(kind: str, text: str = "", page: int = 1, height: float = 0.0, **kw) -> NS:
    prov = [NS(page_no=page, bbox=NS(height=height))]
    return NS(label=label(kind), text=text, prov=prov, **kw)


def grid(*rows: list[str]) -> NS:
    return NS(grid=[[NS(text=c) for c in row] for row in rows])


class ProtocolHelpers(unittest.TestCase):
    def test_list_omits_flat_levels(self):
        self.assertEqual(adapter._list(["a", "b"], False, [0, 0]),
                         {"kind": "list", "items": ["a", "b"], "ordered": False})
        self.assertEqual(adapter._list(["a", "b"], True, [0, 1])["levels"], [0, 1])

    def test_placed_keeps_body_blocks_untagged(self):
        self.assertEqual(adapter._placed(adapter._text("x")), adapter._text("x"))
        tagged = adapter._placed(adapter._text("x"), 2, "footer")
        self.assertEqual((tagged["page"], tagged["region"]), (2, "footer"))

    def test_pdftotext_blocks_unchanged(self):
        text = "Title\n\nCol A    Col B\n1        2\n\fNext page\n"
        self.assertEqual(adapter._blocks_from_plaintext(text), [
            {"kind": "text", "text": "Title", "style": "Normal", "level": 0},
            {"kind": "text", "text": "Col A    Col B\n1        2", "style": "Normal", "level": 0},
            {"kind": "text", "text": "Next page", "style": "Normal", "level": 0},
        ])


class RankLevels(unittest.TestCase):
    def test_clusters_jitter_and_separates_tiers(self):
        self.assertEqual(adapter._rank_levels([27.0, 18.0, 17.8, 14.0, 13.7, 7.5]),
                         {27.0: 1, 18.0: 2, 17.8: 2, 14.0: 2, 13.7: 2, 7.5: 3})

    def test_caps_levels(self):
        self.assertEqual(adapter._rank_levels([40, 20, 10, 5], max_levels=3)[5], 3)

    def test_empty(self):
        self.assertEqual(adapter._rank_levels([]), {})


class DoclingWalk(unittest.TestCase):
    def items(self):
        return [
            (ditem("page_header", "ACME REPORT", 1), 1),
            (ditem("section_header", "Overview", 1, 27.0, level=1), 1),
            (ditem("text", "Body text.", 1), 1),
            (ditem("picture", "", 1), 1),
            (ditem("section_header", "Detail", 1, 17.0, level=1), 1),
            (NS(label=label("list"), text="", prov=[]), 1),
            (ditem("list_item", "first", 1, enumerated=True), 2),
            (ditem("list_item", "nested", 1, enumerated=True), 3),
            (ditem("list_item", "second", 1, enumerated=True), 2),
            (ditem("table", "", 2, data=grid(["Region", "Total"], ["North", "10"], ["", ""])), 1),
            (ditem("page_footer", "Acme Ltd · 1", 2), 1),
        ]

    def test_structure(self):
        blocks = adapter._docling_blocks(self.items())
        kinds = [(b["kind"], b.get("region", "body")) for b in blocks]
        self.assertEqual(kinds, [("text", "header"), ("heading", "body"), ("text", "body"),
                                 ("heading", "body"), ("list", "body"), ("table", "body"),
                                 ("text", "footer")])

    def test_flat_docling_levels_ranked_by_height(self):
        heads = [b for b in adapter._docling_blocks(self.items()) if b["kind"] == "heading"]
        self.assertEqual([(h["text"], h["level"]) for h in heads], [("Overview", 1), ("Detail", 2)])

    def test_real_docling_levels_kept(self):
        items = [(ditem("section_header", "A", 1, 10.0, level=1), 1),
                 (ditem("section_header", "B", 1, 30.0, level=2), 1)]
        heads = adapter._docling_blocks(items)
        self.assertEqual([h["level"] for h in heads], [1, 2])

    def test_list_grouped_with_levels(self):
        lst = next(b for b in adapter._docling_blocks(self.items()) if b["kind"] == "list")
        self.assertEqual((lst["items"], lst["ordered"], lst["levels"]),
                         (["first", "nested", "second"], True, [0, 1, 0]))

    def test_table_header_and_empty_rows(self):
        tbl = next(b for b in adapter._docling_blocks(self.items()) if b["kind"] == "table")
        self.assertEqual((tbl["headers"], tbl["rows"]), (["Region", "Total"], [["North", "10"]]))

    def test_never_emits_image_placeholder(self):
        blocks = adapter._docling_blocks(self.items())
        self.assertFalse(any("<!--" in (b.get("text") or "") for b in blocks))


class Liteparse(unittest.TestCase):
    def test_reads_both_field_spellings(self):
        new = NS(text_items=[NS(text="x", font_size=10)])
        old = NS(textItems=[NS(text="y", fontSize=12)])
        self.assertEqual([adapter._lp_size(i) for i in adapter._lp_items(new) + adapter._lp_items(old)],
                         [10.0, 12.0])

    def test_heading_levels_by_size_whole_lines_only(self):
        body = "a body line that is long enough to dominate the character count"
        items = [NS(text=body, font_size=10)] * 5 + [
            NS(text="Big", font_size=30), NS(text="Medium", font_size=20),
            NS(text="Logo", font_size=24)]
        levels = adapter._liteparse_heading_levels(items, {body, "Big", "Medium"})
        self.assertEqual(levels, {"Big": 1, "Medium": 2})


if __name__ == "__main__":
    unittest.main()
