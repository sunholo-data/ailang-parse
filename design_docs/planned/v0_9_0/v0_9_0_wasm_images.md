# WASM Image Rendering — Design Doc

**Status**: PLANNED (2026-03-20)
**Depends on**: WASM integration (try.html), docparse_browser.ail

## Problem

The WASM parser detects image references in Office XML (e.g., `<a:blip r:embed="rId2"/>`) and produces `ImageBlock` with metadata (mime, description), but the actual binary image data lives in the ZIP's `word/media/` (DOCX), `ppt/media/` (PPTX) folders. The current try.html shows `[Image: embedded]` placeholders instead of rendering images.

## Architecture

The image pipeline crosses the JS/AILANG boundary:

```
ZIP file (JS: JSZip)
  └── word/media/image1.png (binary)
  └── word/_rels/document.xml.rels (XML, maps rId → media path)
  └── word/document.xml (XML, contains <a:blip r:embed="rId2"/>)

AILANG (WASM): parses document.xml → produces ImageBlock({mime: "image/png", ...})
JS: needs to resolve rId → media path → extract binary → base64 → <img src="data:...">
```

## Implementation Steps

### 1. Extract relationship map (JS side)

Before calling AILANG, JS reads `word/_rels/document.xml.rels` and builds a map:
```javascript
// rId → target path
const rels = {};
const relsXml = await zip.file('word/_rels/document.xml.rels').async('string');
// Parse XML, extract <Relationship Id="rId2" Target="media/image1.png"/>
```

### 2. Pass image references through AILANG

Current `docparse_browser.ail` already extracts image blocks. The `ImageBlock` includes the relationship ID or path in its fields. Need to verify which field carries the reference — may need to enhance `docparse_browser.ail` to include the `r:embed` attribute value.

### 3. Extract binary images (JS side)

After AILANG returns blocks, JS:
1. Finds `ImageBlock` entries
2. Resolves the media path via the relationship map
3. Reads binary from ZIP: `await zip.file('word/media/image1.png').async('base64')`
4. Injects as `data:image/png;base64,...` into the block rendering

### 4. Render in output panel

Update `renderBlocks()` in `wasm-demo.js`:
```javascript
case 'image':
  if (b._base64) {
    return '<div class="dp-block"><img src="data:' + b.mime + ';base64,' + b._base64 + '" style="max-width:100%"></div>';
  }
  return '<div class="dp-block">[Image: ' + (b.description || b.mime) + ']</div>';
```

### 5. AI image description (optional)

If user has Gemini API key, can optionally describe images:
```javascript
const desc = await engine.callAsync('describeImageBase64', base64, mime);
```

## Limits

- Max image size: 2MB per image (skip larger ones)
- Max images per document: 20 (prevent memory issues in browser)
- Max total image data: 10MB per document
- Images above limits show placeholder with "Image too large for browser preview"

## Format-specific paths

| Format | Rels file | Media folder |
|--------|-----------|-------------|
| DOCX | `word/_rels/document.xml.rels` | `word/media/` |
| PPTX | `ppt/slides/_rels/slideN.xml.rels` | `ppt/media/` |
| XLSX | N/A (rarely has images) | `xl/media/` |
| ODT | `META-INF/manifest.xml` | `Pictures/` |
| EPUB | OPF manifest | various |

## Files to modify

- `docs/js/wasm-demo.js` — add relationship extraction, binary image loading, block enrichment
- `docparse/services/docparse_browser.ail` — may need to expose image reference IDs
- `docs/try.html` — CSS for image rendering in output panel

## Open questions

1. Does the current `ImageBlock` from `docparse_browser.ail` include the `r:embed` reference ID, or just the resolved path? Need to check `docx_parser.ail` image handling.
2. Should we render images inline in all three tabs (Blocks, JSON, Markdown) or just the Blocks tab?
3. For PPTX, each slide has its own rels file — need per-slide relationship resolution.

## Roadmap note

Also planned: update `ailang-demos` to use this improved WASM implementation once stable. This is a future task, not part of this implementation.
