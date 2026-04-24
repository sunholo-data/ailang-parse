# Design Doc: Editable A2UI Components + Write-Path (v0.17.0)

**Status**: Implemented (both phases complete as of 2026-04-24)  
**Date**: 2026-04-24  
**Author**: Mark + Claude  
**Source**: Aitana Platform v6 request (msg `8db938c6`) — July 2026 workshop deadline  

## Problem

The current A2UI formatter emits read-only components only. Aitana Platform v6 renders parsed documents in a split-pane workspace and needs users to be able to inline-edit content (text, table cells) alongside AI-assisted edits. Three things are missing:

1. **Editable component variants** — `TextField` instead of `Text`, `EditableTable` instead of a read-only table, etc.
2. **Stable block IDs on A2UI nodes** — so frontend edit events can be correlated back to the originating `Block` at index `N`
3. **Write-path API** — accept an array of `EditDelta` objects (block index + new content), regenerate the document

## Non-Goals

- Real-time collaborative editing (OT/CRDT) — out of scope
- Schema-level change to the `Block` ADT — blocks remain stateless; IDs are injected at formatting time
- New persistence layer — the write-path is stateless (caller sends original bytes + deltas)

---

## Part 1: Editable formatter flag (ailang-parse)

### Change to `a2ui_formatter.ail`

Add an `editable` boolean parameter to `documentToA2UI`. When `true`, content-bearing nodes emit editable component type names instead of read-only ones.

**Editable component type map:**

| Block variant | Read-only type | Editable type |
|---------------|----------------|---------------|
| `TextBlock` | `text` | `text-field` |
| `HeadingBlock` | `heading` | `heading-field` |
| `TableBlock` | `table` | `table-editable` |
| `ListBlock` | `list` | `list-editable` |
| `ChangeBlock` | `callout` | `callout` (unchanged — track-change authorship, not user-editable) |
| `ImageBlock` | `image` | `image` (unchanged — no text to edit) |
| `AudioBlock` / `VideoBlock` | `media` | `media` (unchanged) |
| `SectionBlock` | `container` | `container` (unchanged — structural only) |
| Metadata nodes | `key-value` | `key-value` (unchanged — format/title not user-editable) |

### Block index on every node

Every node emitted by `a2uiFlattenOne` already tracks `nextIdx` in the `FlatResult` accumulator. We add a `block_index` prop to every content node (all variants except the root `doc` container and metadata nodes). This is the position of the block in the original `blocks` list, making it stable and trivially computable without changing the `Block` ADT.

```ailang
-- current
let id = "b_${show(idx)}";

-- new: also emit block_index as a prop
let blockIdxProp = {key: "block_index", value: show(idx)}
```

SectionBlock children are emitted as siblings with their own sequential indices — their `block_index` reflects position in the flattened list, which is what the write-path also uses.

### New function signature

```ailang
-- Public: entry point used by api_server.ail
export func documentToA2UI(doc: ParsedDocument, editable: bool) -> string
  ! {}
```

The existing zero-arg call site `documentToA2UI(doc)` in `api_server.ail` becomes `documentToA2UI(doc, false)` — no behaviour change for existing callers.

### API surface change (docparse repo)

`POST /api/v1/parse` gains an optional `editable` boolean in the request body (default `false`), only meaningful when `outputFormat=a2ui`.

```json
{
  "outputFormat": "a2ui",
  "editable": true
}
```

Capability manifest: add `"editable_a2ui": true` under the `a2ui` output format entry.

### Example output (editable=true)

```json
[
  { "id": "doc", "type": "container", "children": ["b_0", "b_1", "b_2"], "props": [] },
  { "id": "b_0", "type": "heading-field", "children": [],
    "props": [{"key": "text", "value": "Q1 Revenue"}, {"key": "level", "value": "1"},
              {"key": "block_index", "value": "0"}] },
  { "id": "b_1", "type": "text-field", "children": [],
    "props": [{"key": "text", "value": "Revenue increased 12% YoY."},
              {"key": "block_index", "value": "1"}] },
  { "id": "b_2", "type": "table-editable", "children": [],
    "props": [{"key": "headers", "value": "[\"Category\",\"Value\"]"},
              {"key": "rows", "value": "[[\"Revenue\",\"€2.3M\"],[\"Costs\",\"€1.1M\"]]"},
              {"key": "block_index", "value": "2"}] }
]
```

---

## Part 2: Write-path — `POST /api/v1/edit` (docparse repo)

### Concept

The caller holds the original file bytes (already uploaded) and a sparse list of `EditDelta` objects. The server applies the deltas to the in-memory block list and calls the existing format-specific generator to produce corrected output bytes.

This is stateless: no diff storage, no server-side document state. The caller is responsible for maintaining the `editedBlocks` overlay and sending the full delta set on each call.

### Endpoint

```
POST /api/v1/edit
Content-Type: multipart/form-data

Fields:
  file        — original document bytes (required)
  outputFormat — "docx" | "pptx" | "xlsx" | "odt" (default: same as input)
  deltas      — JSON array of EditDelta objects (see below)
```

### EditDelta schema

```json
[
  {"block_index": 5, "new_text": "Updated paragraph text"},
  {"block_index": 12, "cell": [1, 2], "new_text": "€2.8M"},
  {"block_index": 7, "new_items": ["Item A", "Item B", "Item C"]}
]
```

| Field | Type | Applies to | Description |
|-------|------|------------|-------------|
| `block_index` | int | all | Index in the flattened block list (matches `block_index` prop in A2UI) |
| `new_text` | string | TextBlock, HeadingBlock | Replace full text content |
| `cell` | [row, col] | TableBlock | Zero-indexed row/col within `rows` |
| `new_text` | string | TableBlock (with `cell`) | New cell text |
| `new_items` | [string] | ListBlock | Replace full items list |

Unsupported delta types (image, audio, video, section, change) return a `422 UNSUPPORTED_DELTA` error with the offending `block_index`.

### Implementation sketch (AILANG)

New module `docparse/services/edit_apply.ail`:

```ailang
module docparse/services/edit_apply

-- Parse the original file to get blocks, apply deltas, regenerate
export func applyEdits(
  fileBytes: bytes,
  filename: string,
  deltas: [EditDelta],
  outputFormat: string
) -> bytes ! {IO, FS, AI, Env}
```

Steps:
1. `parseBytes(fileBytes, filename)` → `ParsedDocument` (reuse existing parse pipeline)
2. `applyDeltas(doc.blocks, deltas)` → `[Block]` (pure function, Z3-verifiable: `listLength(result) == listLength(input)`)
3. Wrap modified blocks back into a `ParsedDocument` (same metadata, new blocks)
4. Route to the appropriate generator (`generateDocx`, `generatePptx`, etc.) based on `outputFormat`
5. Return raw bytes

### Route in `api_server.ail`

```ailang
@raw @nowrap @route("POST", "/api/v1/edit")
func editDocument(req: {body, headers, method}) -> string ! {IO, FS, Env, AI, Net, Rand, Clock}
```

Auth: same API key / JWT flow as `/api/v1/parse`. Quota: counts as one parse request + one (small) AI-free generation.

Response: `Content-Type: application/octet-stream`, raw bytes on success. On error, JSON error envelope matching the structured error schema (`code`, `request_id`, `details`).

### Capability manifest addition

```json
{
  "name": "edit",
  "description": "Apply edit deltas to a parsed document and regenerate",
  "endpoint": "/api/v1/edit",
  "method": "POST",
  "auth": "required",
  "supported_formats": ["docx", "pptx", "xlsx", "odt", "odp", "ods"],
  "delta_types": ["text", "heading", "table_cell", "list_items"]
}
```

---

## Repo placement

| Change | Repo |
|--------|------|
| `documentToA2UI(doc, editable)` + `block_index` prop | **ailang-parse** (public) |
| `text-field`, `heading-field`, `table-editable`, `list-editable` component builders | **ailang-packages/a2ui** |
| `POST /api/v1/parse` `editable` param plumbing | **docparse** (private) |
| `POST /api/v1/edit` endpoint + `edit_apply.ail` | **docparse** (private) |

---

## Phasing

**Phase 1 (near-term, ~1 week):** Editable flag + block_index  
- Change `documentToA2UI` signature  
- Add `block_index` prop to all content nodes  
- Add editable component type names  
- Add `editable` boolean builders to `ailang-packages/a2ui`  
- Wire `editable` param in `api_server.ail`  
- Tests: extend `test_serve_api.sh` — parse with `editable=true`, assert `block_index` present, assert `text-field` type  

**Phase 2 (~2–3 weeks after):** Write-path  
- `edit_apply.ail` module  
- `POST /api/v1/edit` route  
- Delta validation + error codes  
- Tests: round-trip — parse DOCX → edit delta → regenerate DOCX → re-parse → assert changed text  

---

---

## Implementation notes (Phase 2 decisions)

### Delta format — actual vs. planned

The design proposed `"cell": [row, col]` as an array field for table cell coordinates. The actual implementation uses separate integer fields to avoid needing `asInt` on raw JSON values (which isn't exposed from `std/json`):

```json
{"block_index": 2, "op": "set_cell", "cell_row": 1, "cell_col": 0, "new_text": "€2.8M"}
{"block_index": 2, "op": "set_header", "cell_col": 0, "new_text": "Category"}
```

The `op` field distinguishes delta types. Auto-detection (when `op` is absent) inspects field presence: `new_items` → `set_items`, `cell_row` present → `set_cell`, otherwise → `set_text`.

### Response format — JSON blocks, not raw bytes

The design proposed returning raw bytes with `Content-Type: application/octet-stream`. In practice, AILANG `serve-api` with `@nowrap` always JSON-encodes the `result` field — binary bytes in a string become `"PK..."` rather than raw bytes.

The implemented response returns **modified blocks as JSON** (same shape as `POST /api/v1/parse` with `outputFormat=blocks`):

```json
{
  "status": "success",
  "format": "zip-office",
  "blocks": [...],
  "metadata": {...},
  "deltas_applied": 2,
  "meta": {"request_id": "...", "replayable": true}
}
```

To regenerate a file from the returned blocks, use the AILANG SDK or CLI:
```bash
ailang run --entry main --caps IO,FS docparse/main.ail blocks.json --convert output.docx
```

### Contracts

Four `ensures` contracts added to `edit_apply.ail`, all asserting length preservation (deltas mutate content but never add/remove blocks or cells):

| Function | Contract |
|---|---|
| `editApply_applyDeltas` | `listLength(result) == listLength(blocks)` |
| `editApply_applyDelta` | `listLength(result) == listLength(blocks)` |
| `editApply_replaceCellText` | `listLength(result) == listLength(cells)` |
| `editApply_replaceRowCellText` | `listLength(result) == listLength(rows)` |

Z3 skips these (list types not SMT-encodable — same as all other list contracts in the codebase). Runtime-verified via `ailang run --verify-contracts`.

### Resolved open questions

1. **`block_index` for SectionBlock children.** Implemented: child `block_index` is its position in the *flattened* list (consistent with `applyDeltas` indexing). SectionBlock itself also gets `block_index` when `editable=true`.

2. **Table delta granularity.** Implemented cell-level only (`set_cell` for rows, `set_header` for header row). Row/table-level can be added on request.

3. **Round-trip fidelity.** Parse → apply → return blocks. Formatting not in the Block ADT (custom fonts, cell colours) is silently dropped at generation time. Acceptable per Aitana confirmation.

4. **Output format.** Resolved as JSON blocks (see above). Raw bytes not feasible via current serve-api.

5. **Naming.** Implemented as `editApply_*` prefix in `docparse/services/edit_apply.ail` and route `editDocument` in `api_server.ail`. No collision with the AI-driven `generateDocument` in `main.ail`.

---

## Usage example

### 1. Parse with editable A2UI (Phase 1)

```bash
curl -X POST https://<host>/api/v1/parse \
  -H 'Content-Type: application/json' \
  -d '{"filepath":"sample_docx_formatting","outputFormat":"a2ui","editable":"true","apiKey":"dp_..."}'
```

Response contains nodes with `block_index` props and editable component types (`text-field`, `heading-field`, `table-editable`, `list-editable`).

### 2. Apply edits (Phase 2)

```bash
curl -X POST https://<host>/api/v1/edit \
  -F 'filepath=@report.docx' \
  -F 'apiKey=dp_...' \
  -F 'deltas=[
    {"block_index":0,"op":"set_text","new_text":"Q2 Revenue Report"},
    {"block_index":3,"op":"set_cell","cell_row":1,"cell_col":1,"new_text":"€3.1M"},
    {"block_index":5,"op":"set_items","new_items":["Revenue up 12%","Costs stable","EBITDA €2.0M"]}
  ]'
```

Response:
```json
{
  "result": {
    "status": "success",
    "format": "zip-office",
    "blocks": [...modified blocks...],
    "deltas_applied": 3
  },
  "_headers": {"X-Request-Id": "req_abc123", ...}
}
```

### 3. Op auto-detection (convenience)

When `op` is absent, the delta type is inferred from field presence:

```json
[
  {"block_index": 0, "new_text": "Updated heading"},
  {"block_index": 2, "cell_row": 1, "cell_col": 0, "new_text": "New value"},
  {"block_index": 4, "new_items": ["Item A", "Item B"]}
]
```

### 4. Error codes

| Code | Trigger |
|---|---|
| `INVALID_API_KEY` | Missing or invalid `dp_` key |
| `INPUT_NOT_FOUND` | Uploaded file not found at temp path |
| `FORMAT_NOT_SUPPORTED` | AI-required format (pdf, image, audio, video) |
| `QUOTA_EXCEEDED` | Daily/monthly request limit reached |

## Open questions

1. **Binary download.** If Aitana needs the modified file as bytes (not blocks), options are: (a) GCS upload + signed URL from edit endpoint; (b) a separate download endpoint; (c) SDK-side generation from returned blocks. Deferred.

2. **Table row/table-level deltas.** `set_row` and `set_table` ops not yet implemented. Add if requested.
