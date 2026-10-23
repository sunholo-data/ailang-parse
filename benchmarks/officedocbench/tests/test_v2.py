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
        self.assertEqual(nested["features"]["lists"]["count"], 1)
        self.assertEqual(nested["features"]["lists"]["max_depth"], 3)

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
        self.assertEqual(truth["features"]["lists"]["count"], 2)
        self.assertEqual(truth["features"]["lists"]["max_depth"], 2)
        complex_html = audited(
            runner._find_test_file("test_complex.html"), {"features": {}}
        )
        self.assertEqual(complex_html["features"]["tables"]["count"], 3)

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


if __name__ == "__main__":
    unittest.main()
