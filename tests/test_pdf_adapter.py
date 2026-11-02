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


# --- poppler -----------------------------------------------------------------

PAGE_W, PAGE_H, SCALE = 600.0, 800.0, 1.5


def poppler_xml(pages: list[list[tuple]]) -> tuple[str, str]:
    """Both poppler outputs for invented pages. Each line is
    (x0, y0, x1, y1, text, size, bold[, href]) in points; words are spread
    evenly across the line box. pdftohtml coordinates use its 1.5x scale."""
    bbox = ['<doc>']
    html = ['<?xml version="1.0"?><pdf2xml>']
    for pi, lines in enumerate(pages):
        bbox.append(f'<page width="{PAGE_W}" height="{PAGE_H}"><flow><block>')
        html.append(f'<page number="{pi + 1}" top="0" left="0" height="{PAGE_H * SCALE}" width="{PAGE_W * SCALE}">')
        fonts = {}
        for (x0, y0, x1, y1, text, size, bold, *rest) in lines:
            href = rest[0] if rest else ""
            words = text.split()
            step = (x1 - x0) / len(words)
            bbox.append(f'<line xMin="{x0}" yMin="{y0}" xMax="{x1}" yMax="{y1}">')
            for i, w in enumerate(words):
                bbox.append(f'<word xMin="{x0 + i * step}" yMin="{y0}" xMax="{x0 + (i + 1) * step - 2}" yMax="{y1}">{w}</word>')
            bbox.append('</line>')
            fid = fonts.setdefault((size, bold), str(len(fonts)))
            html.append(f'<fontspec id="{fid}" size="{size * SCALE}" family="{"Sans-Bold" if bold else "Sans"}" color="#000"/>')
            inner = f'<a href="{href}">{text}</a>' if href else text
            html.append(f'<text top="{y0 * SCALE}" left="{x0 * SCALE}" width="{(x1 - x0) * SCALE}" '
                        f'height="{(y1 - y0) * SCALE}" font="{fid}">{inner}</text>')
        bbox.append('</block></flow></page>')
        html.append('</page>')
    bbox.append('</doc>')
    html.append('</pdf2xml>')
    return "".join(bbox), "".join(html)


def page_body(n: int) -> list[tuple]:
    return [
        (50, 20, 200, 30, "ACME QUARTERLY", 8, False),            # running header
        (50, 60, 300, 84, f"Part {n} title", 20, True),
        (50, 100, 550, 112, "First line of a paragraph that runs the full width of", 10, False),
        (50, 114, 300, 126, "the column and then stops.", 10, False),
        (50, 140, 550, 152, "A second paragraph that also runs the full width of the", 10, False),
        (50, 154, 200, 166, "column here.", 10, False),
        (60, 180, 66, 190, "•", 10, False), (80, 180, 300, 192, "first point", 10, False),
        (60, 196, 66, 206, "•", 10, False), (80, 196, 300, 208, "second point", 10, False),
        (50, 230, 300, 244, "A subsection", 14, True),
        (60, 260, 120, 272, "Region", 10, True), (200, 260, 240, 272, "Q1", 10, True), (300, 260, 340, 272, "Q2", 10, True),
        (60, 280, 120, 292, "North", 10, False), (200, 280, 240, 292, "10", 10, False), (300, 280, 340, 292, "12", 10, False),
        (60, 300, 120, 312, "South", 10, False), (200, 300, 240, 312, "7", 10, False), (300, 300, 340, 312, "9", 10, False),
        (50, 330, 300, 342, "See the site for more.", 10, False, "https://acme.test"),
        (50, 760, 250, 770, "Acme Ltd · acme.test", 8, False),     # running footer
        (540, 760, 550, 770, str(n), 8, False),                   # page number
    ]


class Poppler(unittest.TestCase):
    def blocks(self, pages=None):
        bbox, html = poppler_xml(pages or [page_body(1), page_body(2)])
        blocks, count = adapter._poppler_blocks(bbox, html)
        return blocks, count

    def body(self):
        return [b for b in self.blocks()[0] if b.get("region", "body") == "body" and b.get("page") == 1]

    def test_page_count(self):
        self.assertEqual(self.blocks()[1], 2)

    def test_heading_levels_by_size(self):
        heads = [(b["text"], b["level"]) for b in self.body() if b["kind"] == "heading"]
        self.assertEqual(heads, [("Part 1 title", 1), ("A subsection", 2)])

    def test_paragraphs_reflowed_and_separated(self):
        texts = [b["text"] for b in self.body() if b["kind"] == "text"]
        self.assertEqual(texts[:2], [
            "First line of a paragraph that runs the full width of the column and then stops.",
            "A second paragraph that also runs the full width of the column here."])

    def test_bullet_list(self):
        lists = [b for b in self.body() if b["kind"] == "list"]
        self.assertEqual([(l["items"], l["ordered"]) for l in lists], [(["first point", "second point"], False)])

    def test_table_from_aligned_columns(self):
        tables = [b for b in self.body() if b["kind"] == "table"]
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0]["headers"], ["Region", "Q1", "Q2"])
        self.assertEqual(tables[0]["rows"], [["North", "10", "12"], ["South", "7", "9"]])

    def test_link_run(self):
        para = next(b for b in self.body() if b["kind"] == "text" and b["text"].startswith("See the site"))
        self.assertEqual({r.get("href") for r in para["runs"]}, {"https://acme.test"})

    def test_furniture_tagged_only_when_repeated(self):
        blocks = self.blocks()[0]
        tagged = sorted({(b["region"], b["text"]) for b in blocks if b.get("region")})
        self.assertEqual(tagged, [("footer", "1"), ("footer", "2"), ("footer", "Acme Ltd · acme.test"),
                                  ("header", "ACME QUARTERLY")])
        single = self.blocks([page_body(1)])[0]
        self.assertFalse(any(b.get("region") for b in single))

    def test_numbered_heading_is_not_a_list(self):
        page = [(50, 60, 70, 80, "1.", 16, True), (75, 60, 200, 80, "Overview", 16, True),
                (50, 100, 550, 112, "Body text at the body size, long enough to set it.", 10, False),
                (50, 114, 550, 126, "More body text at the body size so it dominates.", 10, False)]
        blocks = self.blocks([page])[0]
        self.assertEqual(blocks[0]["kind"], "heading")
        self.assertEqual(blocks[0]["text"], "1. Overview")

    def test_two_column_prose_is_not_a_table(self):
        left = "This is a long line of left column prose for the test"
        right = "and this is a long line of right column prose as well"
        page = [(50, 100 + i * 14, 290, 112 + i * 14, left, 10, False) for i in range(3)] + \
               [(310, 100 + i * 14, 550, 112 + i * 14, right, 10, False) for i in range(3)]
        blocks = self.blocks([page])[0]
        self.assertFalse(any(b["kind"] == "table" for b in blocks))

    def test_geometry_only_without_pdftohtml(self):
        bbox, _ = poppler_xml([page_body(1), page_body(2)])
        blocks, _ = adapter._poppler_blocks(bbox, None)
        self.assertTrue(any(b["kind"] == "heading" and b["text"] == "Part 1 title" for b in blocks))

    def test_key_matches_ailang_normalisation(self):
        # Mirrors pdfFurnitureKey's inline tests in pdf_furniture.ail.
        self.assertEqual(adapter._pp_key("Holosun ApS · CVR 44 324687 · ailang.sunholo.com"),
                         "holosun aps · cvr # · ailang.sunholo.com")
        self.assertEqual(adapter._pp_key("Page 3 of 12"), "page # of #")


if __name__ == "__main__":
    unittest.main()
