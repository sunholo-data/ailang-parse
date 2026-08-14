---
name: verify-docs
description: 'Verify generated Office documents (DOCX, PPTX, XLSX, ODT, ODP, ODS, HTML) are valid and open correctly. Use when: user asks to verify generated files, check document output quality, validate Office files, run the verification loop, test generated documents, check if files open in Keynote/Word/Numbers, or after changing any generator code (docx_generator, pptx_generator, xlsx_generator, odt_generator, odp_generator, ods_generator, html_generator). Also use when user says "verify", "check the files", "do they open", "run verification", or "test the output".'
user-invokable: true
---

# Verify Generated Documents

Run the document generation verification loop to check that generated Office files are structurally valid, open in Python libraries, and roundtrip through AILANG Parse correctly.

## What This Does

Three levels of verification on all files in `data/examples/`:

1. **L1 Structure** — ZIP well-formedness, required entries present, XML validity
2. **L2 Library** — python-docx, python-pptx, openpyxl open without errors, AND
   the DOCX table grid is inspected: every row must span exactly the columns
   `w:tblGrid` declares, and every cell must be iterable
3. **L2b Parts** — DOCX package wiring (declared, related, present)
4. **L4 Roundtrip** — Parse through AILANG Parse, verify blocks are preserved

**Opening a file is not verifying it.** LibreOffice tolerates malformed table
geometry that python-docx rejects and Word offers to repair, so invalid output
shipped twice while every check was green. Anything generated must have its
structure read back, which is what the L2 grid assertion does.

## Usage

Run the verification script:

```bash
uv run --with python-pptx --with openpyxl --with python-docx benchmarks/verify_generated.py
```

### Also run the round-trip suite

`verify_generated.py` only covers `data/examples/`. After any parser or
generator change also run:

```bash
uv run benchmarks/roundtrip_check.py    # parse -> markdown -> parse, 101 files
```

It asserts table dimensions, cell text, grid width and heading sequence survive
a trip through markdown — the writer the office suite cannot see, because every
golden is JSON.

### Building a test document

The cheapest way to exercise the generators is to write markdown and convert
it: front matter, inline formatting, links, images, fenced code, blockquotes,
nested lists and aligned/spanned tables all round-trip. Headers, footers,
comments and tracked changes are not expressible in markdown — convert an
existing document that has them instead.

### With Regeneration

If generator code has changed, regenerate demo files first, then verify:

```bash
bash .claude/skills/verify-docs/scripts/regen_and_verify.sh
```

### Quick Verify Only (no regen)

```bash
bash .claude/skills/verify-docs/scripts/verify_only.sh
```

## Instructions

When this skill is invoked:

1. Check if the user passed `--regen` or asked to regenerate files
2. If regenerating: run `scripts/regen_and_verify.sh` which generates fresh demo files across all formats then verifies
3. If verify only: run `scripts/verify_only.sh`
4. Report results clearly — highlight any FAIL or WARN items
5. If there are failures, investigate the specific XML/structure issue and suggest fixes
6. After fixing generator code, re-run verification to confirm the fix

## Interpreting Results

- **PASS** — File is valid at that level
- **WARN** — Minor issue (e.g., ODF mimetype compression — AILANG stdlib limitation, not fixable by us)
- **FAIL** — File won't open correctly in target applications. Needs a fix in the generator code.

## Known Limitations

- ODF files (ODT/ODP/ODS) have compressed mimetype entries — this is an AILANG `createArchive` limitation (no store/no-compress flag). Shows as WARN, not FAIL.
- Level 3 (native app smoke test) is manual — open files in Keynote/Word/Numbers to verify visually.
