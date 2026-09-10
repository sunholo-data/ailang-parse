# Word proposal templates for AILANG Parse

Three editable Word proposal templates, plus the small styling references that
let AILANG Parse put your Markdown onto them.

| Template | Preview | Reference doc |
|---|---|---|
| `output/sunholo-proposal.docx` | [PDF](output/sunholo-proposal.pdf) | `output/references/sunholo-reference.docx` |
| `output/holosun-proposal.docx` | [PDF](output/holosun-proposal.pdf) | `output/references/holosun-reference.docx` |
| `output/ailang-proposal.docx` | [PDF](output/ailang-proposal.pdf) | `output/references/ailang-reference.docx` |

The PDFs are visual previews. The DOCX files contain editable text, live page
numbers and semantic heading/table styles. Replace every `«…»` prompt before
sending. Commercial figures and agreement wording are deliberately unfilled.
Holosun ApS is named in the footer — change the entity details if a different
party is issuing the proposal.

## Two ways to use them

### 1. Edit in Word

Save a copy of the proposal you want and replace its prompts. Use the existing
Heading 1/2/3 and `SunholoTable` styles. The header and footer stay editable.
These are ordinary reusable `.docx` files, not macro-enabled documents and not
Word `.dotx` templates.

### 2. Generate from Markdown with AILANG Parse

This is what the `references/` files are for. Each is a near-empty document
carrying only the design — page setup, headers, footers, theme, styles. Point
`--reference-doc` at one and your Markdown becomes the body:

```bash
docparse draft.md \
  --convert proposal.docx \
  --reference-doc references/sunholo-reference.docx \
  --table-style SunholoTable
```

Swap `sunholo` for `holosun` or `ailang`. `proposal.md` in this directory is a
ready-made skeleton with the same structure as the Word files — copy it and
fill it in.

Two authoring notes, learned the hard way:

- Use `#` for major page sections and `##` for subheadings. Level-one headings
  start a new page.
- Use separate paragraphs where line separation matters; Markdown hard line
  breaks are collapsed.
- Use `«placeholder»` rather than Markdown square brackets, which can be
  swallowed by link parsing.

See [Styling from a reference doc](../document-generation.html#reference-doc)
for what the merge carries over and what it regenerates.

## Design

A4 portrait; 23 mm side margins; white page; Montserrat headings; 11 pt Arial
body. Colours from sunholo.com: vermilion `#E73C17`, blue-grey `#314352`, pale
grey `#F6F8FA`; small link text uses a darker vermilion `#B52D10`.

First-page branding is larger; continuation pages use a compact header.
Level-two and level-three headings keep with the following text. Table headers
repeat across pages. The three-page outline covers the opportunity, delivery
and commercial next steps — content may run longer, so render after editing.

Montserrat Regular and Bold ship in `assets/fonts/` under the SIL Open Font
License (`OFL.txt`). Install them for the closest Word layout, or share the PDF.
Fonts are not embedded in the DOCX.

## Rebuilding from source

`source/parts/` is the editable OOXML design. `source/build.ail` packages those
parts and the logo assets into the reference documents using AILANG `std/zip`;
`build.sh` runs that builder and then the docparse CLI:

```bash
bash build.sh
```

No Python and no python-docx anywhere in the pipeline. Requirements: AILANG,
AILANG Parse, and — only if you want rendered previews — LibreOffice and
Poppler.

Verify after changing the design:

```bash
docparse-audit output/sunholo-proposal.docx --strict
docparse-render output/sunholo-proposal.docx --output-dir .build/render
```

Then look at every rendered page. An audit pass says the file is well-formed;
it says nothing about whether the layout or the wording is right.

## Licence and provenance

The templates and OOXML source are published by Holosun ApS for reuse — adapt
them freely, including commercially. The bundled Montserrat fonts keep their own
SIL Open Font License. The Sunholo and AILANG logos are Holosun ApS marks;
replace them with your own if you are issuing proposals as a different party.

This is a document adaptation of the sunholo.com visual language, not a formal
brand guide. Brand sources inspected 10 September 2026.
