# DocParse v0.3.0 — Parser Coverage Expansion

**Status**: Planned
**Theme**: Extract everything competitors miss from Office documents

## Goals

1. Expand Office parser coverage to capture all structural metadata
2. Add test files for every feature gap identified
3. Maintain 100% office benchmark baseline after each change

## Features

### 1. PPTX Speaker Notes

Read `ppt/notesSlides/notesSlideN.xml` for each slide and include as `SectionBlock(kind: "notes")`.

Currently the parser reads slides but ignores notes. Speaker notes are a common extraction gap — Docling and Unstructured both miss them.

**Files**: `docparse/services/pptx_parser.ail`, `docparse/services/zip_extract.ail`
**Test file**: Create `speaker_notes.pptx` with slides containing notes

### 2. Real Footnote/Endnote Content

Current test files (`docx-hdrftr.docx`) only have boilerplate footnote separators. Create test files with actual footnote and endnote text content to validate the extraction pipeline end-to-end.

**Files**: New test file `footnotes_real.docx`
**Parser**: Pipeline already wired — just needs test data to verify

### 3. Insert/Delete Track Changes Test Coverage

Only move-to/move-from track changes have dedicated test files. Create test files exercising:
- Simple insertions
- Simple deletions
- Mixed insert/delete in same paragraph
- Formatted track changes (bold/italic within changes)

**Files**: New test file `track_changes_insert_delete.docx`
**Parser**: `docparse/services/docx_parser.ail` already handles these types

### 4. Nested Lists

Test and validate extraction of:
- Multi-level numbered lists
- Multi-level bullet lists
- Mixed numbered/bullet nesting

**Files**: New test file `nested_lists.docx`
**Parser**: May need updates to `docx_parser.ail` for list level tracking

### 5. Metadata Completeness

Extract additional metadata from Office documents:
- **Page count** from `docProps/app.xml` (`<Pages>` element)
- **Slide count** from `docProps/app.xml` (`<Slides>` element)
- **Sheet names** already extracted, verify completeness
- **Custom properties** from `docProps/custom.xml`

**Files**: `docparse/services/docx_parser.ail` (`parseDocxMetadata`), `docparse/services/zip_extract.ail`

### 6. XLSX Chart Detection

Detect presence of charts in XLSX files. Don't need to extract chart data (that's AI territory), but identify that charts exist and report them as `ImageBlock` placeholders.

**Files**: `docparse/services/xlsx_parser.ail`
**Test file**: Create `charts.xlsx` with embedded charts

## Test Strategy

For each feature:
1. Create minimal test file exercising the feature
2. Parse with `ailang run` and inspect output
3. Generate golden output: `bash benchmarks/generate_golden.sh`
4. Run benchmark: `uv run benchmarks/run_benchmarks.py --suite office`
5. Verify 100% baseline maintained

## Success Criteria

- 24+ golden benchmark files (up from 18)
- PPTX speaker notes extracted in benchmark output
- Real footnote content appears in golden output
- 100% office benchmark maintained throughout
- Feature gap vs Docling widens (more features DocParse extracts that Docling doesn't)

## Dependencies

- Microsoft Office or LibreOffice for creating test files (or python-docx/openpyxl)
- No AILANG language changes needed
