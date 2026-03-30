# Document Generation: Verification & Compatibility

**Status**: Verification loop implemented. PPTX Keynote compatibility unresolved (stretch goal).
**Updated**: 2026-03-17

## What We Built

All 7 phases of v0.6.0 document generation are implemented in pure AILANG:
- 9 generator modules (xml_helpers, html, docx, pptx, xlsx, odt, odp, ods, ai_generator)
- `--convert` flag for format conversion, `--generate --prompt` for AI generation
- `/verify-docs` skill for automated verification

## Compatibility Matrix (current state)

| Format | python lib | LibreOffice | Google Docs | MS Office (Mac) | Apple iWork |
|--------|-----------|-------------|-------------|-----------------|-------------|
| DOCX | PASS | PASS | PASS | PASS | PASS (Pages) |
| PPTX | PASS | untested | untested | untested | **FAIL (Keynote)** |
| XLSX | PASS | PASS | untested | untested | PASS (Numbers, after cellStyles fix) |
| HTML | N/A | N/A | N/A | N/A | PASS (Safari) |
| ODT | N/A | PASS | untested | N/A | N/A |
| ODP | N/A | untested | untested | N/A | N/A |
| ODS | N/A | untested | untested | N/A | N/A |

## Generation Pattern: String XML Templates

AILANG's `XmlNode` constructors (`Element`, `Text`) are not publicly exposed — the type is opaque.
We generate Office XML via string concatenation + `std/zip.createArchive`:

```ailang
pure func docxRun(text: string) -> string =
  "<w:r><w:t xml:space=\"preserve\">" ++ xmlEscape(text) ++ "</w:t></w:r>"
```

This works well for DOCX (simple XML structure) but struggles with PPTX (enormous boilerplate).

### Why DOCX Works and PPTX Doesn't

**DOCX** has a forgiving structure. A minimal valid DOCX needs just 3 ZIP entries:
- `[Content_Types].xml` — static template
- `_rels/.rels` — one relationship
- `word/document.xml` — the content

Word, Pages, LibreOffice, and Google Docs all open this happily. We add `word/styles.xml` for heading styles, and it's complete. ~200 lines of AILANG.

**PPTX** has a deeply interconnected structure. A python-pptx reference file has **38 entries** including:
- 11 slide layouts (each ~12KB of XML)
- A slideMaster (~2KB) with placeholder shapes, `clrMap`, `txStyles`
- A theme (~7KB) with `themeElements`, `objectDefaults`, `extraClrSchemeLst`
- `presProps.xml`, `viewProps.xml`, `tableStyles.xml`
- `docProps/app.xml`, `docProps/core.xml`

Keynote validates ALL of this. Missing any piece → silent failure (no error dialog, just won't render).

## What We Tried for PPTX Keynote Compatibility

### Attempt 1: Minimal from scratch
Just `[Content_Types].xml`, `_rels/.rels`, `presentation.xml`, one `slideMaster`, one `slideLayout`, slides, theme.
**Result**: python-pptx opens fine. Keynote silently fails.

### Attempt 2: Added presProps, viewProps, tableStyles
Added the three auxiliary files that the reference has.
**Result**: Still fails in Keynote. python-pptx still works.

### Attempt 3: Added clrMap, clrMapOvr, objectDefaults
Added color mapping to slideMaster (`<p:clrMap bg1="lt1" tx1="dk1" ...>`), color map overrides to slides and layouts, `objectDefaults` and `extraClrSchemeLst` to theme, background reference to slideMaster.
**Result**: Still fails in Keynote. The XML is valid and python-pptx reads it fine.

### Attempt 4: Strip down a working reference
Created a python-pptx PPTX (which Keynote DOES open) and progressively stripped it:
- Removed `docProps/` — still opens
- Removed all layouts except one — still opens
- Removed one slide — still opens
- Down to 14 entries — **still fails** (despite having the same entries as our generated file)

**Key insight**: It's not about WHICH entries are present. Keynote cares about the CONTENT of the XML — specifically the slideMaster's internal structure (placeholder shapes with specific properties, text styles with 9 levels, group shape properties with transform coordinates). The python-pptx slideMaster alone is ~2KB of dense XML with pixel-precise coordinates.

## Root Cause Analysis

The fundamental problem is that PPTX's OOXML spec has two levels:
1. **Structural validity** — correct ZIP entries, valid XML, matching relationship IDs
2. **Semantic validity** — complete placeholder hierarchy, theme color resolution chain, text style inheritance

Python libraries (python-pptx, openpyxl) only check level 1. Keynote checks level 2 — it tries to render the slide and needs the full placeholder/theme resolution chain to succeed.

Building semantically valid PPTX from string templates would require ~500+ lines of dense XML boilerplate embedded in AILANG — essentially hardcoding a python-pptx template as string constants. This is:
- Fragile (any typo in 500 lines of XML strings = silent failure)
- Hard to maintain (no XML validation at compile time)
- Against AILANG's strengths (functional composition, not XML templating)

## Possible Solutions (for future work)

### Option A: AILANG XmlNode constructors (best, blocked)
If AILANG exposes `Element(tag, attrs, children)` + `Text(content)`, we could build XML trees programmatically and serialize them. This would make complex OOXML generation much safer — tree construction with type checking instead of string concatenation. **Requested from AILANG team 2026-03-17.**

### Option B: Template PPTX approach
Store a minimal template PPTX (created by python-pptx) in the repo. At generation time:
1. Read the template via `std/zip.readEntry` to get the boilerplate XML
2. Parse and modify `presentation.xml` to add slide references
3. Add our slide XML entries
4. Reassemble with `createArchive`

**Blocker**: `createArchive` creates from scratch — can't merge with an existing ZIP. Would need `readEntry` for every boilerplate file, then include them all in the new archive. Feasible but verbose.

### Option C: `writeEntryBytes` + template overlay
If AILANG ships `writeEntryBytes`, we could read binary entries from a template and copy them into the output. Combined with Option B, this would handle both XML and binary entries (like thumbnails).

### Option D: Accept library-level compatibility
Generated PPTX files open in:
- python-pptx (programmatic access)
- LibreOffice (cross-platform)
- Google Slides (via upload)
- Microsoft PowerPoint (desktop, untested but likely works given structural validity)

Keynote is the outlier with the strictest validation. For a v1.0, library + LibreOffice + Google compatibility may be sufficient.

## Fixes Applied (working)

### XLSX: cellStyles (fixed, Numbers now opens)
```xml
<cellStyles count="1">
  <cellStyle name="Normal" xfId="0" builtinId="0"/>
</cellStyles>
```

### PPTX: theme + presProps + viewProps + tableStyles (fixed, python-pptx works)
Added theme1.xml with full color/font/format schemes, presProps.xml, viewProps.xml, tableStyles.xml, clrMap on slideMaster, clrMapOvr on slides. Not sufficient for Keynote.

### HTML: XHTML self-closing tags (fixed, roundtrip works)
Changed `<meta charset="UTF-8">` to `<meta charset="UTF-8"/>` and `<img ...>` to `<img .../>` so our html_parser (XML-based) can re-parse the output.

## Unresolvable Issues

### ODF mimetype compression
ODF spec requires `mimetype` as the first ZIP entry, stored uncompressed. AILANG's `createArchive` always compresses. This affects MIME-type sniffing (`file` command shows "Zip data" instead of "OpenDocument Text") but doesn't affect LibreOffice. **Needs AILANG stdlib change** (store flag on `createArchive`). Requested 2026-03-17.

## Verification Infrastructure

### Automated: `benchmarks/verify_generated.py`
```bash
uv run --with python-pptx --with openpyxl --with python-docx benchmarks/verify_generated.py
```
Runs Level 1 (structure), Level 2 (library), Level 4 (roundtrip) on all files in `data/examples/`.

### Skill: `/verify-docs`
- `bash .claude/skills/verify-docs/scripts/verify_only.sh` — type-check + verify
- `bash .claude/skills/verify-docs/scripts/regen_and_verify.sh` — regenerate demos + verify

### Quick smoke test: `benchmarks/quick_check.sh`
Type-check all 28 modules + parse 5 representative files + conversion roundtrip. ~15s.

## Lessons Learned

1. **Office XML has two validity levels** — structural (ZIP/XML) and semantic (placeholder resolution, theme inheritance). Python libraries check structural; native apps check semantic.

2. **DOCX is the most forgiving OOXML format** — a 3-entry ZIP works everywhere. PPTX is the strictest because of the slide layout → slide master → theme inheritance chain.

3. **String XML templates work for simple structures** — DOCX, XLSX, ODF all generate fine this way. PPTX needs too much boilerplate.

4. **`xmlEscape` is essential** — without it, any `<`, `&`, or `"` in content corrupts the XML. Implemented as split/join chains in xml_helpers.ail.

5. **Record literal before `::` doesn't parse in AILANG** — need `let x = {record} in x :: list`. Discovered in multiple generators.

6. **Verification must be automated** — manually opening files in apps is unreliable (exit code 0 doesn't mean it rendered). Python library validation is the reliable automated check.

7. **The template approach is probably the right long-term answer** — generate a reference PPTX once with python-pptx, store it, read its boilerplate at generation time. This separates "OOXML boilerplate" (static) from "our content" (dynamic).
