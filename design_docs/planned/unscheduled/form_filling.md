# Design Doc: Form-Field Read & Fill

**Status**: Planned (unscheduled)
**Date**: 2026-05-18
**Author**: Mark + Claude
**Source**: User request — "can ailang parse help with filling in forms such as the .rtf example we have? and or other formats?". Today `docparse` extracts the *visible value* of form fields as plain text (e.g. RTF `\fldrslt`, DOCX `w:sdt/w:sdtContent`), but it loses the field identity (name, kind, options) and has no way to write values back into a template.

**Related**:
- [v0.18.0 Legal-Grade DOCX Write-Back](../v0_18_0/v0_18_0_legal_docx_writeback.md) — adds a DOCX writer module. Form-fill reuses the same OOXML edit machinery but operates on an **existing** `.docx` rather than emitting one from scratch.
- [v0.11.0 Structured Extraction](../v0_11_0/v0_11_0_structured_extraction.md) — the inverse direction: schema-driven extraction *out of* documents. Form-fill is schema-driven write *into* documents.

---

## Problem

Users have templates — supplier onboarding forms (`.docx`), legacy `.rtf` claim forms, fillable PDF tax returns — and want to programmatically populate them from a structured value source (LLM output, database row, JSON payload). Today `docparse` cannot help with this loop:

1. **Field identity is dropped on parse.** A DOCX content control with `<w:tag w:val="invoice_number"/>` and current value `"INV-1042"` parses to a `TextBlock { text: "INV-1042" }`. The tag name (`invoice_number`) is the binding handle the caller would use to fill it, and we discard it.
2. **No write path for RTF.** RTF is read-only ([rtf_parser.ail](../../../docparse/services/rtf_parser.ail) exists; there is no `rtf_generator.ail`). Even if we knew the field identities we couldn't emit a filled `.rtf`.
3. **No template-fill path for DOCX.** [docx_generator.ail](../../../docparse/services/docx_generator.ail) emits a `.docx` from scratch from the Block ADT — it does not ingest a template `.docx`, locate `w:sdt` controls by tag, and rewrite their `w:sdtContent` in place. That round-trip is what users actually want for forms (preserve all the styling, page layout, signatures, instructions; just change the answers).
4. **PDF forms are entirely out of band.** AcroForm and XFA fields aren't visible to the multimodal AI extraction path at all — they live in the PDF object graph, parallel to the page content.

Without closing this, callers building "fill this form from a JSON payload" workflows have to drop down to `python-docx` / `docx-templates` / `pdf-lib` / hand-written RTF, defeating the point of using `docparse` for the parse half.

---

## Non-Goals

- **Building forms from scratch.** Designing a brand-new form (laying out fields, captions, validation, tab order) is a document-authoring problem; users can already do that in Word/LibreOffice. We fill existing templates.
- **A general form-authoring DSL.** No "describe a form in YAML and we emit a `.docx`". The template is the form.
- **Validation / submission.** We do not enforce that filled values match field constraints (max length, regex, enum), do not submit the filled form anywhere, do not produce audit trails. The caller owns validation.
- **XFA (dynamic XML PDF forms).** XFA is an Adobe-proprietary XML form layer layered on top of PDF, deprecated by the PDF 2.0 standard and unsupported by most modern viewers. Out of scope. AcroForm (the static-PDF widget annotation form layer) is in scope as a stretch goal — see Phase 3.
- **Encrypted PDFs.** Caller decrypts before passing in, or we fail closed.
- **Form-field comments / track-changes annotation.** Filling a field is not a tracked change. If a caller wants the fill to appear as `<w:ins>`, they compose this feature with v0.18.0's tracked-changes write-back — but that composition is the caller's responsibility, not a default of this feature.

---

## Format Landscape

Where forms live in each format we already parse:

| Format | Form mechanism | Spec ref | Parse status | Fill status |
|---|---|---|---|---|
| **DOCX** | `w:sdt` content controls (modern); legacy `w:fldChar`/`FORMTEXT` field codes | ECMA-376 §17.5.2 (sdt), §17.16 (fields) | Visible value extracted as TextBlock; identity lost | None |
| **RTF** | `\field { \fldinst { FORMTEXT } } { \fldrslt value }` and legacy `{\*\formfield ...}` | RTF Spec 1.9.1, p.214+ | `\fldrslt` extracted as text; `\fldinst` skipped | None (no RTF generator at all) |
| **PDF (AcroForm)** | Widget annotations (`/Subtype /Widget`) on each page, with field hierarchy in `/AcroForm` catalog entry | PDF 2.0 §12.7 | None — multimodal path can't see them | None |
| **PDF (XFA)** | Embedded XML in `/AcroForm/XFA` | Adobe XFA 3.3 (deprecated) | None | Out of scope |
| **ODT** | `<form:form>` elements with `<form:text>`, `<form:checkbox>`, etc. | OpenDocument 1.3 §13 | None — ODT parser walks text content only | None |
| **HTML** | `<form>` / `<input>` / `<select>` | HTML Living Standard | None — HTML parser strips form controls | None |

**Coverage choice.** DOCX content controls are the highest-value target by a wide margin (Word is where business forms live; `w:sdt` is the modern, structured mechanism; ECMA-376 is open and stable). RTF is a smaller audience but cheap to add because the format is plain text — no zip container, no XML. PDF AcroForm is the most-requested but the heaviest lift; it gates on a real PDF reader/writer we don't have. ODT and HTML are tracked here for completeness but deferred.

---

## Block ADT Change

Today the Block ADT ([document.ail:29](../../../docparse/types/document.ail#L29)) collapses field values into `TextBlock`. We add a dedicated variant so field identity survives the parse:

```ailang
| FormFieldBlock({
    name: string,        -- binding handle (DOCX w:tag, RTF \fldinst result-name, PDF /T)
    kind: string,        -- "text" | "checkbox" | "dropdown" | "date" | "radio" | "signature"
    value: string,       -- current value as displayed; "" if unfilled
    options: [string],   -- enum values for dropdown/radio; [] otherwise
    placeholder: string, -- prompt / hint text shown when empty
    required: bool       -- format-specific; best-effort
  })
```

**Why a new variant rather than extending `TextBlock`.** A `TextBlock` is body prose; a `FormFieldBlock` is a structured binding site that happens to render text. Conflating them makes the type system stop helping us — generators have to branch on a magic flag, callers iterating "all body text" pick up form values they didn't ask for, and the round-trip property (`parse → fill → emit → re-parse → same identity`) becomes informal.

**Generator fallback.** Generators that don't support form semantics (Markdown, HTML, plain text, PPTX, XLSX) render `FormFieldBlock` as the visible `value` text — same shape as the existing `LinkBlock` fallback contract.

**Helpers** added alongside existing `isHeading` / `isTable`:

```ailang
export pure func isFormField(block: Block) -> bool
export pure func formFieldsByName(blocks: [Block]) -> [(string, FormFieldBlock)]
```

`formFieldsByName` walks the Block tree (including `SectionBlock`) and returns a flat list — this is the data shape callers want for "give me the form schema".

---

## Parser Changes

### DOCX ([docx_parser.ail](../../../docparse/services/docx_parser.ail))

`w:sdt` is already recognised (line 158); today we descend into `w:sdtContent` and treat the contents as text. New behaviour:

1. Read `w:sdtPr/w:tag/@w:val` as `name`. If absent, fall back to `w:sdtPr/w:alias/@w:val`. If both absent, synthesise `sdt_<index>` so the field is still addressable.
2. Detect kind from `w:sdtPr` children:
   - `w:checkbox` → `"checkbox"`, value is `"true"`/`"false"` from `w:checkbox/w:checked/@w:val`.
   - `w:dropDownList` → `"dropdown"`, options from `w:listItem/@w:value` entries.
   - `w:date` → `"date"`, value normalised via `w:date/@w:fullDate`.
   - `w:picture` → `"signature"` if `w:sdtPr/w:alias` matches `/sign/i` heuristic, else not emitted as a form field (it's an image embed).
   - Default → `"text"`.
3. Read `w:sdtPr/w:placeholder/w:docPart` → resolve to glossary doc part → extract placeholder text.
4. `required` is **not** in the OOXML spec for SDTs (CustomXML data binding has it via XPath; we don't parse the binding). Default `false`. Flagged in docs.
5. Emit a `FormFieldBlock` instead of descending into `w:sdtContent` as a normal paragraph. (Body-level SDTs that wrap whole paragraphs/tables are tracked separately — see Open Questions.)

Legacy `w:fldChar` form fields (`FORMTEXT`, `FORMCHECKBOX`, `FORMDROPDOWN`) are a Word 2003-era mechanism still found in old templates. Parse path: scan for the `begin`/`separate`/`end` triplet, read the instruction text between `begin` and `separate` (e.g. `FORMTEXT`), read the result text between `separate` and `end`. Lower priority than SDTs; phase 2.

### RTF ([rtf_parser.ail](../../../docparse/services/rtf_parser.ail))

[rtf_parser.ail:152](../../../docparse/services/rtf_parser.ail#L152) already special-cases `fldinst`/`fldrslt`/`field`; today both halves get folded into text. New behaviour:

- When entering a `\field` group, capture the `\fldinst` instruction string (e.g. `FORMTEXT "Enter name"` or `HYPERLINK "https://..."`).
- If the instruction is `FORMTEXT`, `FORMCHECKBOX`, or `FORMDROPDOWN`, emit a `FormFieldBlock`:
  - `name`: derived from `{\*\bkmkstart bookmark_name}` immediately preceding the field — RTF's idiomatic binding mechanism. If absent, synthesise `field_<index>`.
  - `kind`: `"text"` / `"checkbox"` / `"dropdown"`.
  - `value`: contents of `\fldrslt` group.
  - `placeholder`: quoted argument of `FORMTEXT`, e.g. `FORMTEXT "Enter name"` → `"Enter name"`.
- `HYPERLINK` continues to emit a `LinkBlock` (existing behaviour preserved).
- Legacy `{\*\formfield ...}` blocks: phase 2.

### PDF AcroForm — stretch

Needs a PDF object-graph reader. The annotation work in [pdf_annotations.md](pdf_annotations.md) lays groundwork — same indirect-object scanning, same `/T` field name extraction, plus per-page `/Annots` walking to pair widgets with field dictionaries in `/AcroForm/Fields`. Defer until that PDF reader stabilises.

---

## Fill Path

### DOCX Template Fill (`docparse/docx/fill.ail`)

This is a new module. Public API:

```ailang
export func fillDocx(
  templatePath: string,
  values: [(string, string)],   -- (field name, new value) pairs
  outputPath: string
) -> Result[FillReport, FillError] ! {FS}

export type FillReport = {
  filled: [string],     -- field names that were updated
  unfilled: [string],   -- field names in template but absent from `values`
  unknown: [string]     -- names in `values` that don't match any field
}
```

Algorithm:

1. Unzip the template (`std/zip`).
2. Parse `word/document.xml` with `std/xml`.
3. Walk the tree, for each `w:sdt`:
   - Read `w:sdtPr/w:tag/@w:val` (or alias fallback). Skip if no binding name.
   - If `values` contains this name, **replace `w:sdtContent`**:
     - For `text`: clear children, insert `<w:r><w:t xml:space="preserve">$value</w:t></w:r>`. Preserve the original `<w:rPr>` if present so styling survives.
     - For `checkbox`: rewrite `w:sdtPr/w:checkbox/w:checked/@w:val` and replace the rendered glyph in `w:sdtContent` (`☒` / `☐`).
     - For `dropdown`: validate that the new value matches a `w:listItem/@w:value`; if not, return `FillError::ValueNotInOptions`.
     - For `date`: rewrite `w:sdtPr/w:date/@w:fullDate` to ISO 8601 and the rendered text to the date format specified in `w:date/w:dateFormat`.
4. Re-serialise XML, repack zip, write to `outputPath`.
5. Return `FillReport` so callers can detect drift between schema and template.

**Why edit XML in place rather than regenerate.** Templates carry styling, page setup, section breaks, headers/footers, images, signature blocks, embedded fonts, and custom XML metadata that no `Block` ADT round-trip will preserve cleanly. The `w:sdt` is a surgical hook designed for exactly this; using it as designed gives us byte-stable output everywhere except the rewritten controls.

### RTF Template Fill (`docparse/services/rtf_generator.ail`)

RTF is text — no zip, no XML. A targeted edit module rather than a full generator:

```ailang
export func fillRtf(
  templatePath: string,
  values: [(string, string)],
  outputPath: string
) -> Result[FillReport, FillError] ! {FS}
```

Algorithm: tokenise the RTF, walk groups, find `\field` groups whose preceding bookmark name matches a key in `values`, replace the `\fldrslt` group contents with `{\fldrslt <escaped-value>}`. Escape `\`, `{`, `}`, and non-ASCII characters as `\'XX` hex or `\uNNNN?` Unicode escapes per RTF spec §7.

A *full* RTF generator (Block ADT → `.rtf`) is a separate, larger piece of work and not needed for form-fill. Out of scope for this design doc.

---

## CLI Surface

Add two flags to `docparse`:

```bash
# Show the form schema of a template — what fields exist, what kinds, what current values
./bin/docparse template.docx --form-schema
# → JSON list of FormFieldBlock entries

# Fill a template from a values JSON file
./bin/docparse template.docx --fill values.json --out filled.docx
```

`values.json` shape:

```json
{
  "invoice_number": "INV-1042",
  "issue_date": "2026-05-18",
  "tax_exempt": true,
  "billing_country": "United Kingdom"
}
```

The CLI returns a non-zero exit and prints the `FillReport` to stderr on any unknown / unfilled field, unless `--allow-partial` is passed. This is the same shape as `--check`'s exit-code contract elsewhere in the CLI.

---

## SDK Surface

Each SDK gains two functions, thin wrappers over the API endpoint:

```python
# Python
client.form_schema(path="template.docx")
client.fill_form(path="template.docx", values={"invoice_number": "INV-1042"})
```

The API server gets two new routes:

```
GET  /v1/forms/schema   (multipart upload of template)
POST /v1/forms/fill     (multipart upload of template + JSON body of values)
```

These are billable on the same per-file metering as `parse_file`. Pricing TBD — likely the same tier as parsing since the heavy lifting is identical (unzip + XML walk).

---

## Phasing

**Phase 1 — DOCX read + fill (the core 80%)**
- `FormFieldBlock` ADT variant + helpers
- DOCX parser emits `FormFieldBlock` for `w:sdt` (text, checkbox, dropdown, date)
- `docparse/docx/fill.ail` with `fillDocx`
- CLI `--form-schema` and `--fill`
- Golden tests: round-trip a known template (`data/test_files/forms/sample_form.docx`)

**Phase 2 — RTF + legacy DOCX fields**
- RTF parser emits `FormFieldBlock` for `FORMTEXT`/`FORMCHECKBOX`/`FORMDROPDOWN`
- `docparse/services/rtf_generator.ail` with `fillRtf` (targeted edit, not full generator)
- DOCX legacy `w:fldChar` form fields supported in parser

**Phase 3 — PDF AcroForm (stretch)**
- Depends on a PDF object-graph reader landing first (shared with annotation extraction)
- Read-only schema in this phase; fill in a later phase if demand justifies the PDF writer

**Phase 4 — ODT / HTML (deferred)**
- Track demand. Both are mechanically straightforward but small audiences.

---

## Open Questions

1. **Body-level SDTs that wrap paragraphs / tables.** `extractSdtBodyBlocks` ([docx_parser.ail:164](../../../docparse/services/docx_parser.ail#L164)) handles SDTs that wrap structural content. A "repeating section" SDT might wrap an entire address block with sub-fields. Do we (a) emit a single `FormFieldBlock` with `kind="section"` and lose the inner structure, (b) emit a `SectionBlock` containing nested `FormFieldBlock`s, or (c) split based on whether the SDT has children that are themselves SDTs? Leaning (b) — it composes with `formFieldsByName`'s tree walk and preserves richness. Needs a real-world template to validate against.

2. **Locked / read-only fields.** `w:sdtPr/w:lock/@w:val` can be `sdtLocked`, `contentLocked`, etc. Do we surface `locked: bool` on `FormFieldBlock` and refuse to fill, or silently allow the fill and let the caller decide? Leaning: surface it as a field, return `FillError::FieldLocked` on attempts to fill, with `--force` to override.

3. **Naming collisions.** Multiple `w:sdt`s with the same `w:tag` are legal OOXML. `formFieldsByName` would return duplicates; `fillDocx` would fill all of them with the same value. Document this as the contract rather than rejecting it — many templates intentionally bind the same value to multiple visible cells.

4. **Schema export format.** `--form-schema` could emit JSON Schema (`{"type": "object", "properties": {...}}`) rather than a list of fields, which would compose nicely with v0.11.0's `--extract --schema`. Worth doing if v0.11.0 ships first; otherwise emit a flat list and align later.

5. **Test corpus.** We need a real template. Candidates: a UK HMRC P11D form (RTF), a US W-9 (PDF AcroForm — stretch only), and a handcrafted DOCX with one of each SDT kind. Both legitimately freely redistributable.

---

## Test Plan

- **Unit**: per-parser golden tests asserting `FormFieldBlock` extraction from a small synthetic file. Cover each kind (text, checkbox, dropdown, date) and each binding mechanism (`w:tag`, `w:alias`, missing-both fallback).
- **Round-trip**: `parse → fill known value → re-parse → assert field shows the new value`. This is the property that proves the feature is real and not a paper exercise.
- **Negative**: dropdown value not in options → `FillError::ValueNotInOptions`. Unknown field name → in `FillReport.unknown`. Locked field → `FillError::FieldLocked` without `--force`.
- **Office benchmark**: add a form-fields scoring dimension to OfficeDocBench so regressions surface alongside the other 9 dimensions. Baseline: 100% on the synthetic corpus.
- **Byte-stability**: assert that filling no fields (`values = []`) produces a byte-identical output to the input template, modulo zip timestamps. This is the cleanest proof the round-trip preserves everything the writer doesn't touch.

---

## What This Unblocks

- "Onboarding form auto-fill" workflows: LLM extracts entity data from a free-text email, fills the DOCX supplier-onboarding form, returns a `.docx` to attach.
- Legacy-form digitisation: ingest an `.rtf` claim form, parse it as a schema, present a web form, fill the original `.rtf` for submission to systems that still expect RTF.
- Composability with v0.11.0 structured extraction: `--extract` produces JSON matching the form schema; `--fill` consumes it. Round-trip extraction → fill on the same template type becomes a one-liner.
- Composability with v0.18.0 legal write-back: a filled form *could* be emitted as tracked-changes inserts rather than direct content replacement, giving lawyer-style review on filled drafts. Not a default; a downstream composition.
