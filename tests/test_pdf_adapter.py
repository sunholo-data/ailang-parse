"""Unit tests for the PDF backend adapter (assets/pdf_backends/adapter.py).

Stdlib only, and no PDF engine needed: docling items and liteparse text items
are faked with SimpleNamespace, and the poppler backend is fed small inline
XML documents. All text is invented.

    python3 -m unittest tests/test_pdf_adapter.py
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
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


def poppler_xml(pages: list[list[tuple]], images: dict | None = None) -> tuple[str, str]:
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
        for (x0, y0, x1, y1, src) in (images or {}).get(pi, []):
            html.append(f'<image top="{y0 * SCALE}" left="{x0 * SCALE}" width="{(x1 - x0) * SCALE}" '
                        f'height="{(y1 - y0) * SCALE}" src="{src}"/>')
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

    def test_control_characters_do_not_fail_the_parse(self):
        # poppler copies control codes through from fonts that map glyphs to
        # them (LaTeX math), raw and as numeric references. XML 1.0 forbids
        # both, and one used to make the whole document unparseable.
        bbox, html = poppler_xml([page_body(1), page_body(2)])
        for bad in ("\x02", "\x0c", "&#1;", "&#x1F;", "&#031;", "\ufffe"):
            dirty_bbox = bbox.replace("stops.", "stops." + bad)
            dirty_html = html.replace("stops.", "stops." + bad)
            self.assertNotEqual(dirty_bbox, bbox)
            blocks, count = adapter._poppler_blocks(dirty_bbox, dirty_html)
            self.assertEqual(count, 2)
            self.assertEqual(blocks, adapter._poppler_blocks(bbox, html)[0])

    def test_legal_references_are_kept(self):
        self.assertEqual(adapter._pp_xml_clean("a&#9;b&#10;c&#13;d&#32;e&#x41;f&#100;g&amp;h\ti"),
                         "a&#9;b&#10;c&#13;d&#32;e&#x41;f&#100;g&amp;h\ti")

    # --- papers: two columns, numbered and small-caps headings, outlines ---

    BODY_L = "left column prose that fills the whole width of its column"
    BODY_R = "right column prose that fills the whole width of its column"

    def two_columns(self, left_extra=(), right_extra=()):
        """A two-column page: ten lines of prose a side from y=200, with
        `left_extra` / `right_extra` lines placed above them in a column."""
        page = [(50, 200 + i * 14, 290, 210 + i * 14, self.BODY_L, 10, False) for i in range(10)] + \
               [(310, 200 + i * 14, 550, 210 + i * 14, self.BODY_R, 10, False) for i in range(10)]
        return list(left_extra) + list(right_extra) + page

    def test_heading_in_one_column_of_two(self):
        # Level with the right column's text: read by whole-page rows it was
        # one row with that text, and not a heading.
        page = self.two_columns(left_extra=[(50, 172, 150, 186, "Method", 14, True)],
                                right_extra=[(310, 172, 550, 182, self.BODY_R, 10, False)])
        blocks = self.blocks([page])[0]
        self.assertEqual([b["text"] for b in blocks if b["kind"] == "heading"], ["Method"])
        self.assertFalse(any(b["kind"] == "table" for b in blocks))

    def test_columns_are_read_left_then_right(self):
        blocks = self.blocks([self.two_columns()])[0]
        texts = [b["text"] for b in blocks if b["kind"] == "text"]
        self.assertEqual(len(texts), 2)
        self.assertTrue(texts[0].startswith("left column") and "right" not in texts[0])
        self.assertTrue(texts[1].startswith("right column") and "left" not in texts[1])

    def test_line_across_both_columns_comes_first(self):
        page = self.two_columns(left_extra=[(50, 60, 550, 84, "A title across the whole page", 20, True)])
        blocks = self.blocks([page])[0]
        self.assertEqual((blocks[0]["kind"], blocks[0]["text"]), ("heading", "A title across the whole page"))

    def test_table_is_not_split_into_columns(self):
        rows = [(60, 100 + i * 14, f"Region {i}", f"{i}0") for i in range(12)]
        page = [(x, y, x + 60, y + 10, a, 10, False) for (x, y, a, _) in rows] + \
               [(400, y, 430, y + 10, b, 10, False) for (_, y, _, b) in rows]
        blocks = self.blocks([page])[0]
        self.assertEqual([b["kind"] for b in blocks], ["table"])

    def numbered(self, number, title, bold, gap=30):
        body = "Body text at the body size, long enough to fill the line fully."
        return [(50, 100, 550, 110, body, 10, False), (50, 112, 550, 122, body, 10, False),
                (50, 122 + gap, 50 + 8 * len(number), 132 + gap, number, 10, bold),
                (50 + 8 * len(number) + 6, 122 + gap, 300, 132 + gap, title, 10, bold),
                (50, 140 + gap, 550, 150 + gap, body, 10, False), (50, 152 + gap, 550, 162 + gap, body, 10, False)]

    def headings(self, page):
        return [(b["text"], b["level"]) for b in self.blocks([page])[0] if b["kind"] == "heading"]

    def test_numbered_heading_at_body_size(self):
        self.assertEqual(self.headings(self.numbered("3.2", "Causal Convolutions", True)),
                         [("3.2 Causal Convolutions", 3)])
        self.assertEqual(self.headings(self.numbered("1", "INTRODUCTION", False)), [("1 INTRODUCTION", 2)])
        # Not bold, not capitals: a multi-level number standing apart is enough.
        self.assertEqual(self.headings(self.numbered("3.2", "Causal Convolutions", False)),
                         [("3.2 Causal Convolutions", 3)])

    def test_numbered_text_that_is_not_a_heading(self):
        self.assertEqual(self.headings(self.numbered("1", "Introduction", False)), [])       # a list item
        self.assertEqual(self.headings(self.numbered("3.2", "Causal Convolutions", False, gap=2)), [])
        self.assertEqual(self.headings(self.numbered("3.2", "we then define the loss", True)), [])
        self.assertEqual(self.headings(self.numbered("2", "0.75 0.81 0.90", True)), [])       # a table row

    def test_small_caps_are_rejoined(self):
        words = [{"x0": 10.0, "y0": 0.0, "x1": 14.0, "y1": 10.0, "text": "I"},
                 {"x0": 14.5, "y0": 2.0, "x1": 80.0, "y1": 10.0, "text": "NTRODUCTION"},
                 {"x0": 84.0, "y0": 0.0, "x1": 88.0, "y1": 10.0, "text": "A"},
                 {"x0": 92.0, "y0": 0.0, "x1": 120.0, "y1": 10.0, "text": "WORD"}]
        self.assertEqual([w["text"] for w in adapter._pp_join_small_caps(words)], ["INTRODUCTION", "A", "WORD"])

    def test_tex_bold_fonts(self):
        for family in ("WMCLTX+CMBX10", "MBSETQ+NimbusRomNo9L-Medi", "Arial-BoldMT", "Helvetica-Bd"):
            self.assertTrue(adapter._PP_BOLD_FAMILY.search(family.lower()), family)
        for family in ("DGPCYE+CMR10", "ULKTDC+NimbusRomNo9L-Regu", "Roboto-Medium", "CMMI9"):
            self.assertFalse(adapter._PP_BOLD_FAMILY.search(family.lower()), family)

    def with_outline(self, pages, outline):
        bbox, html = poppler_xml(pages)
        return adapter._poppler_blocks(bbox, html.replace("</pdf2xml>", outline + "</pdf2xml>"))[0]

    def test_outline_names_headings_and_levels(self):
        # Body-size, not bold: only the PDF's outline says these are headings.
        body = "Body text at the body size, long enough to fill the line fully."
        page = [(50, 100, 200, 110, "1 Overview", 10, False), (50, 114, 550, 124, body, 10, False),
                (50, 128, 550, 138, body, 10, False), (50, 150, 200, 160, "2 Scope", 10, False),
                (50, 164, 550, 174, body, 10, False), (50, 178, 550, 188, body, 10, False)]
        outline = '<outline><item page="1">1 Overview</item><outline><item page="1">Scope</item></outline></outline>'
        blocks = self.with_outline([page], outline)
        self.assertEqual([(b["text"], b["level"]) for b in blocks if b["kind"] == "heading"],
                         [("1 Overview", 1), ("2 Scope", 2)])
        # The same lines on another page are not headings.
        blocks = self.with_outline([page], outline.replace('page="1"', 'page="2"'))
        self.assertFalse(any(b["kind"] == "heading" for b in blocks))

    def test_outline_entry_wrapped_over_two_lines(self):
        body = "Body text at the body size, long enough to fill the line fully."
        page = [(50, 100, 300, 110, "2 Towards Reducing Internal", 10, False),
                (50, 112, 200, 122, "Covariate Shift", 10, False),
                (50, 140, 550, 150, body, 10, False), (50, 154, 550, 164, body, 10, False)]
        outline = '<outline><item page="1">2 Towards Reducing Internal Covariate Shift</item></outline>'
        blocks = self.with_outline([page], outline)
        self.assertEqual([b["text"] for b in blocks if b["kind"] == "heading"],
                         ["2 Towards Reducing Internal Covariate Shift"])
        self.assertFalse(any("Covariate Shift" == b.get("text") for b in blocks))

    def test_wrapped_heading_is_one_heading(self):
        body = "Body text at the body size, long enough to fill the line fully."
        page = [(50, 60, 400, 80, "A long heading that wraps", 18, True), (50, 82, 250, 102, "onto a second line", 18, True),
                (50, 130, 550, 140, body, 10, False), (50, 144, 550, 154, body, 10, False)]
        self.assertEqual([h for h, _ in self.headings(page)], ["A long heading that wraps onto a second line"])

    def test_formula_and_email_are_not_headings(self):
        body = "Body text at the body size, long enough to fill the line fully."
        page = [(50, 60, 70, 90, "Z", 24, False), (50, 100, 300, 116, "ann@example.test", 14, False),
                (50, 130, 550, 140, body, 10, False), (50, 144, 550, 154, body, 10, False)]
        self.assertEqual(self.headings(page), [])

    def test_sideways_margin_text_is_not_a_heading(self):
        body = "Body text at the body size, long enough to fill the line fully."
        page = [(10, 200, 30, 560, "arXiv:0000.00000v1 [cs.XX] 1 Jan 2000", 20, False),
                (50, 130, 550, 140, body, 10, False), (50, 144, 550, 154, body, 10, False)]
        self.assertEqual(self.headings(page), [])

    def test_first_line_indent_stays_in_its_paragraph(self):
        page = [(64, 100, 550, 110, "An indented first line that runs to the right edge of", 10, False),
                (50, 112, 550, 122, "the column and continues on the second line all the way", 10, False),
                (50, 124, 300, 134, "and then stops.", 10, False)]
        texts = [b["text"] for b in self.blocks([page])[0] if b["kind"] == "text"]
        self.assertEqual(len(texts), 1)

    def test_geometry_only_without_pdftohtml(self):
        bbox, _ = poppler_xml([page_body(1), page_body(2)])
        blocks, _ = adapter._poppler_blocks(bbox, None)
        self.assertTrue(any(b["kind"] == "heading" and b["text"] == "Part 1 title" for b in blocks))

    def test_stacked_tables_split_on_column_change(self):
        rows = [(60, 100, "Name", "Game", "Fame"), (60, 114, "Ann", "Chess", "High"),
                (60, 128, "Bob", "Go", "Low")]
        page = [(x, y, x + 50, y + 12, a, 10, False) for (x, y, a, _, _) in rows] + \
               [(200, y, 250, y + 12, b, 10, False) for (_, y, _, b, _) in rows] + \
               [(340, y, 390, y + 12, c, 10, False) for (_, y, _, _, c) in rows] + \
               [(60, 150, 110, 162, "Left", 10, False), (270, 150, 320, 162, "Right", 10, False),
                (60, 164, 110, 176, "Up", 10, False), (270, 164, 320, 176, "Down", 10, False)]
        tables = [b for b in self.blocks([page])[0] if b["kind"] == "table"]
        self.assertEqual([t["headers"] for t in tables], [["Name", "Game", "Fame"], ["Left", "Right"]])

    def test_wrapped_cell_folds_back_and_margin_text_does_not(self):
        page = [(60, 100, 110, 112, "Item", 10, True), (200, 100, 260, 112, "Detail", 10, True),
                (60, 114, 110, 126, "Alpha", 10, False), (200, 114, 380, 126, "first half of a", 10, False),
                (200, 127, 300, 139, "wrapped cell", 10, False),
                (60, 141, 110, 153, "Beta", 10, False), (200, 141, 300, 153, "short", 10, False),
                (50, 155, 120, 167, "Afterwards", 10, False)]
        blocks = self.blocks([page])[0]
        table = next(b for b in blocks if b["kind"] == "table")
        self.assertEqual(table["rows"], [["Alpha", "first half of a wrapped cell"], ["Beta", "short"]])
        self.assertEqual(blocks[-1]["text"], "Afterwards")

    def test_bold_slightly_larger_row_is_heading(self):
        body = [(50, 100 + i * 14, 550, 112 + i * 14, "Body text long enough to set the body size here.", 12, False)
                for i in range(4)]
        page = [(50, 70, 300, 84, "Bold section title", 13.3, True)] + body
        self.assertEqual(self.blocks([page])[0][0]["kind"], "heading")

    def test_space_between_styled_runs_is_plain(self):
        words = [{"text": "plain", "bold": False, "italic": False, "href": ""},
                 {"text": "bold", "bold": True, "italic": False, "href": ""},
                 {"text": "after", "bold": False, "italic": False, "href": ""}]
        self.assertEqual(adapter._pp_runs(words), [
            {"text": "plain "}, {"text": "bold", "bold": True}, {"text": " "}, {"text": "after"}])

    def image_page(self):
        lines = [(50, 100, 550, 112, "Text above the picture, long enough to be body text here.", 10, False),
                 (50, 420, 550, 432, "Text below the picture, long enough to be body text too.", 10, False)]
        images = {0: [(50, 130, 410, 400, "page-1_1.jpg"),      # illustration: body
                      (50, 15, 95, 50, "page-1_2.png"),         # logo in the header band
                      (300, 200, 310, 210, "page-1_3.png")]}    # 10pt decoration
        return poppler_xml([lines], images)

    def test_body_image_in_reading_order_logo_and_decoration_left_out(self):
        bbox, html = self.image_page()
        loaded = []
        blocks, _ = adapter._poppler_blocks(bbox, html, lambda src: loaded.append(src) or b"\xff\xd8jpeg")
        self.assertEqual([b["kind"] for b in blocks], ["text", "image", "text"])
        img = blocks[1]
        self.assertEqual((img["mime"], img["width"], img["height"]), ("image/jpeg", 480, 360))
        self.assertEqual(loaded, ["page-1_1.jpg"])

    def test_no_loader_no_images(self):
        bbox, html = self.image_page()
        self.assertFalse(any(b["kind"] == "image" for b in adapter._poppler_blocks(bbox, html)[0]))

    def test_image_byte_budget(self):
        bbox, html = self.image_page()
        big = b"x" * (adapter._PP_IMAGE_BUDGET + 1)
        self.assertFalse(any(b["kind"] == "image" for b in adapter._poppler_blocks(bbox, html, lambda s: big)[0]))

    def test_docling_picture_rules(self):
        class Img:
            def save(self, buf, format):
                buf.write(b"\x89PNG fake")
        class Box:
            def __init__(self, l, t, r, b): self.l, self.t, self.r, self.b = l, t, r, b
            def to_top_left_origin(self, page_h): return self
        doc = NS(pages={1: NS(size=NS(width=600.0, height=800.0))})
        def pic(l, t, r, b):
            return NS(label=label("picture"), text="", prov=[NS(page_no=1, bbox=Box(l, t, r, b))],
                      get_image=lambda d: Img())
        items = [(pic(50, 200, 410, 470), 1), (pic(50, 20, 120, 50), 1)]
        images = [b for b in adapter._docling_blocks(items, doc) if b["kind"] == "image"]
        self.assertEqual([(i["width"], i["height"]) for i in images], [(480, 360)])
        self.assertEqual(adapter._docling_blocks(items), [])

    def diagram_page(self):
        title = [(50, 40, 300, 70, "Our three teams", 24, True)]
        labels = [(80, 150, 160, 162, "Sales", 10, False), (300, 150, 380, 162, "Product", 10, False),
                  (520, 150, 590, 162, "Ops", 10, False), (80, 250, 170, 262, "Leads in", 10, False),
                  (300, 260, 400, 272, "Roadmap", 10, False), (520, 280, 590, 292, "Support", 10, False)]
        return poppler_xml([title + labels])

    def slide_tools(self, coverage):
        calls = []
        return calls, {"coverage": lambda pno, page, t, i: coverage,
                       "render": lambda pno, top, bottom: calls.append((pno, round(top), round(bottom))) or b"\x89PNG diagram"}

    def test_diagram_page_becomes_title_picture_and_notes(self):
        bbox, html = self.diagram_page()
        calls, tools = self.slide_tools(0.3)
        blocks, _ = adapter._poppler_blocks(bbox, html, None, tools)
        self.assertEqual([(b["kind"], b.get("region", "body")) for b in blocks][:2], [("heading", "body"), ("image", "body")])
        self.assertEqual(blocks[0]["text"], "Our three teams")
        notes = [b["text"] for b in blocks if b.get("region") == "notes"]
        self.assertIn("Sales", " ".join(notes))
        self.assertEqual(calls[0][0], 1)
        self.assertGreater(calls[0][1], 70)   # cropped below the title

    def test_undrawn_page_is_not_a_diagram(self):
        bbox, html = self.diagram_page()
        _, tools = self.slide_tools(0.0)
        blocks, _ = adapter._poppler_blocks(bbox, html, None, tools)
        self.assertFalse(any(b["kind"] == "image" or b.get("region") == "notes" for b in blocks))

    def test_drawn_table_stays_a_table(self):
        rows = [(60, 100 + i * 20, 120, 112 + i * 20, w, 10, i == 0) for i, w in enumerate(["Name", "Ann", "Bob"])] + \
               [(220, 100 + i * 20, 280, 112 + i * 20, w, 10, i == 0) for i, w in enumerate(["Age", "23", "31"])] + \
               [(380, 100 + i * 20, 440, 112 + i * 20, w, 10, i == 0) for i, w in enumerate(["City", "Oslo", "Rome"])]
        bbox, html = poppler_xml([[(50, 40, 300, 70, "A table", 24, True)] + rows])
        _, tools = self.slide_tools(0.3)
        blocks, _ = adapter._poppler_blocks(bbox, html, None, tools)
        self.assertTrue(any(b["kind"] == "table" for b in blocks))
        self.assertFalse(any(b["kind"] == "image" for b in blocks))

    def test_symbol_font_glyphs_mapped(self):
        line = {"words": [{"text": "Provider"}, {"text": "\uf0e0"}, {"text": "LLMs"}]}
        self.assertEqual(adapter._pp_line_text(line), "Provider → LLMs")

    def test_ppm_coverage(self):
        # 10x10 white page with a 3x3 black square in the middle band.
        w = h = 10
        px = bytearray(b"\xff" * (w * h * 3))
        for y in range(4, 7):
            for x in range(4, 7):
                i = (y * w + x) * 3
                px[i:i + 3] = b"\x00\x00\x00"
        ppm = b"P6\n10 10\n255\n" + bytes(px)
        cov = adapter._pp_ppm_coverage(ppm, 100.0, 100.0, [])
        self.assertAlmostEqual(cov, 9 / 90, places=3)       # the bottom row is the footer band
        self.assertEqual(adapter._pp_ppm_coverage(ppm, 100.0, 100.0, [(40, 40, 70, 70)]), 0.0)

    def test_key_matches_ailang_normalisation(self):
        # Mirrors pdfFurnitureKey's inline tests in pdf_furniture.ail.
        self.assertEqual(adapter._pp_key("Holosun ApS · CVR 44 324687 · ailang.sunholo.com"),
                         "holosun aps · cvr # · ailang.sunholo.com")
        self.assertEqual(adapter._pp_key("Page 3 of 12"), "page # of #")


STAMP = "RECEIVED BY THE ARCHIVE OF NORTHWOOD - CERTIFIED TRUE COPY - FILE NO. 2031-554210"


def scan(n: int, total: int) -> str:
    """pdftotext -layout of a scanned page: the stamp and a page number."""
    return f"{' ' * 60}Page {n} of {total}\n\n\n\n{STAMP}\n"


class TextLayer(unittest.TestCase):
    """The text-layer audit behind pdf_text_layer_sparse (2026-11-02 incident:
    every page a scan plus one identical stamp line)."""

    def audit(self, pages, pictures=None, calls=None):
        def picture_pages():
            if calls is not None:
                calls.append(1)
            return set(range(1, len(pages) + 1)) if pictures is None else pictures
        return adapter._text_layer(pages, picture_pages)

    def test_pdftotext_pages_split_on_form_feeds(self):
        self.assertEqual(adapter._pdftotext_pages("a\fb\f\f"), ["a", "b", ""])
        self.assertEqual(adapter._pdftotext_pages("no feeds"), ["no feeds"])

    def test_stamp_on_every_scanned_page_is_textless(self):
        tl = self.audit([scan(n, 78) for n in range(1, 79)])
        self.assertEqual((tl["pages"], tl["textlessPages"]), (78, list(range(1, 79))))
        self.assertLess(tl["distinctWords"], 20)

    def test_no_text_at_all_needs_no_image_check(self):
        calls = []
        tl = self.audit(["", "  \n", ""], calls=calls)
        self.assertEqual(tl["textlessPages"], [1, 2, 3])
        self.assertEqual(calls, [])

    def test_slide_deck_is_not_textless(self):
        # Little text per page, but its own on every page; a repeated footer
        # and full-bleed pictures on every slide do not change that.
        slides = [("Quarterly roadmap", "Ship the field app"), ("Why now", "Paper backlog doubled"),
                  ("Pilot results", "41% faster filing"), ("Risks", "Vendor lock-in")]
        pages = [f"{t}\n  - {b}\n\nNorthwood - internal - {n}\n" for n, (t, b) in enumerate(slides, 1)]
        self.assertEqual(self.audit(pages)["textlessPages"], [])

    def test_identical_pages_without_pictures_are_text(self):
        form = "APPLICATION FOR A PARKING PERMIT\nApplicant name: ______\nSignature: ____\n"
        calls = []
        tl = self.audit([form] * 4, pictures=set(), calls=calls)
        self.assertEqual(tl["textlessPages"], [])
        self.assertEqual(calls, [1])        # asked, because every line repeats

    def test_partial_scan_names_only_the_scanned_pages(self):
        text = [f"Chapter {n}\nThe survey of parcel {n} found the markers intact and the lane clear.\n"
                for n in range(1, 5)]
        tl = self.audit(text + [scan(5, 6), scan(6, 6)], pictures={5, 6})
        self.assertEqual(tl["textlessPages"], [5, 6])

    def test_numbers_only_rows_are_content(self):
        # Rows of figures normalise alike ("# # #") but are a statement's content.
        rows = ["2031  4,551.20  118.00  4,433.20", "2032  4,433.20  120.10  4,313.10"]
        pages = ["\n".join(rows[i % 2] for i in range(3)) + "\n" for _ in range(3)]
        self.assertEqual(self.audit(pages)["textlessPages"], [])

    def test_fragmented_stamp_with_number_fragments_is_textless(self):
        # A stamp drawn rotated / letter-spaced comes out as many 1-3 character
        # lines, some of them digits only ("/0", ":3"). Those number-only
        # fragments used to count as content and left every page above the
        # threshold, hiding a 78-page scan (2026-11-02).
        frags = ["Ce", "rt", "ifi", "ed", "co", "py", "12", "/0", "3/", "20", "31", ":3", "0", "-", "4"]
        pages = ["\n".join(" " * (i % 7) + f for i, f in enumerate(frags)) + f"\n{' ' * 60}{n}\n"
                 for n in range(1, 41)]
        tl = self.audit(pages)
        self.assertEqual(tl["textlessPages"], list(range(1, 41)))

    def test_short_number_lines_on_few_pages_stay_content(self):
        # A short figure repeated on a couple of pages out of many is not a
        # stamp: below the repeat share it is still the page's own text.
        pages = [f"Ref {n:03d}\n12\n/0\n3/\n20\n31\n:3\n" if n <= 2 else
                 f"Parcel {n} was surveyed and the boundary stones were found in place.\n"
                 for n in range(1, 21)]
        tl = self.audit(pages, pictures={1, 2})
        self.assertEqual(tl["textlessPages"], [])

    def test_without_image_data_a_line_must_repeat_widely(self):
        # A heading shared by two of ten pages is not furniture when no image
        # data says those pages are pictures.
        words = ["alder", "birch", "cedar", "dogwood", "elm", "fir", "ginkgo", "hazel"]
        pages = [f"The {w} stand on this parcel was surveyed and tagged.\n" for w in words]
        pages += ["Appendix tables and figures (scanned)\n", "Appendix tables and figures (scanned)\n"]
        tl = adapter._text_layer(pages, lambda: None)
        self.assertEqual(tl["textlessPages"], [])
        tl = adapter._text_layer([scan(n, 10) for n in range(1, 11)], lambda: None)
        self.assertEqual(len(tl["textlessPages"]), 10)

    def test_all_textless_guard(self):
        self.assertTrue(adapter._text_layer_all_textless({"pages": 2, "textlessPages": [1, 2]}))
        self.assertFalse(adapter._text_layer_all_textless({"pages": 2, "textlessPages": [2]}))
        self.assertFalse(adapter._text_layer_all_textless({"pages": 0, "textlessPages": []}))
        self.assertFalse(adapter._text_layer_all_textless(None))


@unittest.skipUnless(shutil.which("pdftotext") and shutil.which("pdfimages"), "needs poppler")
class TextLayerFixtures(unittest.TestCase):
    """The audit end to end on synthetic PDFs (benchmarks/pdf/text_layer_fixtures.py)."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "text_layer_fixtures", _ADAPTER.parent.parent.parent / "benchmarks" / "pdf" / "text_layer_fixtures.py")
        fx = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fx)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.paths = fx.write_fixtures(Path(cls.tmp.name))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def layer(self, name, backend="pdftotext"):
        return adapter.BACKENDS[backend](self.paths[name])["textLayer"]

    def test_scanned(self):
        for backend in ("pdftotext", "poppler"):
            self.assertEqual(self.layer("scanned.pdf", backend)["textlessPages"], [1, 2, 3, 4, 5, 6])

    def test_scanned_with_fragmented_stamp(self):
        for backend in ("pdftotext", "poppler"):
            self.assertEqual(self.layer("scanned_fragments.pdf", backend)["textlessPages"],
                             [1, 2, 3, 4, 5, 6], backend)

    def test_partial(self):
        self.assertEqual(self.layer("partial.pdf")["textlessPages"], [5, 6])

    def test_slides_and_forms_are_not_flagged(self):
        for name in ("slides.pdf", "forms.pdf"):
            for backend in ("pdftotext", "poppler"):
                self.assertEqual(self.layer(name, backend)["textlessPages"], [], f"{name} via {backend}")

    def test_picture_pages(self):
        self.assertEqual(adapter._picture_pages(self.paths["partial.pdf"]), {5, 6})
        self.assertEqual(adapter._picture_pages(self.paths["slides.pdf"]), {3})   # full-bleed background


if __name__ == "__main__":
    unittest.main()
