# Email Parsing — Follow-up Design Doc

**Status:** IMPLEMENTED (v0.9.0) — P0, P0a, P1, P6 shipped; P2–P5 remain planned  
**Author:** Mark + Claude  
**Date:** 2026-04-02  
**Updated:** 2026-04-02  
**Context:** Email parsing (EML/MBOX) is now live — 100% gap coverage across RFC 5322, MIME, and encoding tests. This doc captures follow-up work to turn email parsing from a feature into a product differentiator.

---

## Current State

### What works
- RFC 5322 header extraction with folding/unfolding
- MIME multipart (alternative, mixed, nested)
- Base64 and quoted-printable body decoding
- RFC 2047 encoded-words (B and Q encoding) for international headers
- MBOX multi-message archive parsing
- Attachment identification with filename + MIME type
- Metadata mapping: Subject→title, From→author, Date→created
- Browser WASM parsing (same AILANG codebase)
- Batch mode via `ailang run --batch`

### Known limitations
- ~~HTML parts fail on non-XML-compliant HTML~~ **DONE** — htmlSanitize pre-processor closes void elements, replaces HTML entities, strips DOCTYPE. HTML-only emails now parse fully.
- ~~No attachment content extraction~~ **DONE** — text-based attachments (CSV, HTML, Markdown, nested EML) parsed inline. Office/binary attachments identified but not yet parsed (see P0a below).
- ~~No thread reconstruction~~ **DONE** — `parseMboxThreaded` groups by Message-ID/In-Reply-To/References with quote stripping.
- No Outlook `.msg` support (binary format, different from EML)

---

## Follow-up Proposals

### P0: Attachment Chain Parsing — DONE (text-based)

**Status:** Shipped (2026-04-02)

Text-based attachments are now decoded and parsed inline automatically:
- `text/csv`, `text/tab-separated-values` → `parseCsv`
- `text/html` → `parseHtml`
- `text/markdown` → `parseMarkdown`
- `text/plain` → TextBlock
- `message/rfc822` → recursive `parseEml` (email-in-email)

Binary attachments (PDF, images) stay as placeholder TextBlocks. Output:

```json
{
  "type": "section",
  "kind": "attachment",
  "blocks": [
    {"type": "text", "style": "attachment-meta", "text": "revenue_q1.csv (text/csv)"},
    {"type": "table", "headers": [...], "rows": [[...]]}
  ]
}
```

17/17 gap checks passing at 100%.

---

### P0a: Office Attachment Parsing (two-pass approach) — DONE

**Status:** Shipped (2026-04-02)

**Problem:** DOCX/PPTX/XLSX attachments are ZIP archives. The email parser is `pure func` — no filesystem effects — so it can't extract ZIP contents to parse them. These attachments currently appear as placeholders: `[attachment: report.docx, application/vnd...]`.

**Proposal: Two-pass architecture.**

**Pass 1 (pure):** The email parser identifies Office attachments and preserves their base64-encoded content in a new block variant or metadata field:

```json
{
  "type": "section",
  "kind": "attachment",
  "blocks": [
    {"type": "text", "style": "attachment-meta", "text": "report.docx (application/vnd.openxmlformats...)"},
    {"type": "text", "style": "attachment-data", "text": "UEsDBBQAAAAI..."}
  ]
}
```

**Pass 2 (effectful):** A separate function (or the CLI entry point) takes the parse output, finds `attachment-data` blocks, writes them to temp files, runs the appropriate Office parser (DOCX/PPTX/XLSX), and replaces the data block with parsed content blocks.

```
parseEmailDocument (main.ail)
  ├── Pass 1: parseEml(content)          → pure, returns blocks with base64 data
  └── Pass 2: resolveOfficeAttachments() → {FS}, extracts ZIPs, parses Office XML
```

**Why two-pass?**
- Keeps `eml_parser.ail` pure — no FS effects leaking into the email parser
- Same pattern works for PDF/image attachments when AI is available (Pass 2 with `{AI}` effects)
- Users who only want text-based attachment parsing get it for free (Pass 1 only)
- The `--deep` flag gates Pass 2: `ailang run ... inbox.eml --deep`

**Supported Office MIME types:**
- `application/vnd.openxmlformats-officedocument.wordprocessingml.document` (DOCX)
- `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` (XLSX)
- `application/vnd.openxmlformats-officedocument.presentationml.presentation` (PPTX)

**Complexity:** Medium. Base64 → temp file → ZIP extract → existing Office parser. The plumbing exists; it's wiring it together and managing temp file cleanup.

**Impact:** High. This is the "parse an email and its DOCX attachment in one call" story. Combined with text-based attachment parsing, it covers the vast majority of real-world email attachments.

---

### P1: Thread Reconstruction — DONE

**Status:** Shipped (2026-04-02)

`parseMboxThreaded(content)` groups MBOX messages into conversation threads:
- Groups by Message-ID / In-Reply-To / References via BFS traversal
- Subject normalization strips Re:/Fwd: prefixes
- Participant extraction per thread
- Quote stripping removes `> ` prefixed lines and "On DATE, PERSON wrote:" attribution
- CLI: `ailang run ... archive.mbox --threaded`
- WASM: `parseMboxThreadedContent()` export

Output:

```json
{
  "type": "section",
  "kind": "thread",
  "blocks": [
    {"type": "text", "style": "thread-subject", "text": "Q2 Budget Planning"},
    {"type": "text", "style": "thread-participants", "text": "Alice, Bob, Carol"},
    {"type": "section", "kind": "thread-message", "blocks": [...]},
    {"type": "section", "kind": "thread-message", "blocks": [...]},
    {"type": "section", "kind": "thread-message", "blocks": [...]}
  ]
}
```

Tested with 5 interleaved messages forming 2 threads (3+2). 3/3 thread gap checks at 100%.

---

### P2: Inbox Monitoring Agent

**Problem:** Parsing individual .eml files is useful, but the real product story is continuous monitoring — an agent that watches a mailbox and processes new emails as they arrive.

**Proposal:** Build an AILANG-based agent that:
1. Watches a local mailbox directory (MailMate, Thunderbird) or connects via IMAP
2. Parses new emails as they arrive using the existing EML parser
3. Optionally chains to attachment parsing (P0)
4. Outputs structured JSON to a configurable sink (webhook, vector DB, file system)
5. Supports filtering rules (by sender, subject pattern, attachment type)

**Implementation options:**
- **Local directory watcher:** Simplest. Watch `~/Library/Application Support/MailMate/Messages.noindex/` for new `.eml` files. Cross-platform via fsnotify.
- **IMAP polling:** More portable. Connect to Gmail/Outlook IMAP, fetch new messages, parse inline.
- **Gmail API integration:** Native Google Workspace support via OAuth + Gmail push notifications.

**Complexity:** High. Requires IO/FS/Net effects, credential management, and state tracking (which messages have been processed).

**Impact:** Very high. Transforms email parsing from a developer tool into an automation product. "Drop an AILANG agent on your inbox and get structured JSON for every email" is a compelling pitch.

---

### P3: Outlook .msg Support

**Problem:** Enterprise email archives often use Outlook's proprietary `.msg` format (OLE2 Compound Document / CFB). This is a binary format completely different from RFC 5322 EML.

**Proposal:** Add an `msg_parser.ail` that reads the OLE2 structure and extracts headers, body (RTF/HTML/plain), and attachments. Map to the same Block ADT.

**Complexity:** High. OLE2/CFB is a complex binary format with FAT-based sector chains. Would need either:
- A pure AILANG implementation (significant effort, ~1000+ lines)
- A `std/ole2` stdlib module in the AILANG runtime

**Impact:** Medium-high for enterprise customers. Most consumer email is EML; .msg is primarily Outlook desktop exports and legal discovery archives.

---

### P4: Calendar Invite Parsing (text/calendar)

**Problem:** Meeting invitations arrive as `text/calendar` MIME parts containing iCalendar (RFC 5545) data. Currently treated as opaque MIME parts.

**Proposal:** Add iCalendar parsing for `VEVENT` components. Extract: summary, start/end time, location, organizer, attendees, description, recurrence rules.

```json
{
  "type": "section",
  "kind": "calendar-event",
  "blocks": [
    {"type": "text", "style": "event-summary", "text": "Q2 Planning Meeting"},
    {"type": "text", "style": "event-time", "text": "2026-04-15 14:00-15:30 UTC"},
    {"type": "text", "style": "event-location", "text": "Zoom (link in description)"},
    {"type": "text", "style": "event-attendees", "text": "alice@co.com, bob@co.com, carol@co.com"}
  ]
}
```

**Complexity:** Low-medium. iCalendar is a text format with key-value pairs and folding (similar to email headers). Core VEVENT parsing is ~200 lines.

**Impact:** Medium. Useful for AI calendar assistants and meeting prep agents. Natural companion to email parsing — many emails contain calendar invites.

---

### P5: S/MIME and PGP Signed/Encrypted Messages

**Problem:** Some enterprise and security-conscious emails use S/MIME or PGP encryption/signing. Currently these appear as opaque `application/pkcs7-mime` or `multipart/signed` MIME parts.

**Proposal:** 
- **Signed messages:** Strip the signature wrapper and parse the inner content normally. Expose signature validity as metadata (if verification keys are available).
- **Encrypted messages:** Out of scope for deterministic parsing (requires private keys). Surface as `[encrypted: S/MIME]` or `[encrypted: PGP]` attachment blocks.

**Complexity:** Low for signed (just unwrap), high for encrypted (key management).

**Impact:** Low-medium. Niche but important for regulated industries.

---

### P6: HTML Email Rendering Improvement — DONE

**Status:** Shipped (2026-04-02)

Added `htmlSanitize` pre-processor to `html_parser.ail` (option 1 from original proposal):
- **Void element closing:** `<br>`, `<meta>`, `<img>`, `<hr>`, `<input>`, `<link>`, `<col>`, `<area>`, `<base>`, `<embed>`, `<source>`, `<track>`, `<wbr>` — all self-closed before XML parsing
- **HTML entity replacement:** 23 common entities (`&mdash;`, `&euro;`, `&nbsp;`, `&copy;`, etc.) replaced with actual Unicode characters via UTF-8 byte construction
- **DOCTYPE stripping:** `<!DOCTYPE ...>` removed before XML parsing
- Case-insensitive tag matching with word boundary checks (won't match `<breaking>` when looking for `<br>`)

Tested on real emails from MailMate inbox — zero HTML parse errors on previously-failing marketing and transactional emails. HTML-only emails now parse fully (headings, tables, lists, images).

3/3 HTML gap checks at 100%.

---

## Prioritization

| ID | Proposal | Effort | Impact | Status |
|----|----------|--------|--------|--------|
| P0 | Attachment chain parsing (text-based) | Medium | High | **DONE** |
| P1 | Thread reconstruction | Medium | High | **DONE** |
| P0a | Office attachment parsing (two-pass) | Medium | High | **DONE** |
| P4 | Calendar invite parsing | Low-Med | Medium | Quick win |
| P6 | HTML email rendering fix | Low | Medium | **DONE** |
| P2 | Inbox monitoring agent | High | Very high | Plan carefully |
| P3 | Outlook .msg support | High | Medium-high | Backlog |
| P5 | S/MIME / PGP | Low-High | Low-medium | Backlog |

**Recommended sequence:** P4 (quick win, extends format coverage) → P2 (the product play).

---

## Open Questions

1. ~~**Attachment parsing depth:**~~ **Resolved.** Text-based attachments (CSV, HTML, MD, EML) parse recursively. Office attachments use two-pass approach (P0a). PDF/images can use AI in Pass 2 when `--deep` + AI capabilities are enabled. Recursion depth: email → attachment → one level of embedded content (no infinite recursion risk since Office docs don't contain emails).
2. **MBOX scale:** What's the largest MBOX we should target? A 10-year Gmail export could be 10+ GB. Streaming vs. load-all?
3. ~~**Thread reconstruction scope:**~~ **Resolved (simple first).** Current implementation handles In-Reply-To graph traversal — covers 1:1, small-group, and standard reply chains. Mailing list threads (which use References without In-Reply-To) partially work via Reference header but may split threads. Revisit when real-world mailing list MBOX files are tested.
4. **Inbox agent product surface:** CLI daemon? Cloud function triggered by Gmail push? MCP tool for Claude? All three?
5. **Privacy:** Email content is inherently sensitive. What guardrails should the inbox agent have? Local-only mode? No-telemetry flag?
6. **Two-pass temp file management (P0a):** Where should temp files go? System temp dir with cleanup, or a configurable `--work-dir`? How to handle cleanup on error/interrupt?
