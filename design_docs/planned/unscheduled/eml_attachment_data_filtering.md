# EML attachment data filtering — feature request

**Status**: FILED (2026-08-27)  
**Theme**: Add a CLI flag to omit `attachment-data` blocks (base64-encoded attachment content) from EML JSON output, solving a production scaling problem where large attachments cause DuckDB ingest failures and memory pressure.  
**Source**: User feedback via `mcp.ailang.sunholo.com/submit_feedback`; no auto-dispatch flag was set, so filed here for design review rather than immediate action.  
**Impact**: Production ingestion pipeline for a 66,608-message email archive.

## The request, as filed

Add either:
- `--no-attachment-data` — omit the blocks entirely, keeping `attachment-meta` and `[attachment: name, mime]` placeholder
- `--max-attachment-data-bytes N` — keep small attachments inline, replace oversized ones with placeholder

Preference stated: the first (simpler, covers their case completely).

## Why this matters

**Problem: DuckDB ingest failures and memory pressure**

The user persists parsed `.eml.json` to disk for downstream consumers. Every downstream consumer drops `attachment-data` blocks at projection before doing anything else — the base64 content exists only to be discarded.

Measured over a 66,608-message archive:
- Parsed JSON totals 1.71 GB (mean 25 KB, p50 3 KB, p90 21 KB)
- 172 files >1 MB account for 0.88 GB — **52% of all parsed bytes**
- Those large files are ~100% `attachment-data`; sampled 17.1 MB file: 17.1 MB `attachment-data` vs ~2 KB everything else (6 headers, 5 attachment-meta, 1 body)
- 10 files exceed 16 MB; the largest is 31.3 MB

**Concrete failure in production**

DuckDB's `read_json_objects` rejects any single JSON object larger than `maximum_object_size` (default 16 MB) and fails the *entire scan*, not just the offending file. One 17.1 MB parsed message caused a 66k-message ingest to fail silently for nine days. The index stopped advancing.

Workaround shipped: pass `maximum_object_size = 67108864` to the reader. Cost: DuckDB allocates a read buffer of `2x maximum_object_size` **per thread**. On an 8-core box, 128 MB allocation fails OOM; 64 MB costs 1.3 GB peak RSS. Every consumer must raise the ceiling as attachments grow, paying in memory.

Dropping the base64 at write time removes the class of problem instead of pushing the threshold.

## What's actually going on

**Attachment data is already typed and optional**

`docparse/types/document.ail` defines:
```
TextBlock({text, style, attachment_meta: ?[AttachmentMeta], attachment_data: ?text, attachment_ext: ?text})
```

`attachment_meta` holds `{filename, mime_type}` — the index-able part. `attachment_data` holds the base64-encoded content — the dead weight. The user's pipeline needs the metadata (for indexing filenames, mime types) but never touches the base64.

**Generator already supports omitting fields**

Existing CLI already accepts granular output filtering. Adding a flag to skip the `attachment_data` field (not the whole block) when writing JSON follows established patterns.

## Design

**Recommendation: add `--no-attachment-data` flag to omit the `attachment_data` field from TextBlock serialization when writing EML JSON.**

```
./bin/docparse archive.eml --no-attachment-data
```

Behavior:
- `TextBlock.attachment_meta` still present (filenames, mime types)
- `TextBlock.attachment_data` field omitted (no base64)
- `TextBlock.attachment_ext` field omitted (related metadata)
- `LinkBlock` and all other block types unchanged
- Scope: EML parsing only (other formats don't serialize `attachment_data`)
- Does not affect `--deep` (second-pass re-parsing reads the original `.eml` file, not the stored JSON)

### Downstream impact

- **DuckDB consumers**: Single JSON object size drops from 17.1 MB to ~2 MB for the measured high-end file; 52% of archive bytes no longer needed.
- **Memory pressure**: Consumer no longer needs to raise `maximum_object_size` past 16 MB default.
- **API change**: Output schema change — consumers expecting `attachment_data` field will see it missing. **Mitigation**: document clearly; field was already optional in type definition; existing robust consumers already handle its absence.
- **Round-trip**: `attachment_data` is never re-parsed as input, so round-trip fidelity for documented metadata is unchanged.

### Alternatives considered

- **`--max-attachment-data-bytes N`**: Keep small attachments, replace large ones with placeholder. More complex; the user states `--no-attachment-data` covers their case completely. Can be added later if the lighter flag gets adoption and use cases emerge.
- **Always omit in EML by default**: Breaking change to output schema. Not recommended without a major version bump.
- **Second flag for `attachment_ext`**: User's sampling showed both are base64; lumping them together makes sense. If they prove independent in practice, a follow-up flag is cheap.

### Open questions

1. **Other attachment-carrying formats**: Only EML currently exposes `attachment_data`; DOCX/PPTX/XLSX carry embedded media as `ImageBlock` (binary data serialized differently). No change needed there, but verify no format creep before shipping.
2. **Serialization layer**: Is `attachment_data` omission a JSON serializer concern or a parser concern? Check `output_formatter.ail` to decide where the gate lives (likely JSON output only; don't discard from the in-memory `Block` value, just skip serializing it).
3. **Scheduling**: Low-risk, localized change with clear user need and documented failure mode. Good candidate for next patch release once design is approved.
