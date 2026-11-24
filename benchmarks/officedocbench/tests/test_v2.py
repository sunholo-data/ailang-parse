"""Corruptions that used to leave the public score unchanged."""

import copy
import json
import sys
import unittest
from pathlib import Path

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH))
# ruff: noqa: E402
from structure_v2 import score_structure, has_extracted_content
from scoring import (
    score_structural_quality,
    score_metadata,
    _score_ordering,
)
from adapters.docparse_adapter import DocParseAdapter
from adapters.llamaparse_adapter import LlamaParseAdapter
from adapters.extend_adapter import ExtendAdapter
from adapters.reducto_adapter import ReductoAdapter
from adapters.liteparse_adapter import LiteParseAdapter
from types import SimpleNamespace
from adapters.structure import (
    raw_structure,
    markdown_output,
    html_rows,
    table_cells,
    add_sheet_scopes,
    docling_structure,
)
import eval_officedocbench as runner
from audit_legacy_truth import audited, CASES


class StructuralTests(unittest.TestCase):
    def test_audited_legacy_fields_are_source_derived_and_repeatable(self):
        for name in CASES:
            with self.subTest(file=name):
                source = runner._find_test_file(name)
                truth = json.loads(
                    (BENCH / "ground_truth" / (name + ".json")).read_text()
                )
                self.assertEqual(audited(source, truth), truth)
        footnotes = audited(
            runner._find_test_file("challenge_footnotes.docx"), {"features": {}}
        )
        self.assertEqual(footnotes["features"]["footnotes_endnotes"]["count"], 0)
        self.assertEqual(footnotes["input_profile"], "recovery")
        nested = audited(
            runner._find_test_file("challenge_nested_lists.docx"), {"features": {}}
        )
        # WordprocessingML has no list container: list grouping is not scored.
        self.assertIsNone(nested["features"]["lists"])
        self.assertIn("lists:docx", nested["legacy_verification"]["not_scored"])

    def test_every_legacy_case_is_rebuilt_from_source(self):
        self.assertEqual(len(CASES), 69)
        for name in CASES:
            with self.subTest(file=name):
                truth = json.loads(
                    (BENCH / "ground_truth" / (name + ".json")).read_text()
                )
                self.assertTrue(truth["verified"])
                self.assertNotIn("element_order", truth)
                self.assertNotIn("paragraph_count", truth["features"]["text"])
                tables = truth["features"].get("tables") or {}
                self.assertNotIn("total_rows", tables)
                record = truth["legacy_verification"]
                self.assertEqual(record["oracle"], "audit_legacy_truth.py v2")
                self.assertIn("full_text_words", record["fields"])

    def test_heading_texts_match_heading_counts(self):
        with_texts = 0
        for name in CASES:
            truth = json.loads((BENCH / "ground_truth" / (name + ".json")).read_text())
            headings = truth["features"]["headings"]
            if headings is None:
                continue
            with self.subTest(file=name):
                texts = headings["texts"]
                self.assertEqual(len(texts), headings["count"])
                levels = {}
                for entry in texts:
                    self.assertTrue(entry["text"].strip())
                    levels[str(entry["level"])] = levels.get(str(entry["level"]), 0) + 1
                self.assertEqual(levels, headings["by_level"])
                with_texts += bool(texts)
        self.assertGreater(with_texts, 0)
        real_world = audited(
            runner._find_test_file("challenge_real_world.docx"), {"features": {}}
        )["features"]["headings"]["texts"]
        # Title/Subtitle carry no outline level and are not headings.
        self.assertNotIn("Title", [h["text"] for h in real_world])
        self.assertEqual(real_world[0]["level"], 1)

    def test_source_truth_corrections(self):
        def build(name):
            return audited(runner._find_test_file(name), {"features": {}})

        # ODF creation date is meta:creation-date; dc:date is the last save.
        odt = build("lo_listformat.odt")["features"]["metadata"]
        self.assertEqual(odt["created"], "2021-06-14T11:52:30.242000000")
        self.assertEqual(odt["modified"], "2021-06-14T11:53:55.192000000")
        # dc:creator alone is the last editor, not the author.
        self.assertNotIn("author", build("test.odt")["features"]["metadata"])
        # A comment range is the text between commentRangeStart and End.
        ranges = build("challenge_comment_ranges.docx")["features"]["comments"]["ranges"]
        self.assertEqual(ranges[0]["annotated_text"], "deadline is March 15")
        # Empty header parts are not headers; notes without w:type are notes.
        hdr = build("docx-hdrftr.docx")["features"]["headers_footers"]
        self.assertEqual((hdr["header_count"], hdr["footer_count"]), (1, 1))
        self.assertEqual(build("pandoc_notes.docx")["features"]["footnotes_endnotes"]["count"], 2)
        # mc:Fallback repeats each text box; count it once.
        self.assertEqual(build("docx-shapes.docx")["features"]["text_boxes"]["count"], 4)
        # The body's closing w:sectPr is not a section break.
        fields = audited(
            runner._find_test_file("challenge_fields.docx"),
            {"features": {"section_breaks": {"present": True, "count": 1}}},
        )
        self.assertEqual(fields["features"]["section_breaks"]["count"], 0)
        # Minimal hand-made ODF packages are recovery inputs.
        for name in ("test.odt", "test.ods", "test.odp"):
            self.assertEqual(build(name)["input_profile"], "recovery")
        for name in ("lo_nested_table.odt", "lo_table_styles.odt"):
            self.assertTrue(build(name)["allow_empty_output"])
            self.assertEqual(build(name)["full_text_words"], [])

    def test_key_phrases_occur_verbatim_in_the_source(self):
        from source_truth import read

        for name in CASES:
            truth = json.loads((BENCH / "ground_truth" / (name + ".json")).read_text())
            facts = read(runner._find_test_file(name), truth["format"])
            for phrase in truth["features"]["text"].get("key_phrases", []):
                with self.subTest(file=name, phrase=phrase):
                    self.assertTrue(facts.contains_phrase(phrase))
        kept = audited(
            runner._find_test_file("docx-shapes.docx"),
            {"features": {"text": {"key_phrases": ["Paragraph with <inline-image> within."]}}},
        )
        self.assertNotIn("key_phrases", kept["features"]["text"])

    def test_structure_asserts_only_real_breaks_and_explicit_formatting(self):
        import zipfile
        from build_structure_truth import docx

        with zipfile.ZipFile(runner._find_test_file("challenge_page_breaks.docx")) as z:
            breaks = docx(z)["breaks"]
        self.assertEqual(
            sorted(b["kind"] for b in breaks), ["page-break", "section-break"]
        )
        with zipfile.ZipFile(runner._find_test_file("challenge_fields.docx")) as z:
            self.assertNotIn("breaks", docx(z))
        with zipfile.ZipFile(runner._find_test_file("docx-shapes.docx")) as z:
            self.assertNotIn("runs", docx(z))
        for name in ("table_header_rowspan.docx", "poi_comment.pptx", "image_vml.docx"):
            runs = json.loads(
                (BENCH / "ground_truth" / (name + ".json")).read_text()
            )["structure"]["runs"]
            for run in runs:
                self.assertNotIn(False, run.values())
                self.assertNotEqual(run.get("color"), "#000000")

    def test_html_audit_rejects_old_parse_error_expectations_and_counts_nesting(self):
        truth = audited(
            runner._find_test_file("challenge_complex.html"),
            {
                "features": {"text": {"key_phrases": ["HTML parse error"]}},
                "full_text_words": ["error"],
            },
        )
        self.assertNotIn("error", truth["full_text_words"])
        self.assertIn("revenue", truth["full_text_words"])
        self.assertEqual(truth["features"]["headings"]["count"], 4)
        # One top-level <ol> whose item holds a nested <ul>: one list, depth 2.
        self.assertEqual(truth["features"]["lists"]["count"], 1)
        self.assertEqual(truth["features"]["lists"]["max_depth"], 2)
        complex_html = audited(
            runner._find_test_file("test_complex.html"), {"features": {}}
        )
        self.assertEqual(complex_html["features"]["tables"]["count"], 3)

    def test_pptx_audit_preserves_source_spaces_and_excludes_unused_media(self):
        truth = audited(runner._find_test_file("poi_comment.pptx"), {"features": {}})
        self.assertIn("finance", truth["full_text_words"])
        self.assertNotIn("tofinancefor", truth["full_text_words"])
        self.assertNotIn("worldwaterforum", truth["full_text_words"])
        self.assertEqual(truth["features"]["images"]["count"], 0)
        basic = audited(runner._find_test_file("pandoc_basic.pptx"), {"features": {}})
        self.assertIn("everworker", basic["full_text_words"])
        self.assertIn("venn", basic["full_text_words"])
        self.assertNotIn("everworkervenn", basic["full_text_words"])

    def assert_sensitive(self, key, want, mutation):
        gt = {key: want}
        output = {"structure": {key: copy.deepcopy(want)}}
        self.assertEqual(score_structure(gt, output)["score"], 1)
        mutation(output["structure"][key])
        self.assertLess(score_structure(gt, output)["score"], 1)

    def test_column_shift(self):
        self.assert_sensitive(
            "table_cells",
            [{"table": 0, "row": 2, "col": 3, "text": "Acme"}],
            lambda xs: xs[0].update(col=4),
        )

    def test_table_assigned_to_wrong_sheet(self):
        self.assert_sensitive(
            "table_cells",
            [{"scope": "Revenue", "row": 1, "col": 1, "text": "100"}],
            lambda xs: xs[0].update(scope="Costs"),
        )

    def test_sheet_order(self):
        self.assert_sensitive(
            "containers",
            [{"kind": "sheet", "name": "A"}, {"kind": "sheet", "name": "B"}],
            lambda xs: xs.reverse(),
        )

    def test_same_type_reading_order(self):
        self.assert_sensitive(
            "element_order",
            [{"type": "text", "text": "first"}, {"type": "text", "text": "second"}],
            lambda xs: xs.reverse(),
        )
        self.assertLess(
            _score_ordering(
                [{"type": "text", "text": "first"}],
                [{"type": "text", "text": "second"}],
            ),
            1,
        )

    def test_notes_belong_to_slide(self):
        self.assert_sensitive(
            "notes",
            [{"scope": "Agenda", "text": "Ask for feedback"}],
            lambda xs: xs[0].update(scope="Budget"),
        )

    def test_comment_target(self):
        self.assert_sensitive(
            "comment_anchors",
            [{"text": "Fix", "annotated_text": "target", "anchored": True}],
            lambda xs: xs[0].update(annotated_text="other"),
        )

    def test_legacy_comment_range_cannot_pass_by_word_presence(self):
        f = {
            "comments": {
                "present": True,
                "ranges": [{"comment_text": "Fix", "annotated_text": "target"}],
            }
        }
        wrong = {
            "comments": [{"text": "Fix", "annotated_text": "other", "anchored": True}],
            "text_elements": [{"text": "target"}],
        }
        self.assertEqual(
            score_structural_quality(f, wrong)["details"]["comment_ranges"]["score"], 0
        )

    def test_list_depth(self):
        self.assert_sensitive(
            "list_items",
            [{"text": "child", "ordered": True, "level": 2}],
            lambda xs: xs[0].update(level=0),
        )

    def test_style(self):
        self.assert_sensitive(
            "runs",
            [{"text": "bold", "bold": True}],
            lambda xs: xs[0].update(bold=False),
        )

    def test_style_coalescing(self):
        self.assertEqual(
            score_structure(
                {"runs": [{"text": "bold", "bold": True}]},
                {"structure": {"runs": [{"text": "some bold words", "bold": True}]}},
            )["score"],
            1,
        )

    def test_one_run_cannot_satisfy_duplicate_occurrences(self):
        want = {"runs": [{"text": "bold", "bold": True}] * 2}
        got = {"structure": {"runs": [{"text": "bold", "bold": True}]}}
        self.assertEqual(score_structure(want, got)["score"], 0.5)

    def test_formula(self):
        self.assert_sensitive(
            "table_cells",
            [{"row": 1, "col": 2, "text": "3", "formula": "A1+1"}],
            lambda xs: xs[0].pop("formula"),
        )

    def test_formula_display_prefix_is_equivalent_but_expression_matters(self):
        for expected, actual in [("A1+1", "=A1+1"), ("=A1+1", "A1+1")]:
            want = {"table_cells": [{"row": 1, "col": 2, "formula": expected}]}
            got = {
                "structure": {"table_cells": [{"row": 1, "col": 2, "formula": actual}]}
            }
            with self.subTest(expected=expected, actual=actual):
                self.assertEqual(score_structure(want, got)["score"], 1)
                got["structure"]["table_cells"][0]["formula"] = "=A1+2"
                self.assertEqual(score_structure(want, got)["score"], 0)
                got["structure"]["table_cells"][0].pop("formula")
                self.assertEqual(score_structure(want, got)["score"], 0)

    def test_fill_on_blank_cell(self):
        self.assert_sensitive(
            "table_cells",
            [{"row": 2, "col": 2, "text": "", "fill": "#ffff00"}],
            lambda xs: xs[0].pop("fill"),
        )

    def test_bookmark_break_link(self):
        for key, record in [
            ("bookmarks", {"name": "target"}),
            ("breaks", {"kind": "page-break"}),
            ("hyperlinks", {"text": "site", "url": "https://example.org"}),
        ]:
            with self.subTest(key=key):
                self.assert_sensitive(key, [record], lambda xs: xs.clear())

    def test_missing_evidence_not_inferred(self):
        self.assertEqual(
            score_structure(
                {"table_cells": [{"row": 1, "col": 1, "text": "yes"}]},
                {"tables": [{"cell_text": "yes"}]},
            )["score"],
            0,
        )

    def test_metadata_order(self):
        self.assertLess(
            score_metadata({}, {"sheet_names": ["B", "A"]}, {"names": ["A", "B"]})[
                "score"
            ],
            1,
        )

    def test_raw_adapter_retains_data(self):
        raw = {
            "document": {
                "blocks": [
                    {
                        "type": "section",
                        "kind": "sheet",
                        "name": "S",
                        "blocks": [
                            {
                                "type": "table",
                                "headers": ["A", "B"],
                                "rows": [
                                    [
                                        "",
                                        {
                                            "text": "3",
                                            "formula": "A1+1",
                                            "fill": "#ffff00",
                                        },
                                    ]
                                ],
                            }
                        ],
                    },
                    {
                        "type": "section",
                        "kind": "comment",
                        "blocks": [
                            {
                                "type": "comment",
                                "text": "Fix",
                                "author": "Ann",
                                "anchorText": "B2: 3",
                                "anchored": True,
                            }
                        ],
                    },
                ]
            }
        }
        out = raw_structure(raw)
        self.assertEqual(out["table_cells"][-1]["formula"], "A1+1")
        self.assertEqual(out["comment_anchors"][0]["scope"], "S")

    def test_link_labels_coalesce_only_across_adjacent_target_runs(self):
        raw = {
            "document": {
                "blocks": [
                    {
                        "type": "text",
                        "runs": [
                            {
                                "text": "Our",
                                "href": "https://example.com",
                                "bold": True,
                            },
                            {"text": " site", "href": "https://example.com"},
                            {"text": " and "},
                            {"text": "again", "href": "https://example.com"},
                        ],
                    }
                ]
            }
        }
        self.assertEqual(
            raw_structure(raw)["hyperlinks"],
            [
                {"text": "Our site", "url": "https://example.com"},
                {"text": "again", "url": "https://example.com"},
            ],
        )

    def test_warning_blocks_are_diagnostics_and_images_retain_order(self):
        raw = {
            "document": {
                "metadata": {},
                "blocks": [
                    {"type": "text", "text": "Source prose", "style": "Normal"},
                    {"type": "image", "description": "Logo", "mime": "image/png"},
                    {"type": "text", "text": "Missing note part", "style": "warning"},
                ],
            }
        }
        out = DocParseAdapter()._convert(raw)
        self.assertEqual([r["text"] for r in out["text_elements"]], ["Source prose"])
        self.assertEqual(
            out["structure"]["element_order"],
            [
                {"type": "text", "text": "Source prose"},
                {"type": "image"},
            ],
        )
        self.assertEqual(len(out["images"]), 1)
        self.assertIn("Missing note part", out["warnings"])

    def test_cell_runs_are_scored_from_provider_output(self):
        output = {
            "document": {
                "blocks": [
                    {
                        "type": "table",
                        "headers": [],
                        "rows": [
                            [
                                {
                                    "text": "label",
                                    "runs": [
                                        {
                                            "text": "label",
                                            "bold": True,
                                            "color": "#123456",
                                            "href": "https://example.com",
                                        }
                                    ],
                                }
                            ]
                        ],
                    }
                ]
            }
        }
        got = raw_structure(output)
        expected = {
            "runs": [{"text": "label", "bold": True, "color": "#123456"}],
            "hyperlinks": [{"text": "label", "url": "https://example.com"}],
        }
        self.assertEqual(score_structure(expected, {"structure": got})["score"], 1)
        output["document"]["blocks"][0]["rows"][0][0].pop("runs")
        self.assertEqual(
            score_structure(expected, {"structure": raw_structure(output)})["score"], 0
        )

    def test_markdown_adapter_keeps_empty_cells_and_styles(self):
        out = markdown_output(
            "**bold**\n\n| A | B | C |\n|---|---|---|\n| one | | three |\n"
        )
        self.assertEqual(out["structure"]["table_cells"][-2]["text"], "")
        self.assertEqual(
            score_structure({"runs": [{"text": "bold", "bold": True}]}, out)["score"], 1
        )

    def test_html_spans(self):
        rows = html_rows('<table><tr><td colspan="2">wide</td><td>x</td></tr></table>')
        self.assertEqual(table_cells(rows, 0)[-1]["col"], 3)

    def test_version_is_package_version(self):
        self.assertNotEqual(DocParseAdapter().version(), "0.3.0")

    def test_source_hashes_and_schema(self):
        import hashlib
        import jsonschema

        schema = json.loads((BENCH / "schema/ground_truth.schema.json").read_text())
        for p in (BENCH / "ground_truth").glob("*.json"):
            gt = json.loads(p.read_text())
            jsonschema.validate(gt, schema)
            if "verification" in gt:
                src = runner._find_test_file(gt["file"])
                self.assertEqual(
                    hashlib.sha256(src.read_bytes()).hexdigest(),
                    gt["verification"]["source_sha256"],
                )

    def test_failed_batch_cannot_score_stale_output(self):
        class Empty(DocParseAdapter):
            def parse_batch(self, paths):
                return {}

            def parse(self, path):
                raise AssertionError("must not retry stale individual output")

        result = runner.evaluate_adapter(
            Empty(), [BENCH / "ground_truth/sample.docx.json"], use_golden=False
        )
        self.assertEqual(result["results"][0]["status"], "ERROR")

    def test_captured_v047_defects_reduce_public_score(self):
        prefix = BENCH.parent / "office/regressions/v0_47_0_prefix"
        goldens = BENCH.parent / "office/golden"
        for name in (
            "challenge_sparse_rows.xlsx",
            "poi_two_sheets.xlsx",
            "pptx_slide_order_notes.pptx",
            "poi_comment.pptx",
        ):
            with self.subTest(file=name):
                gt = json.loads((BENCH / "ground_truth" / (name + ".json")).read_text())
                old = json.loads((prefix / (name + ".json")).read_text())
                current = json.loads((goldens / (name + ".json")).read_text())
                a = score_structure(gt["structure"], {"structure": raw_structure(old)})[
                    "score"
                ]
                b = score_structure(
                    gt["structure"], {"structure": raw_structure(current)}
                )["score"]
                self.assertLess(a, b)

    def test_footer_only_and_blank_slide_results_are_valid(self):
        self.assertTrue(
            has_extracted_content({"headers_footers": [{"text": "footer"}]})
        )
        self.assertTrue(
            has_extracted_content(
                {"structure": {"containers": [{"kind": "slide", "name": ""}]}}
            )
        )
        self.assertTrue(has_extracted_content({}, {"allow_empty_output": True}))
        self.assertFalse(
            has_extracted_content(
                {"text_elements": [], "structure": {"table_cells": []}}
            )
        )

    def test_markdown_sheet_names_are_credited(self):
        out = add_sheet_scopes(
            markdown_output("## Revenue\n\n| A | B |\n|---|---|\n| x | 3 |\n")
        )
        self.assertEqual(
            out["structure"]["containers"], [{"kind": "sheet", "name": "Revenue"}]
        )
        self.assertEqual(out["structure"]["table_cells"][-1]["scope"], "Revenue")

    def test_docling_worksheet_offsets_are_preserved(self):
        doc = {
            "groups": [
                {"label": "sheet", "name": "S", "children": [{"$ref": "#/tables/0"}]}
            ],
            "tables": [
                {
                    "self_ref": "#/tables/0",
                    "prov": [{"bbox": {"t": 3, "l": 2}}],
                    "data": {
                        "table_cells": [
                            {
                                "text": "x",
                                "start_row_offset_idx": 0,
                                "start_col_offset_idx": 0,
                            }
                        ]
                    },
                }
            ],
        }
        result = docling_structure(doc)["table_cells"][0]
        self.assertEqual((result["scope"], result["row"], result["col"]), ("S", 4, 3))

    def test_html_table_keeps_reading_order_and_sheet_attribution(self):
        out = add_sheet_scopes(
            markdown_output(
                "## Revenue\n\n<table><tr><td>A</td><td>B</td></tr><tr><td>x</td><td>3</td></tr></table>\n"
            )
        )
        self.assertEqual(out["structure"]["element_order"][-1]["type"], "table")
        self.assertEqual(out["structure"]["table_cells"][-1]["scope"], "Revenue")

    def test_declared_corpus_matches_annotations(self):
        declared = set(json.loads((BENCH / "corpus.json").read_text())["files"])
        actual = {p.name[:-5] for p in (BENCH / "ground_truth").glob("*.json")}
        self.assertEqual(declared, actual)
        self.assertEqual(len(declared), 87)

    def test_llamaparse_native_page_heading_scopes_table(self):
        response = [
            {
                "pages": [
                    {
                        "md": "<table><tr><td>A</td></tr></table>",
                        "items": [{"type": "heading", "value": "Revenue", "lvl": 1}],
                    }
                ]
            }
        ]
        output = LlamaParseAdapter().convert_json(response, Path("input.xlsx"))
        self.assertEqual(output["structure"]["table_cells"][0]["scope"], "Revenue")
        self.assertEqual(output["metadata"]["sheet_names"], ["Revenue"])

    def test_llamaparse_native_notes_keep_slide_attribution(self):
        response = [
            {
                "pages": [
                    {
                        "md": "# Agenda",
                        "items": [{"type": "heading", "value": "Agenda"}],
                        "slideSpeakerNotes": "Ask for feedback",
                    }
                ]
            }
        ]
        output = LlamaParseAdapter().convert_json(response, Path("input.pptx"))
        self.assertEqual(
            output["structure"]["notes"],
            [{"scope": "Agenda", "text": "Ask for feedback"}],
        )

    def test_llamaparse_job_failure_is_visible(self):
        with self.assertRaisesRegex(RuntimeError, "conversion failed"):
            LlamaParseAdapter().convert_json(
                [{"error": "conversion failed"}], Path("input.epub")
            )

    @staticmethod
    def _extend_run(chunks):
        return {"status": "PROCESSED", "output": {"chunks": chunks}}

    def test_extend_sheet_scopes_formulas_and_merges(self):
        sheet = {"sheet": {"index": 0, "name": "Budget"}}
        html = (
            '<table><tr><th data-cell="A1">Item</th><th data-cell="B1">Cost</th></tr>'
            '<tr><td data-cell="A2">Total</td>'
            '<td data-cell="B2" data-formula="=SUM(B1:B1)">9</td></tr>'
            '<tr><td colspan="2" data-cell="A3:B3">Note</td></tr></table>'
        )
        run = self._extend_run(
            [{"blocks": [{"type": "table", "content": html, "metadata": sheet}]}]
        )
        output = ExtendAdapter().convert_json(run, Path("input.xlsx"))
        cells = output["structure"]["table_cells"]
        self.assertEqual(output["metadata"]["sheet_names"], ["Budget"])
        self.assertEqual(output["structure"]["containers"], [{"kind": "sheet", "name": "Budget"}])
        self.assertTrue(all(c["scope"] == "Budget" for c in cells))
        self.assertEqual(
            [c.get("formula") for c in cells if c["text"] == "9"], ["=SUM(B1:B1)"]
        )
        self.assertTrue(output["tables"][0]["has_merged_cells"])
        note = [c for c in cells if c["text"] == "Note"][0]
        self.assertEqual((note["row"], note["col"], note["col_span"]), (3, 1, 2))
        self.assertIn(
            {"table": 0, "scope": "Budget", "row": 3, "col": 2, "text": "", "col_span": 1, "merged": True},
            cells,
        )

    def test_extend_split_sheet_keeps_sheet_coordinates_and_colours(self):
        sheet = {"sheet": {"index": 0, "name": "Form"}}
        first = '<table><tr><td data-cell="A1" style="color:#FFFFFF;background-color:#1F4E78">Title</td></tr></table>'
        second = '<table><tr><td data-cell="A6">Later</td></tr></table>'
        run = self._extend_run(
            [{"blocks": [
                {"type": "table", "content": first, "metadata": sheet},
                {"type": "table", "content": second, "metadata": sheet},
            ]}]
        )
        output = ExtendAdapter().convert_json(run, Path("input.xlsx"))
        cells = {c["text"]: c for c in output["structure"]["table_cells"]}
        self.assertEqual((cells["Later"]["table"], cells["Later"]["row"]), (0, 6))
        self.assertEqual((cells["Title"]["fill"], cells["Title"]["color"]), ("#1f4e78", "#ffffff"))
        self.assertEqual(len(output["tables"]), 2)

    def test_extend_change_markup_becomes_typed_changes(self):
        run = self._extend_run(
            [
                {
                    "blocks": [
                        {
                            "type": "text",
                            "content": "Ship <change><ins>blue</ins><del>red</del></change> crates.",
                            "metadata": {},
                        },
                        {"type": "footer", "content": "Page footer", "metadata": {}},
                    ]
                }
            ]
        )
        output = ExtendAdapter().convert_json(run, Path("input.docx"))
        self.assertEqual(
            [(c["type"], c["text"]) for c in output["track_changes"]],
            [("insert", "blue"), ("delete", "red")],
        )
        self.assertEqual(output["text_elements"][0]["text"], "Ship bluered crates.")
        self.assertEqual(output["headers_footers"], [{"type": "footer", "text": "Page footer"}])
        self.assertNotIn("Page footer", [t["text"] for t in output["text_elements"]])

    def test_extend_slides_named_by_page_heading(self):
        run = self._extend_run(
            [
                {"blocks": [{"type": "heading", "content": "# Agenda", "metadata": {}}]},
                {"blocks": [{"type": "heading", "content": "# Wrap up", "metadata": {}}]},
            ]
        )
        output = ExtendAdapter().convert_json(run, Path("input.pptx"))
        self.assertEqual(
            [c["name"] for c in output["structure"]["containers"]], ["Agenda", "Wrap up"]
        )
        self.assertEqual(output["speaker_notes"], [])

    def test_extend_ods_sheets_are_containers(self):
        meta = lambda i, n: {"sheet": {"index": i, "name": n}}
        run = self._extend_run(
            [
                {"blocks": [{"type": "table", "content": "<table><tr><td>a</td></tr></table>", "metadata": meta(0, "Prices")}]},
                {"blocks": [{"type": "table", "content": "<table><tr><td>b</td></tr></table>", "metadata": meta(1, "Stock")}]},
            ]
        )
        output = ExtendAdapter().convert_json(run, Path("input.ods"))
        self.assertEqual(output["metadata"]["sheet_names"], ["Prices", "Stock"])

    def test_extend_html_passthrough_keeps_markup_structure(self):
        html = (
            "<h1>Guide</h1><div>Intro <b>bold</b> text</div>"
            "<ul><li>One<ol><li>Nested</li></ol></li></ul>"
            "<table><tr><th>K</th></tr><tr><td>V</td></tr></table>"
        )
        run = self._extend_run([{"blocks": [{"type": "text", "content": html, "metadata": {}}]}])
        output = ExtendAdapter().convert_json(run, Path("input.html"))
        self.assertEqual(output["headings"], [{"text": "Guide", "level": 1}])
        self.assertIn("Intro bold text", [t["text"] for t in output["text_elements"]])
        self.assertEqual(
            [(i["text"], i["level"], i["ordered"]) for i in output["structure"]["list_items"]],
            [("One", 0, False), ("Nested", 1, True)],
        )
        self.assertEqual(len(output["tables"]), 1)

    def test_extend_failed_run_is_visible(self):
        with self.assertRaisesRegex(RuntimeError, "FILE_TYPE_NOT_SUPPORTED"):
            ExtendAdapter().convert_json(
                {"status": "FAILED", "failureReason": "FILE_TYPE_NOT_SUPPORTED"},
                Path("input.odt"),
            )

    @staticmethod
    def _reducto_run(blocks, props=None):
        return {
            "result": {"type": "full", "chunks": [{"content": "", "blocks": blocks}]},
            "document_properties": props,
        }

    @staticmethod
    def _rb(btype, content, page=1, extra=None):
        return {"type": btype, "content": content, "bbox": {"page": page}, "extra": extra}

    def test_reducto_comments_keep_author_anchor_and_reply(self):
        run = self._reducto_run(
            [
                self._rb("Text", "Some text to review."),
                self._rb(
                    "Comment",
                    "Check this.",
                    extra={"author": "Ann", "anchored_text": "text to review",
                           "resolved": False, "reply_to_comment_id": None},
                ),
                self._rb(
                    "Comment",
                    "Agreed.",
                    extra={"author": "Bo", "anchored_text": "text to review",
                           "resolved": True, "reply_to_comment_id": "0"},
                ),
            ],
            {"author": "Ann", "created_at": "2016-05-09T20:15:00+00:00"},
        )
        output = ReductoAdapter().convert_json(run, Path("input.docx"))
        self.assertEqual([c["author"] for c in output["comments"]], ["Ann", "Bo"])
        self.assertEqual(
            output["structure"]["comment_anchors"][1],
            {"text": "Agreed.", "author": "Bo", "annotated_text": "text to review",
             "anchored": True, "parent_id": "0", "resolved": True, "scope": ""},
        )
        self.assertEqual([t["text"] for t in output["text_elements"]], ["Some text to review."])
        self.assertEqual(output["metadata"]["created"], "2016-05-09T20:15:00Z")

    def test_reducto_change_markup_and_inline_formatting(self):
        run = self._reducto_run(
            [
                self._rb("Text", "a <b>bold</b> and <u>under</u> E=mc<sup>2</sup> "
                         "<change><s>gone</s> <u>new</u></change>"),
                self._rb("Footer", "Page footer"),
                self._rb("Page Number", "3"),
            ]
        )
        output = ReductoAdapter().convert_json(run, Path("input.docx"))
        self.assertEqual(
            [(c["type"], c["text"]) for c in output["track_changes"]],
            [("delete", "gone"), ("insert", "new")],
        )
        runs = {r["text"]: r for r in output["structure"]["runs"]}
        self.assertTrue(runs["bold"]["bold"])
        self.assertTrue(runs["under"]["underline"])
        self.assertEqual(runs["2"]["vertAlign"], "superscript")
        self.assertNotIn("gone", runs)  # a tracked change, not strike formatting
        self.assertEqual(output["headers_footers"], [{"type": "footer", "text": "Page footer"}])

    def test_reducto_bare_underline_is_not_an_insertion(self):
        run = self._reducto_run([self._rb("Text", "a <u>two</u> b")])
        output = ReductoAdapter().convert_json(run, Path("input.docx"))
        self.assertEqual(output["track_changes"], [])

    def test_reducto_tab_nested_list_items(self):
        run = self._reducto_run(
            [
                self._rb("List Item", "1. Intro"),
                self._rb("List Item", "\t1. Background"),
                self._rb("List Item", "\t\t• Detail"),
                self._rb("List Item", "2. Method"),
            ]
        )
        output = ReductoAdapter().convert_json(run, Path("input.docx"))
        self.assertEqual(
            [(i["text"], i["ordered"], i["level"]) for i in output["structure"]["list_items"]],
            [("Intro", True, 0), ("Background", True, 1), ("Detail", False, 2), ("Method", True, 0)],
        )

    def test_reducto_slides_and_sheets(self):
        slides = self._reducto_run(
            [self._rb("Title", "Agenda", 1), self._rb("List Item", "• One", 1),
             self._rb("Title", "Wrap up", 2)]
        )
        output = ReductoAdapter().convert_json(slides, Path("input.pptx"))
        self.assertEqual(
            output["structure"]["containers"],
            [{"kind": "slide", "name": "Agenda"}, {"kind": "slide", "name": "Wrap up"}],
        )
        self.assertEqual(output["speaker_notes"], [])
        sheets = self._reducto_run(
            [
                self._rb("Title", "Revenue", 1),
                self._rb("Table", '<table><tr><th>Q</th><th>P</th></tr><tr><td>Q1</td>'
                         '<td data-formula="=B2-C2" style="background-color: yellow">5</td>'
                         '</tr><tr><td colspan="2">[Site](https://example.com)</td></tr></table>', 1),
                self._rb("Title", "Staff", 2),
                self._rb("Table", "<table><tr><td>a</td></tr></table>", 2),
            ]
        )
        output = ReductoAdapter().convert_json(sheets, Path("input.xlsx"))
        self.assertEqual(output["metadata"]["sheet_names"], ["Revenue", "Staff"])
        cells = output["structure"]["table_cells"]
        five = next(c for c in cells if c["text"] == "5")
        self.assertEqual((five["scope"], five.get("formula")), ("Revenue", "=B2-C2"))
        self.assertNotIn("fill", five)  # colour names are not invented into hex
        self.assertIn({"text": "Site", "url": "https://example.com"}, output["hyperlinks"])
        self.assertTrue(output["tables"][0]["has_merged_cells"])

    def test_reducto_refusal_is_visible(self):
        with self.assertRaisesRegex(RuntimeError, "415"):
            ReductoAdapter().convert_json(
                {"failed": True, "failureReason": "parse HTTP 415", "failureMessage": "DOCUMENT_CORRUPT"},
                Path("input.odt"),
            )

    def test_empty_provider_answers_are_valid_empty_output(self):
        import jsonschema

        schema = json.loads((BENCH / "schema/adapter_output.schema.json").read_text())
        out = ReductoAdapter().convert_json(self._reducto_run([]), Path("blank.pptx"))
        jsonschema.validate(out, schema)
        self.assertFalse(has_extracted_content(out))
        self.assertTrue(has_extracted_content(out, {"allow_empty_output": True}))
        # Extend returns one chunk per slide; a blank deck's chunks have no blocks.
        run = {"status": "PROCESSED", "output": {"chunks": [{"blocks": []}] * 3}}
        out = ExtendAdapter().convert_json(run, Path("blank.pptx"))
        jsonschema.validate(out, schema)
        self.assertEqual(out["structure"]["containers"], [{"kind": "slide", "name": ""}] * 3)
        out = ExtendAdapter().convert_json({"status": "PROCESSED", "output": {"chunks": []}}, Path("x.docx"))
        self.assertFalse(has_extracted_content(out))
        self.assertTrue(has_extracted_content(out, {"allow_empty_output": True}))

    def test_liteparse_native_layout_keeps_table_cells(self):
        c = lambda value: SimpleNamespace(text=value)
        block = SimpleNamespace(
            kind="table",
            text=None,
            header=[c("A"), c("B")],
            rows=[[c("one"), c("")]],
            bold=False,
            italic=False,
        )
        page = SimpleNamespace(
            markdown="", text="fallback", blocks=[block], annotations=[], text_items=[]
        )
        output = LiteParseAdapter().convert_result(
            SimpleNamespace(pages=[page], images=[]), Path("file.docx")
        )
        self.assertEqual(len(output["tables"]), 1)
        self.assertEqual(output["structure"]["table_cells"][-1]["col"], 2)
        self.assertEqual(output["structure"]["table_cells"][-1]["text"], "")

    def test_liteparse_layoutnet_tables_and_page_furniture(self):
        # OCRia-nano-1's LayoutNet emits merged_table and page_header/footer.
        c = lambda value: SimpleNamespace(text=value)
        block = lambda kind, **kw: SimpleNamespace(
            kind=kind, text=kw.get("text"), header=None, rows=kw.get("rows"),
            bold=False, italic=False, level=None, ordered=False,
        )
        page = SimpleNamespace(
            markdown="",
            text="fallback",
            blocks=[
                block("page_header", text="Quarterly report"),
                block("merged_table", rows=[[c("A"), c("B")], [c("1"), c("2")]]),
                block("page_footer", text="Page 1"),
            ],
            annotations=[],
            text_items=[],
        )
        output = LiteParseAdapter().convert_result(
            SimpleNamespace(pages=[page], images=[]), Path("file.docx")
        )
        self.assertEqual(len(output["tables"]), 1)
        self.assertTrue(output["tables"][0]["has_merged_cells"])
        self.assertEqual(
            output["headers_footers"],
            [
                {"type": "header", "text": "Quarterly report"},
                {"type": "footer", "text": "Page 1"},
            ],
        )
        self.assertNotIn(
            "Page 1", [t["text"] for t in output["text_elements"]]
        )

    def test_liteparse_backends_are_pinned(self):
        from adapters.liteparse_ocria_adapter import LiteParseOCRiaAdapter

        self.assertEqual(LiteParseAdapter.OCR_BACKEND, "tesseract")
        self.assertEqual(LiteParseOCRiaAdapter.OCR_BACKEND, "ocria-nano")
        self.assertEqual(
            runner._ADAPTER_ID[LiteParseOCRiaAdapter().name()], "liteparse_ocria"
        )

    def test_summary_rejects_filtered_provider_results(self):
        result = {
            "adapter": "Example",
            "provenance": {
                "benchmark_version": "2.1.0",
                "mode": "live",
                "corpus_sha256": "same",
            },
            "results": [{"file": "sample.docx", "status": "ERROR"}],
        }
        with self.assertRaisesRegex(ValueError, "filtered"):
            runner._write_summary([result])

    def test_summary_rejects_legacy_results(self):
        with self.assertRaises(ValueError):
            runner._write_summary([{"adapter": "old", "results": []}])

    def test_dimensions_without_checks_are_not_free_points(self):
        from scoring import score_file

        truth = {"features": {"metadata": {"title": "Q3"}}, "full_text_words": ["alpha"]}
        good = score_file(truth, {"metadata": {"title": "Q3"}, "text_elements": [{"text": "alpha"}]})
        bad = score_file(truth, {"metadata": {}, "text_elements": [{"text": "beta"}]})
        self.assertEqual(good["composite"], 1.0)
        # Only metadata and text are checked, so a wrong answer on both is 0,
        # not 0.75 from five unchecked dimensions scoring 1.0.
        self.assertEqual(bad["composite"], 0.0)
        self.assertFalse(bad["structural_recall"]["applicable"])

    def test_heading_text_uses_source_texts_and_penalises_none(self):
        from scoring import score_structural_quality

        feats = {"headings": {"present": True, "count": 1, "by_level": {"1": 1},
                              "texts": [{"text": "Results", "level": 1}]}}
        none = score_structural_quality(feats, {"headings": []})
        self.assertEqual(none["details"]["heading_text_match"]["score"], 0.0)
        empty = score_structural_quality(feats, {"headings": [{"text": "", "level": 1}]})
        self.assertEqual(empty["details"]["heading_text_match"]["score"], 0.0)
        hit = score_structural_quality(feats, {"headings": [{"text": "Results", "level": 1}]})
        self.assertEqual(hit["details"]["heading_text_match"]["score"], 1.0)

    def test_covered_cell_span_is_representation_not_meaning(self):
        from structure_v2 import score_structure

        want = {"table_cells": [{"table": 0, "row": 5, "col": 2, "text": "",
                                 "col_span": 3, "merged": True}]}
        html_style = {"structure": {"table_cells": [
            {"table": 0, "row": 5, "col": c, "text": "", "col_span": 1, "merged": True}
            for c in (2, 3, 4)
        ]}}
        self.assertEqual(score_structure(want, html_style)["score"], 1.0)
        unmerged = {"structure": {"table_cells": [
            {"table": 0, "row": 5, "col": 2, "text": "", "col_span": 1, "merged": False}
        ]}}
        self.assertEqual(score_structure(want, unmerged)["score"], 0.0)

    def test_track_change_type_synonyms_match(self):
        from scoring import score_structural_recall

        feats = {"track_changes": {"present": True, "count": 2,
                                   "types": {"insert": 1, "delete": 1}}}
        out = {"track_changes": [{"type": "insertion"}, {"type": "deletion"}]}
        self.assertEqual(score_structural_recall(feats, out)["per_feature"]["track_changes"], 1.0)


def _words(text, wrap=None):
    """Pandoc inlines for a phrase: Str/Space per word, optionally wrapped."""
    out = []
    for i, w in enumerate(text.split()):
        out += ([{"t": "Space"}] if i else []) + [{"t": "Str", "c": w}]
    return [{"t": wrap, "c": out}] if wrap else out


def _pandoc_cell(text, rowspan=1, colspan=1):
    attr = ["", [], []]
    return [attr, {"t": "AlignDefault"}, rowspan, colspan,
            [{"t": "Plain", "c": _words(text)}]]


def _pandoc_table(head, body):
    attr = ["", [], []]
    rows = lambda rs: [[attr, r] for r in rs]
    return {"t": "Table", "c": [attr, [None, []], [], [attr, rows(head)],
                                [[attr, 0, [], rows(body)]], [attr, []]]}


class AdapterMappingTests(unittest.TestCase):
    """Synthetic provider output -> adapter output, one fix per test."""

    def test_pandoc_reads_spreadsheets_slides_and_delimited_text(self):
        from adapters.pandoc_adapter import PandocAdapter

        self.assertLessEqual({"csv", "tsv", "pptx", "xlsx"}, PandocAdapter().supported_formats())

    def test_pandoc_comments_are_comments_not_paragraph_text(self):
        from adapters.pandoc_adapter import PandocAdapter

        start = lambda cid, body: {"t": "Span", "c": [
            ["", ["comment-start"], [["comment-id", cid], ["author", "Ann"], ["date", "2026-01-01T00:00:00Z"]]],
            _words(body)]}
        end = lambda cid, inner=(): {"t": "Span", "c": [["", ["comment-end"], [["comment-id", cid]]], list(inner)]}
        ast = {"blocks": [
            {"t": "Para", "c": _words("Keep") + [{"t": "Space"}, start("1", "Check date."),
             start("2", "Nested.")] + _words("the term") + [end("1", [end("2")]), {"t": "Space"}] + _words("ok")},
            {"t": "Para", "c": [start("3", "Never closed.")] + _words("tail")},
        ]}
        out = PandocAdapter().convert_ast(ast)
        self.assertEqual([t["text"] for t in out["text_elements"]], ["Keep the term ok", "tail"])
        got = {c["text"]: (c["author"], c["annotated_text"], c["anchored"]) for c in out["comments"]}
        self.assertEqual(got, {
            "Check date.": ("Ann", "the term", True),
            "Nested.": ("Ann", "the term", True),
            "Never closed.": ("Ann", "", False),
        })
        self.assertEqual(out["bookmarks"], [])
        expected = {"comment_anchors": [{"text": "Check date.", "author": "Ann",
                                         "annotated_text": "the term", "anchored": True}]}
        self.assertEqual(score_structure(expected, out)["score"], 1)

    def test_pandoc_comment_range_spans_paragraphs_and_cells(self):
        from adapters.structure import pandoc_structure
        from adapters.pandoc_adapter import PandocAdapter

        start = {"t": "Span", "c": [["", ["comment-start"], [["comment-id", "0"], ["author", "A"]]], _words("body")]}
        table = _pandoc_table([], [[_pandoc_cell("x"), _pandoc_cell("EUR 1")],
                                   [_pandoc_cell("y"), _pandoc_cell("EUR 2")]])
        cell = table["c"][4][0][3][0][1][1]
        cell[4][0]["c"] = [start] + cell[4][0]["c"]
        last = table["c"][4][0][3][1][1][1]
        last[4][0]["c"].append({"t": "Span", "c": [["", ["comment-end"], [["comment-id", "0"]]], []]})
        out = pandoc_structure({"blocks": [table]}, PandocAdapter()._parse_table)
        self.assertEqual(out["comment_anchors"][0]["annotated_text"], "EUR 1 y EUR 2")

    def test_pandoc_runs_join_words_that_share_formatting(self):
        from adapters.pandoc_adapter import PandocAdapter

        ast = {"blocks": [{"t": "Para", "c": _words("plain then") + [{"t": "Space"}]
                           + _words("two words", "Strong") + [{"t": "Space"}]
                           + _words("E=mc") + [{"t": "Superscript", "c": _words("2")}]}]}
        out = PandocAdapter().convert_ast(ast)
        runs = out["structure"]["runs"]
        self.assertIn({"text": "two words", "bold": True, "italic": False, "underline": False,
                       "strike": False, "code": False, "vertAlign": ""}, runs)
        self.assertEqual([r["text"] for r in runs if r["vertAlign"] == "superscript"], ["2"])
        expected = {"runs": [{"text": "two words", "bold": True}, {"text": "plain then", "bold": False},
                             {"text": "2", "vertAlign": "superscript"}]}
        self.assertEqual(score_structure(expected, out)["score"], 1)

    def test_pandoc_rowspan_keeps_later_cells_in_their_columns(self):
        from adapters.pandoc_adapter import PandocAdapter

        table = _pandoc_table(
            [[_pandoc_cell("A", rowspan=2), _pandoc_cell("E", colspan=2)],
             [_pandoc_cell("G"), _pandoc_cell("H")]],
            [[_pandoc_cell("1"), _pandoc_cell("2"), _pandoc_cell("3")]],
        )
        out = PandocAdapter().convert_ast({"blocks": [table]})
        cells = {(c["row"], c["col"]): c for c in out["structure"]["table_cells"]}
        self.assertEqual(cells[2, 2]["text"], "G")
        self.assertEqual(cells[2, 3]["text"], "H")
        self.assertTrue(cells[2, 1]["merged"])
        self.assertEqual(cells[1, 2]["col_span"], 2)
        self.assertEqual(out["tables"][0]["rows"][1][1]["text"], "G")

    def test_pandoc_slides_sheets_and_notes(self):
        from adapters.pandoc_adapter import PandocAdapter

        header = lambda ident, text: {"t": "Header", "c": [2, [ident, [], []], _words(text)]}
        notes = {"t": "Div", "c": [["", ["notes"], []], [{"t": "Para", "c": _words("Say hello")}]]}
        out = PandocAdapter().convert_ast({"blocks": [
            header("slide-1", "Intro"), {"t": "Para", "c": _words("Body")}, notes,
            header("slide-2", "End"),
        ]})
        s = out["structure"]
        self.assertEqual(s["containers"], [{"kind": "slide", "name": "Intro"}, {"kind": "slide", "name": "End"}])
        self.assertEqual(s["notes"], [{"scope": "Intro", "text": "Say hello"}])
        self.assertEqual(out["speaker_notes"], [{"text": "Say hello"}])
        self.assertNotIn("Say hello", [t["text"] for t in out["text_elements"]])
        out = PandocAdapter().convert_ast({"blocks": [
            header("sheet-1", "Main"), _pandoc_table([], [[_pandoc_cell("x")]]),
            header("sheet-2", "Other"), _pandoc_table([], [[_pandoc_cell("y")]]),
        ]})
        self.assertEqual(out["metadata"]["sheet_names"], ["Main", "Other"])
        self.assertEqual([(c["table"], c["scope"]) for c in out["structure"]["table_cells"]],
                         [(0, "Main"), (1, "Other")])
        # A heading the author wrote is not a container.
        out = PandocAdapter().convert_ast({"blocks": [header("intro", "Intro")]})
        self.assertEqual(out["structure"]["containers"], [])

    def test_markdown_list_items_group_into_their_list(self):
        out = markdown_output(
            "- a\n- b\n\n1. one\n2. two\n   - x\n   - y\n3. three\n\npara\n\n- c\n"
        )
        self.assertEqual(
            [(x["items"], x["ordered"], x["depth"]) for x in out["lists"]],
            [(["a", "b"], False, 1), (["one", "two", "x", "y", "three"], True, 2),
             (["c"], False, 1)],
        )
        self.assertEqual(
            [(x["text"], x["level"], x["ordered"]) for x in out["structure"]["list_items"]],
            [("a", 0, False), ("b", 0, False), ("one", 0, True), ("two", 0, True),
             ("x", 1, False), ("y", 1, False), ("three", 0, True), ("c", 0, False)],
        )

    def test_markitdown_formats_slides_notes_and_placeholder_header(self):
        from adapters.markitdown_adapter import MarkItDownAdapter

        self.assertLessEqual({"md", "tsv"}, MarkItDownAdapter().supported_formats())
        out = MarkItDownAdapter().convert_slides(
            "<!-- Slide number: 1 -->\n# Intro\nBody\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\n"
            "### Notes:\nSay hi\nthen go\n\n<!-- Slide number: 2 -->\n\n### Notes:\n\n"
            "<!-- Slide number: 3 -->\nNo title\n"
        )
        s = out["structure"]
        self.assertEqual([c["name"] for c in s["containers"]], ["Intro", "", ""])
        self.assertEqual(s["notes"], [{"scope": "Intro", "text": "Say hi then go"}])
        self.assertEqual(out["speaker_notes"], [{"text": "Say hi then go"}])
        self.assertEqual({c["scope"] for c in s["table_cells"]}, {"Intro"})
        self.assertNotIn("Notes:", [h["text"] for h in out["headings"]])
        md = "|  |  |\n| --- | --- |\n| Name | Game |\n| a | b |\n"
        out = markdown_output(md, placeholder_header=True)
        self.assertEqual(out["structure"]["table_cells"][0], {
            "table": 0, "scope": "", "row": 1, "col": 1, "text": "Name",
            "col_span": 1, "merged": False})
        self.assertEqual(out["tables"][0]["row_count"], 1)
        # Without the provider flag an empty header row is a real row.
        self.assertEqual(markdown_output(md)["structure"]["table_cells"][0]["text"], "")

    def test_unstructured_lists_heading_levels_slides_and_notes(self):
        from adapters.unstructured_adapter import UnstructuredAdapter

        class Meta(SimpleNamespace):
            def to_dict(self):
                return {k: v for k, v in vars(self).items() if v is not None}

        def el(kind, text, page=None, depth=None):
            cls = type(kind, (), {"__str__": lambda self: text})
            obj = cls()
            obj.metadata = Meta(page_number=page, category_depth=depth)
            return obj

        out = UnstructuredAdapter().convert_elements([
            el("Title", "Plan", depth=0), el("ListItem", "Frontend", depth=0),
            el("ListItem", "React", depth=1), el("Title", "Timeline", depth=1),
            el("ListItem", "Later", depth=0),
        ], Path("x.docx"))
        self.assertEqual(out["headings"], [{"text": "Plan", "level": 1}, {"text": "Timeline", "level": 2}])
        self.assertEqual(out["structure"]["list_items"], [
            {"text": "Frontend", "level": 0}, {"text": "React", "level": 1}, {"text": "Later", "level": 0}])
        self.assertEqual([(x["items"], x["depth"]) for x in out["lists"]],
                         [(["Frontend", "React"], 2), (["Later"], 1)])
        self.assertEqual([e["type"] for e in out["structure"]["element_order"]],
                         ["heading", "list", "heading", "list"])

        plain = [el("Title", "Intro", 1, 0), el("Title", "Point", 1, 1), el("PageBreak", "", 1),
                 el("NarrativeText", "Body", 2, 0), el("PageBreak", "", 2)]
        noted = [el("NarrativeText", "Say hi", 1, 0)] + plain
        notes = UnstructuredAdapter._slide_notes(plain, noted)
        self.assertEqual(notes, {1: "Say hi"})
        out = UnstructuredAdapter().convert_elements(plain, Path("x.pptx"), notes)
        self.assertEqual(out["structure"]["containers"], [
            {"kind": "slide", "name": "Intro"}, {"kind": "slide", "name": ""},
            {"kind": "slide", "name": ""}])
        self.assertEqual(out["structure"]["notes"], [{"scope": "Intro", "text": "Say hi"}])
        self.assertEqual(out["speaker_notes"], [{"text": "Say hi"}])
        self.assertNotIn("", [t["text"] for t in out["text_elements"]])

    def test_docling_comments_notes_furniture_lists_and_spans(self):
        from adapters.docling_adapter import DoclingAdapter

        ref = lambda kind, i: {"$ref": f"#/{kind}/{i}"}
        text = lambda i, value, parent, label="text", layer="body", **kw: {
            "self_ref": f"#/texts/{i}", "parent": parent, "children": kw.pop("children", []),
            "content_layer": layer, "label": label, "text": value, "orig": value, **kw}
        group = lambda i, label, name, parent, children, layer="body": {
            "self_ref": f"#/groups/{i}", "parent": parent, "children": children,
            "content_layer": layer, "label": label, "name": name}
        body = {"self_ref": "#/body", "children": [ref("groups", 0), ref("texts", 0),
                ref("groups", 1), ref("groups", 3), ref("tables", 0)], "label": "unspecified"}
        doc = {
            "body": body,
            "texts": [
                text(0, "Keep the date.", ref("body", 0), comments=[ref("groups", 3)]),
                text(1, "One", ref("groups", 1), "list_item", children=[ref("groups", 2)]),
                text(2, "Nested", ref("groups", 2), "list_item"),
                text(3, "Two", ref("groups", 1), "list_item"),
                text(4, "[author: Ann Lee (AL), time: 2026-01-01T00:00:00.000+00:00]: Check it.",
                     ref("groups", 3), layer="notes"),
                text(5, "Header text", ref("groups", 0), layer="furniture"),
            ],
            "groups": [
                group(0, "section", "page header", ref("body", 0), [ref("texts", 5)], "furniture"),
                group(1, "list", "list", ref("body", 0), [ref("texts", 1), ref("texts", 3)]),
                group(2, "list", "list", ref("texts", 1), [ref("texts", 2)]),
                group(3, "comment_section", "comment-0", ref("body", 0), [ref("texts", 4)], "notes"),
            ],
            "tables": [{"self_ref": "#/tables/0", "prov": [], "data": {"num_rows": 3, "table_cells": [
                {"start_row_offset_idx": 0, "start_col_offset_idx": 0, "row_span": 2, "col_span": 1,
                 "text": "A", "column_header": True},
                {"start_row_offset_idx": 0, "start_col_offset_idx": 1, "row_span": 1, "col_span": 2,
                 "text": "E", "column_header": True},
                {"start_row_offset_idx": 1, "start_col_offset_idx": 1, "row_span": 1, "col_span": 1, "text": "G"},
                {"start_row_offset_idx": 2, "start_col_offset_idx": 0, "row_span": 1, "col_span": 1, "text": "1"},
            ]}}],
            "pictures": [],
        }
        document = SimpleNamespace(export_to_dict=lambda: doc, export_to_markdown=lambda: "Keep the date.")
        out = DoclingAdapter().convert_document(document)
        self.assertEqual(out["comments"], [{"text": "Check it.", "author": "Ann Lee",
                                            "annotated_text": "Keep the date.", "anchored": True, "scope": ""}])
        self.assertEqual(out["headers_footers"], [{"type": "header", "text": "Header text"}])
        self.assertEqual(out["lists"], [{"items": ["One", "Nested", "Two"], "ordered": False, "depth": 2}])
        self.assertEqual(out["tables"][0]["row_count"], 2)
        cells = {(c["row"], c["col"]): c for c in out["structure"]["table_cells"]}
        self.assertTrue(cells[2, 1]["merged"] and cells[1, 3]["merged"])
        self.assertEqual(cells[2, 2]["text"], "G")

        slide = {"self_ref": "#/groups/0", "parent": ref("body", 0), "children": [ref("texts", 0), ref("texts", 1)],
                 "content_layer": "body", "label": "chapter", "name": "slide-0"}
        doc = {"body": {"self_ref": "#/body", "children": [ref("groups", 0)]}, "groups": [slide],
               "texts": [text(0, "Intro", ref("groups", 0), "title"),
                         text(1, "Say hi", ref("groups", 0), layer="notes")],
               "tables": [], "pictures": []}
        out = DoclingAdapter().convert_document(SimpleNamespace(export_to_dict=lambda: doc,
                                                                export_to_markdown=lambda: "# Intro"))
        self.assertEqual(out["structure"]["notes"], [{"scope": "Intro", "text": "Say hi"}])
        self.assertEqual(out["speaker_notes"], [{"text": "Say hi"}])

    def test_kreuzberg_markdown_links_and_header_row_count(self):
        from adapters.kreuzberg_adapter import KreuzbergAdapter

        cell = lambda r, c, text, header=False: {"content": text, "row": r, "col": c,
                                                  "row_span": 1, "col_span": 1, "is_header": header}
        nodes = [
            {"content": {"node_type": "paragraph", "text": "See Docs"}},
            {"content": {"node_type": "table", "grid": {"rows": 3, "cols": 1, "cells": [
                cell(0, 0, "Name", True), cell(1, 0, "a"), cell(2, 0, "b")]}}},
        ]
        result = SimpleNamespace(
            content="See [Docs](https://example.com/docs)\n\n| Name |\n| --- |\n| a |\n| b |\n",
            tables=[SimpleNamespace(cells=[["Name"], ["a"], ["b"]], markdown="| Name |\n| --- |\n| a |\n| b |")],
            images=[], metadata={}, document={"nodes": nodes},
        )
        out = KreuzbergAdapter().convert_result(result, Path("x.docx"))
        self.assertEqual(out["structure"]["hyperlinks"], [{"text": "Docs", "url": "https://example.com/docs"}])
        self.assertEqual(out["tables"][0]["row_count"], 2)
        nodes[1]["content"]["grid"]["cells"][0]["is_header"] = False
        out = KreuzbergAdapter().convert_result(result, Path("x.docx"))
        self.assertEqual(out["tables"][0]["row_count"], 3)

    def test_liteparse_pages_are_slides_and_list_blocks_group(self):
        block = lambda kind, text=None, **kw: SimpleNamespace(
            kind=kind, text=text, header=None, rows=kw.get("rows"), bold=False,
            italic=False, level=kw.get("level"), ordered=kw.get("ordered", False))
        page = lambda blocks, md="": SimpleNamespace(
            markdown=md, text="", blocks=blocks, annotations=[], text_items=[])
        c = lambda value: SimpleNamespace(text=value)
        pages = [
            page([block("heading", "Intro", level=1), block("list_item", "a", level=0),
                  block("list_item", "b", level=1), block("text", "gap"),
                  block("list_item", "c", level=0)]),
            page([block("list_item", "next page", level=0),
                  block("table", rows=[[c("x"), c("y")]])]),
            page([], "```text\n\n```"),
        ]
        out = LiteParseAdapter().convert_result(SimpleNamespace(pages=pages, images=[]), Path("deck.pptx"))
        s = out["structure"]
        self.assertEqual(s["containers"], [{"kind": "slide", "name": n} for n in ("Intro", "", "")])
        self.assertEqual({c["scope"] for c in s["table_cells"]}, {""})
        self.assertEqual([(x["items"], x["depth"]) for x in out["lists"]],
                         [(["a", "b"], 2), (["c"], 1), (["next page"], 1)])
        self.assertEqual([e["type"] for e in s["element_order"]],
                         ["heading", "list", "text", "list", "list", "table"])
        out = LiteParseAdapter().convert_result(SimpleNamespace(pages=pages, images=[]), Path("doc.docx"))
        self.assertNotIn("containers", out["structure"])
        blank = LiteParseAdapter().convert_result(
            SimpleNamespace(pages=[page([], "```text\n\n```")] * 3, images=[]), Path("blank.pptx"))
        self.assertTrue(has_extracted_content(blank))

    def test_error_text_keeps_the_cause_at_the_end(self):
        noise = "conversion error: Command failed: " + "Fontconfig warning: x\n" * 40
        text = runner._error_text(RuntimeError(noise + "Error: source file could not be loaded"))
        self.assertLessEqual(len(text), 500)
        self.assertTrue(text.startswith("conversion error"))
        self.assertTrue(text.endswith("source file could not be loaded"))
        self.assertEqual(runner._error_text(RuntimeError("short")), "short")

    def test_formatted_runs_reach_text_elements_like_the_reference(self):
        from adapters.structure import attach_formatting
        from scoring import score_feature_detection

        out = markdown_output("Plain **bold words** and *it*.\n\nNothing here.\n")
        first, second = out["text_elements"]
        self.assertEqual([(r["text"], r["bold"], r["italic"]) for r in first["formatting"]],
                         [("bold words", True, False), ("it", False, True)])
        self.assertEqual(second["formatting"], [])
        styles = {"styles": {"present": True}}
        self.assertTrue(score_feature_detection(styles, out)["checks"]["styles"])
        self.assertFalse(score_feature_detection(styles, markdown_output("plain"))["checks"]["styles"])
        elements = attach_formatting([{"text": "a key phrase here"}, {"text": "other"}],
                                     [{"text": "key phrase", "bold": True}, {"text": "other", "bold": False}])
        self.assertEqual(elements[0]["formatting"], [{"text": "key phrase", "bold": True}])
        self.assertEqual(elements[1]["formatting"], [])
        run = StructuralTests._reducto_run([StructuralTests._rb("Text", "Some <b>bold</b> text.")])
        out = ReductoAdapter().convert_json(run, Path("x.docx"))
        self.assertEqual([r["text"] for r in out["text_elements"][0]["formatting"]], ["bold"])

    def test_llamaparse_raw_answers_are_kept_and_reused(self):
        import os
        import tempfile
        from unittest import mock

        page = {"items": [{"type": "text", "value": "Hello"}], "md": "Hello"}
        calls = []

        class Fake:
            def __init__(self, json_result=None, docs=None, error=None):
                self.json_result, self.docs, self.error = json_result, docs, error

            def get_json_result(self, path):
                calls.append(("json", path))
                return self.json_result

            def load_data(self, path):
                calls.append(("md", path))
                if self.error:
                    raise RuntimeError(self.error)
                return self.docs

        class Adapter(LlamaParseAdapter):
            fake = None

            def _parser(self):
                return self.fake

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "doc.docx"
            src.write_bytes(b"one")
            raw = Path(tmp) / "raw"
            env = {"LLAMAPARSE_RAW_DIR": str(raw), "LLAMA_CLOUD_API_KEY": "x",
                   "LLAMAPARSE_REUSE_RAW": ""}
            with mock.patch.dict(os.environ, env):
                adapter = Adapter()
                adapter.fake = Fake(json_result=[{"pages": [page]}])
                first = adapter.parse(src)
                self.assertEqual(len(calls), 1)
                self.assertEqual(len(list(raw.glob("doc.docx.*.json"))), 1)
                self.assertFalse(adapter.provider_config()["raw_reuse"])
                # Reuse: no request, same mapping, even without an API key.
                os.environ.update(LLAMAPARSE_REUSE_RAW="1", LLAMA_CLOUD_API_KEY="")
                adapter.fake = None
                self.assertEqual(adapter.parse(src), first)
                self.assertEqual(len(calls), 1)
                self.assertTrue(adapter.provider_config()["raw_reuse"])
                # Different bytes are a different key: a fresh request.
                os.environ.update(LLAMA_CLOUD_API_KEY="x")
                src.write_bytes(b"two")
                adapter.fake = Fake(json_result=[], docs=[SimpleNamespace(text="# Title")])
                out = adapter.parse(src)
                self.assertEqual(out["headings"], [{"text": "Title", "level": 1}])
                self.assertEqual(adapter.parse(src), out)  # reused
                self.assertEqual(len(calls), 3)  # json then markdown, once
                # Failures are kept and reproduced by a remap.
                src.write_bytes(b"three")
                adapter.fake = Fake(json_result=None, error="credits exhausted")
                with self.assertRaisesRegex(RuntimeError, "credits exhausted"):
                    adapter.parse(src)
                adapter.fake = None
                with self.assertRaisesRegex(RuntimeError, "credits exhausted"):
                    adapter.parse(src)
                self.assertEqual(len(list(raw.glob("doc.docx.*.json"))), 3)


if __name__ == "__main__":
    unittest.main()
