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
        with self.assertRaisesRegex(RuntimeError, "no blocks"):
            ReductoAdapter().convert_json(self._reducto_run([]), Path("input.docx"))

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
                "benchmark_version": "2.0.0",
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

    def test_track_change_type_synonyms_match(self):
        from scoring import score_structural_recall

        feats = {"track_changes": {"present": True, "count": 2,
                                   "types": {"insert": 1, "delete": 1}}}
        out = {"track_changes": [{"type": "insertion"}, {"type": "deletion"}]}
        self.assertEqual(score_structural_recall(feats, out)["per_feature"]["track_changes"], 1.0)


if __name__ == "__main__":
    unittest.main()
