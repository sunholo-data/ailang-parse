# Gemini Files API for Large PDF Optimization

**Status**: Implemented (commit 5160a38 — upload once, reference by URI)
**Version**: v0.9.0+
**Date**: 2026-03-31

## Problem

The PDF parser (`direct_ai_parser.ail`) sends the **full base64-encoded PDF** with every AI call. For multi-page documents, this creates massive redundant network traffic and unacceptable latency.

### Quantified Impact

| Metric | 20-page, 7MB PDF | 50-page, 20MB PDF |
|--------|-------------------|-------------------|
| Base64 size | ~10 MB | ~27 MB |
| AI calls | 22 (1 page count + 20 pages + 1 metadata) | 52 |
| Total upload | **~220 MB** | **~1.4 GB** |
| Observed latency | **12+ minutes** | Budget exhaustion / timeout |
| AI budget used | 22 of 30 (73%) | Exceeds limit=30 |

The advertised 50 MB per-format PDF limit is unreachable with the current architecture.

### Root Cause

`parsePdfAllPages()` is recursive and passes `base64Data` (the full file) to every `parsePdfOnePage()` call. Each call builds a JSON request with `kv("data", js(base64Data))`, embedding the entire file inline. The Gemini API receives the same 10+ MB payload 20+ times.

```
parsePdf(filepath)
  -> readFileBytes(filepath)          // 7 MB -> 10 MB base64
  -> aiGetPageCount(base64Data, ...)  // sends 10 MB
  -> parsePdfAllPages(base64Data, ...)
       -> parsePdfOnePage(base64Data, ..., page=1)   // sends 10 MB
       -> parsePdfOnePage(base64Data, ..., page=2)   // sends 10 MB
       -> ...                                         // 20 more times
```

## Solution: Upload Once, Reference by URI

Upload the file **once** to cloud storage, then reference it by URI in all subsequent AI calls. The Gemini `generateContent` API supports `fileData` parts with URIs:

```json
{
  "contents": [{
    "parts": [
      {"fileData": {"mimeType": "application/pdf", "fileUri": "gs://bucket/file.pdf"}},
      {"text": "Extract content from page 5..."}
    ]
  }]
}
```

### Architecture

```
                    +---------------------------+
                    |  sunholo/gemini_files     |
                    |  (new AILANG package)     |
                    +---------------------------+
                    | endpoints.ail  (pure URLs)|
                    | upload.ail     (Net ops)  |
                    +---------------------------+
                         |              |
              +----------+              +----------+
              |                                    |
    +---------v---------+            +-------------v----------+
    | Backend A: GCS    |            | Backend B: AI Studio   |
    | (Vertex AI / ADC) |            | (API key)              |
    +---------+---------+            +-------------+----------+
              |                                    |
              v                                    v
    gs://bucket/file.pdf              files/abc123 URI
              |                                    |
              +----------------+-------------------+
                               |
                    +----------v----------+
                    | AILANG Runtime       |
                    | buildParts() change: |
                    | fileUri -> fileData  |
                    +----------+----------+
                               |
                    +----------v----------+
                    | direct_ai_parser    |
                    | parsePdf() updated  |
                    | PdfSource ADT       |
                    +---------------------+
```

### Three Layers of Change

1. **New AILANG package** (`sunholo/gemini_files`) -- file upload/delete via Net
2. **AILANG runtime change** -- `fileUri` field in multimodal JSON -> `fileData` Gemini part
3. **Parser update** (`direct_ai_parser.ail`) -- use file URI for large PDFs

## Package Design: `sunholo/gemini_files`

### Dependencies

```toml
[dependencies]
"sunholo/gcp_auth" = "0.8.0"       # OAuth2 tokens for GCS
"sunholo/http_helpers" = "0.1.0"   # Bearer headers, response parsing
"sunholo/config" = "0.1.0"         # Env var loading

[effects]
max = ["Net", "FS", "Env"]
```

### Module: `endpoints.ail` (pure)

URL constructors for both backends. Follows the `gemini-live/endpoints.ail` pattern.

```ailang
-- Backend A: GCS (Vertex AI)
export pure func gcsUploadUrl(bucket: string, objectName: string) -> string
  -- https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o?uploadType=media&name={objectName}

export pure func gcsDeleteUrl(bucket: string, objectName: string) -> string
  -- https://storage.googleapis.com/storage/v1/b/{bucket}/o/{objectName}

export pure func gcsUri(bucket: string, objectName: string) -> string
  -- gs://{bucket}/{objectName}

-- Backend B: AI Studio Files API
export pure func aiStudioUploadUrl(apiKey: string) -> string
  -- https://generativelanguage.googleapis.com/upload/v1beta/files?key={apiKey}

export pure func aiStudioFileUrl(apiKey: string, fileName: string) -> string
  -- https://generativelanguage.googleapis.com/v1beta/files/{fileName}?key={apiKey}
```

### Module: `upload.ail` (effects: Net, FS, Env)

```ailang
-- Result of a file upload (either backend)
type UploadedFile = {
  uri: string,         -- gs://bucket/path OR Gemini Files API URI
  mimeType: string,
  backend: string      -- "gcs" or "ai_studio"
}

-- Upload a file. Auto-detects backend:
--   1. GOOGLE_API_KEY empty + GCS_TEMP_BUCKET set -> GCS upload (Vertex AI path)
--   2. GOOGLE_API_KEY set -> AI Studio Files API
--   3. Neither -> Err
export func uploadFile(base64Data: string, mimeType: string, displayName: string)
  -> Result[UploadedFile, string] ! {Net, FS, Env}

-- Delete an uploaded file (best-effort cleanup)
export func deleteFile(uploaded: UploadedFile)
  -> Result[(), string] ! {Net, FS, Env}
```

### Backend A: GCS Upload (Vertex AI)

```
POST https://storage.googleapis.com/upload/storage/v1/b/{BUCKET}/o
  ?uploadType=media&name=docparse-temp/{timestamp}-{hash}.pdf
Authorization: Bearer {token from gcp_auth}
Content-Type: application/pdf
Content-Transfer-Encoding: base64

{base64 data}
```

Returns `gs://{BUCKET}/docparse-temp/{timestamp}-{hash}.pdf` as the URI.

**Auth**: Uses `gcp_auth/token.getAccessToken()` -- same ADC token that works for Vertex AI, Firestore, etc. The `cloud-platform` scope includes GCS access.

**Cleanup**: `DELETE` via GCS JSON API + 1-day lifecycle policy as safety net.

### Backend B: AI Studio Files API

```
POST https://generativelanguage.googleapis.com/upload/v1beta/files?key={KEY}
Content-Type: multipart/related; boundary=BOUNDARY

--BOUNDARY
Content-Type: application/json

{"file": {"displayName": "contract.pdf"}}
--BOUNDARY
Content-Type: application/pdf
Content-Transfer-Encoding: base64

{base64 data}
--BOUNDARY--
```

Returns a `file_uri` from the response JSON. Files auto-expire after 48 hours.

## AILANG Runtime Change

**File**: `internal/ai/gemini/generate.go` -- `buildParts()` function

Current behavior: only handles `inlineData` from the `"data"` field.

Required addition (~15 lines): detect `"fileUri"` field and produce a `fileData` part.

```go
// In buildParts(), after checking mode == "multimodal":
if fileUri := obj["fileUri"]; fileUri != "" {
    parts := []part{
        {FileData: &fileData{
            MimeType: obj["mimeType"],
            FileUri:  fileUri,
        }},
    }
    // ... add text prompt part (same as existing code)
    return parts
}
```

New type in `types.go`:
```go
type fileData struct {
    MimeType string `json:"mimeType"`
    FileUri  string `json:"fileUri"`
}

type part struct {
    Text       string      `json:"text,omitempty"`
    InlineData *inlineData `json:"inlineData,omitempty"`
    FileData   *fileData   `json:"fileData,omitempty"`  // NEW
}
```

This supports both `gs://` URIs (Vertex AI) and Gemini Files API URIs (AI Studio).

## Parser Changes

**File**: `ailang-parse/docparse/services/direct_ai_parser.ail`

### New ADT

```ailang
type PdfSource = InlineData(string) | FileRef({uri: string, mimeType: string})
```

### Modified Flow

```ailang
export func parsePdf(filepath: string) -> [Block] ! {FS, AI, Net, Env} {
  match readFileBytes(filepath) {
    Err(_) => [],
    Ok(base64Data) => {
      let source = prepareSource(base64Data, filepath);
      let pageCount = aiGetPageCountFromSource(source, filepath);
      let blocks = if pageCount <= 5
        then aiExtractWithRetryFromSource(source, filepath, true, 1)
        else parsePdfAllPagesFromSource(source, filepath, 1, pageCount);
      cleanupSource(source);
      blocks
    }
  }
}
```

### Source Preparation

```ailang
func prepareSource(base64Data: string, filepath: string) -> PdfSource ! {Net, FS, Env} {
  -- Only use file upload for large files (>500KB base64 ~ 375KB raw)
  if length(base64Data) <= 500000 then InlineData(base64Data)
  else match uploadFile(base64Data, pdfMimeType(), filepath) {
    Ok(uploaded) => FileRef({uri: uploaded.uri, mimeType: uploaded.mimeType}),
    Err(_) => InlineData(base64Data)  -- silent fallback
  }
}
```

### Request Construction

```ailang
pure func sourceKvs(source: PdfSource) -> [Json] =
  match source {
    InlineData(data) => [kv("data", js(data))],
    FileRef(ref) => [kv("fileUri", js(ref.uri))]
  }
-- Used in place of kv("data", js(base64Data)) in all AI call builders
```

### Effect Signature Change

`parsePdf`: `{FS, AI}` -> `{FS, AI, Net, Env}` (breaking change)

- CLI `--caps` needs `Net` added: `IO,FS,Env,AI,Net`
- API server already has `Net` in capabilities
- `ailang-parse/ailang.toml` effect ceiling needs `Net` added

## Infrastructure (Vertex AI Path)

### GCS Bucket

```hcl
# In ailang-multivac/terraform/docparse.tf

resource "google_storage_bucket" "docparse_temp_files" {
  name          = "docparse-temp-files"
  location      = "EUROPE-WEST1"
  project       = "ailang-multivac-dev"
  storage_class = "STANDARD"
  force_destroy = true

  lifecycle_rule {
    condition {
      age = 1  # Auto-delete after 1 day
    }
    action {
      type = "Delete"
    }
  }

  uniform_bucket_level_access = true
}
```

### IAM

```hcl
resource "google_storage_bucket_iam_member" "docparse_sa_object_creator" {
  bucket = google_storage_bucket.docparse_temp_files.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:ailang-dev-docparse@ailang-multivac-dev.iam.gserviceaccount.com"
}
```

### Environment Variable

Add `GCS_TEMP_BUCKET=docparse-temp-files` to the Cloud Run service env.

## Performance Projections

### Before (inline base64)

| PDF Size | Pages | AI Calls | Network Traffic | Latency |
|----------|-------|----------|-----------------|---------|
| 1 MB | 5 | 3 | 4 MB | ~30s |
| 7 MB | 20 | 22 | 220 MB | ~12 min |
| 20 MB | 50 | 52 | 1.4 GB | Timeout |
| 50 MB | 100 | 102 | 6.8 GB | Impossible |

### After (file URI reference)

| PDF Size | Pages | AI Calls | Network Traffic | Latency (est.) |
|----------|-------|----------|-----------------|----------------|
| 1 MB | 5 | 3 | 1.3 MB (inline, below threshold) | ~30s |
| 7 MB | 20 | 22 | 10 MB upload + 22 KB refs = **10 MB** | ~2 min |
| 20 MB | 50 | 52 | 27 MB upload + 52 KB refs = **27 MB** | ~5 min |
| 50 MB | 100 | 102 | 67 MB upload + 102 KB refs = **67 MB** | ~10 min |

**Key improvement**: Network traffic scales with file size (1x), not file size x pages (Nx).

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| AILANG runtime `fileUri` change delayed | Blocks parser update | Package + design doc can proceed independently; fallback to inline works |
| GCS upload via `httpRequest` string body corrupts base64 | Upload fails | Test early; if broken, request `httpUploadBinary` stdlib function |
| GCS bucket not configured in dev/CI | Falls back to inline | Silent fallback; no behavior regression |
| Effect ceiling change breaks callers | Compile error for callers without Net | Document in release notes; API server already has Net |
| Vertex AI rejects `gs://` URI in `fileData` | AI calls fail | Verify with manual curl test before implementing |
| Concurrent uploads create GCS cost | Minor | 1-day lifecycle policy; files are small (< 50 MB) |

## Success Criteria

1. 20-page PDF parses in < 3 minutes (down from 12+)
2. 50 MB PDF limit is achievable (currently impossible)
3. Small PDFs (< 5 pages) have zero performance regression
4. Vertex AI (ADC) mode works end-to-end with GCS
5. Upload failure gracefully falls back to inline base64
6. AI budget usage unchanged (same number of AI calls)

## Open Questions

1. Does the GCS JSON API accept base64-encoded body with `Content-Transfer-Encoding: base64`, or does it require raw binary? If raw binary, we may need an AILANG stdlib addition (`httpUploadBytes`).
2. Should we also implement Gemini context caching (cache the file across calls) for even better performance? This would reduce Gemini's per-call processing time since it wouldn't re-process the file each time.
3. For the API server (Cloud Run), should uploaded files use the requester's project/bucket or a shared docparse bucket? Shared is simpler but means all files go through our GCS.
