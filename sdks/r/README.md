# AILANG Parse R SDK

R client and MCP server for the [AILANG Parse](https://www.sunholo.com/ailang-parse/) document parsing API. Parse 13 formats into a structured Block ADT, manage API keys, and run as a Claude Desktop / Cursor / VS Code MCP server — all from R.

This SDK is feature-equivalent to the [Python](../python), [JavaScript](../js) and [Go](../go) SDKs and shares the same on-disk credential format, so a key saved by one SDK is usable from any other.

## Install

```r
# install.packages("remotes")
remotes::install_github("sunholo-data/ailang-parse", subdir = "sdks/r")
```

## Quick Start

```r
library(ailangparse)

# Auto-loads DOCPARSE_API_KEY env var or saved credentials
client <- DocParse$new()

# Parse a document by sample ID or server-side filepath
res <- client$parse("report.docx")

cat(length(res$blocks), "blocks, format:", res$format, "\n")

for (b in res$blocks) {
  if (b$type == "heading") {
    cat("  H", b$level, ": ", b$text, "\n", sep = "")
  } else if (b$type == "table") {
    cat("  Table:", length(b$headers), "cols x", length(b$rows), "rows\n")
  } else if (b$type == "change") {
    cat("  ", b$change_type, " by ", b$author, ": ", b$text, "\n", sep = "")
  } else {
    cat("  ", b$type, ": ", substr(b$text, 1, 80), "\n", sep = "")
  }
}
```

### Tables become data frames

```r
tables <- Filter(function(b) inherits(b, "ailang_block_table"), res$blocks)
df <- as.data.frame(tables[[1]])
head(df)
```

### Upload a local file

```r
res <- client$parse_file("data/report.docx")
```

### Parse from a signed URL

Parse documents from GCS, S3, or Azure Blob signed URLs without downloading locally:

```r
res <- client$parse_url(
  "https://storage.googleapis.com/bucket/doc.docx?X-Goog-Signature=...",
  output_format = "markdown+metadata"
)
```

### Output formats

```r
res <- client$parse("report.docx", output_format = "blocks")              # default
res <- client$parse("report.docx", output_format = "markdown")
res <- client$parse("report.docx", output_format = "html")
res <- client$parse("report.docx", output_format = "markdown+metadata")   # markdown with sections

# markdown+metadata includes rendered markdown and heading-sliced sections
cat(res$markdown)
for (s in res$sections) {
  cat("  ", s$heading, ": ", substr(s$markdown, 1, 60), "...\n", sep = "")
}
```

### Response metadata

Every parse result carries quota and request metadata as an attribute:

```r
res <- client$parse("report.docx")
meta <- attr(res, "response_meta")

meta$request_id            # "req_abc123"
meta$tier                  # "free", "pro", or "business"
meta$quota_remaining_day   # Requests left today
meta$quota_remaining_month # Requests left this month
meta$quota_remaining_ai    # AI requests remaining
meta$format                # Detected input format ("docx", etc.)
meta$replayable            # Whether this request can be replayed
```

## Authentication

API key resolution order:

1. Explicit `api_key` argument to `DocParse$new()`.
2. `DOCPARSE_API_KEY` environment variable.
3. Saved credentials at `~/.config/ailang-parse/credentials.json` (matched by `base_url`).

To obtain a new key interactively, use the RFC 8628 device-authorization flow:

```r
client <- DocParse$new()
info <- client$device_auth(label = "my-r-laptop")
# Browser opens → approve → key is auto-saved to disk and visible to all SDKs
```

## Key management

```r
client$keys$list()
client$keys$usage("key-id-here")
client$keys$rotate("key-id-here")
client$keys$revoke("key-id-here")
```

## MCP server (Claude Desktop, Cursor, VS Code)

The package ships a stdio MCP bridge that proxies to the hosted API. Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ailang-parse": {
      "command": "Rscript",
      "args": ["-e", "ailangparse::mcp()"]
    }
  }
}
```

The bridge auto-loads any saved API key (set via `client$device_auth(...)` or any other AILANG Parse SDK) and injects it into MCP `tools/call` requests.

## Unstructured.io drop-in

```r
uc <- UnstructuredClient$new(server_url = "https://docparse.ailang.sunholo.com")
elements <- uc$partition("report.docx", strategy = "auto")
```

## Block types

The Block ADT has 9 variants. Each block is an S3 list with class `c("ailang_block_<type>", "ailang_block")`:

| Type | Key fields |
|------|------------|
| `text` | `text`, `style` |
| `heading` | `text`, `level` |
| `table` | `headers`, `rows` (cells with `text`, `col_span`, `merged`); `as.data.frame()` supported |
| `list` | `items`, `ordered` |
| `image` | `mime`, `data_length`, `description` |
| `audio` | `mime`, `data_length`, `transcription` |
| `video` | `mime`, `data_length`, `description`, `transcription` |
| `section` | `kind`, `children` (recursive) |
| `change` | `change_type`, `author`, `date`, `text` |

## Error handling

All errors are typed conditions, so callers can dispatch:

```r
tryCatch(
  client$parse("missing.docx"),
  ailang_auth_error  = function(e) message("auth: ", conditionMessage(e)),
  ailang_quota_error = function(e) message("quota: ", e$tier, " ", e$used, "/", e$limit),
  ailang_docparse_error = function(e) {
    message("api error: ", conditionMessage(e))
    message("  suggested fix: ", e$suggested_fix)
    message("  details: ", e$details)       # Structured error details
    message("  request_id: ", e$request_id) # For support/debugging
  }
)
```

## Tests

```r
devtools::test()                          # unit tests, all offline
Sys.setenv(DOCPARSE_API_KEY = "dp_...")
devtools::test(filter = "integration")    # live API tests
```

## License

Apache 2.0 — same as the rest of the AILANG Parse project.
