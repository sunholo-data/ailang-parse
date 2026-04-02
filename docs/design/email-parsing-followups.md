# Email Parsing — Follow-up Design Doc

**Status:** Proposal  
**Author:** Mark + Claude  
**Date:** 2026-04-02  
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
- HTML parts fail on non-XML-compliant HTML (self-closing `<meta>`, unquoted attributes). Plain text fallback always works in multipart/alternative.
- No attachment content extraction (binary data is identified but not decoded/parsed)
- No thread reconstruction (References/In-Reply-To headers parsed but not linked)
- No Outlook `.msg` support (binary format, different from EML)

---

## Follow-up Proposals

### P0: Attachment Chain Parsing

**Problem:** Emails frequently contain DOCX, PDF, CSV, or image attachments. We identify them (`[attachment: report.pdf, application/pdf]`) but don't parse their content. This is the most obvious gap — the user has to make a second call to parse the attachment.

**Proposal:** When the parser encounters a base64-encoded attachment with a supported MIME type, optionally decode it and parse it inline using the existing format parsers. The attachment's blocks become nested inside a `SectionBlock` with kind `attachment`.

```json
{
  "type": "section",
  "kind": "attachment",
  "filename": "report.docx",
  "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "blocks": [
    {"type": "heading", "text": "Q1 Revenue Report", "level": 1},
    {"type": "table", "headers": ["Region", "Revenue"], "rows": [["EMEA", "$268k"]]}
  ]
}
```

**Complexity:** Medium. Base64 decoding exists. ZIP extraction for DOCX/PPTX/XLSX needs FS effects (write temp file, extract, parse). PDF/image attachments need AI capability. Could gate behind `--deep` flag or AI capability.

**Impact:** High. This is the "emails are documents that contain other documents" story. A single API call parses the email AND its attachments — no other tool does this.

---

### P1: Thread Reconstruction

**Problem:** Email threads are the natural unit of context for AI reasoning. Individual messages lose the back-and-forth that makes email useful. The `References` and `In-Reply-To` headers are already parsed but not linked.

**Proposal:** Add a `parseThread` function that takes multiple EML files (or an MBOX) and reconstructs the conversation tree using Message-ID/References/In-Reply-To. Output as a `SectionBlock` with kind `thread`, messages ordered chronologically with quote-stripping.

```json
{
  "type": "section",
  "kind": "thread",
  "subject": "Re: Q1 Budget Review",
  "participants": ["Alice Smith", "Bob Jones", "Carol Davis"],
  "messages": [
    {"type": "section", "kind": "thread-message", "blocks": [...]},
    {"type": "section", "kind": "thread-message", "blocks": [...]}
  ]
}
```

**Complexity:** Medium. Header correlation is straightforward. Quote stripping (detecting `> ` prefixed lines and `On DATE, PERSON wrote:` blocks) needs heuristics but is well-understood.

**Impact:** High for AI triage and knowledge-base use cases. An LLM seeing a full thread can understand context, summarize, and respond accurately. Individual messages are often unintelligible without their thread.

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

### P6: HTML Email Rendering Improvement

**Problem:** Our HTML parser uses Go's strict XML parser, which chokes on real-world HTML email (self-closing `<meta>`, unquoted attributes, `<br>` without `/>`). This affects the HTML part of multipart/alternative emails.

**Proposal:** Either:
1. Pre-process HTML to close self-closing tags before XML parsing
2. Add an HTML5-tolerant parser to the AILANG stdlib
3. Use a regex-based fallback that extracts text, headings, lists, and tables from HTML without full DOM parsing

**Complexity:** Low for option 1, medium for option 3, high for option 2.

**Impact:** Medium. Plain text fallback works for multipart/alternative, but HTML-only emails (increasingly common from marketing/transactional senders) need this fix.

---

## Prioritization

| ID | Proposal | Effort | Impact | Priority |
|----|----------|--------|--------|----------|
| P0 | Attachment chain parsing | Medium | High | Do next |
| P1 | Thread reconstruction | Medium | High | Do next |
| P4 | Calendar invite parsing | Low-Med | Medium | Quick win |
| P6 | HTML email rendering fix | Low | Medium | Quick win |
| P2 | Inbox monitoring agent | High | Very high | Plan carefully |
| P3 | Outlook .msg support | High | Medium-high | Backlog |
| P5 | S/MIME / PGP | Low-High | Low-medium | Backlog |

**Recommended sequence:** P6 (unblocks HTML-only emails) → P4 (quick win, extends format coverage) → P0 (the killer feature) → P1 (completes the email story) → P2 (the product play).

---

## Open Questions

1. **Attachment parsing depth:** Should attachment chain parsing be recursive? (Email → DOCX → embedded images → AI descriptions). How deep?
2. **MBOX scale:** What's the largest MBOX we should target? A 10-year Gmail export could be 10+ GB. Streaming vs. load-all?
3. **Thread reconstruction scope:** Should we handle mailing list threads (which break In-Reply-To conventions) or just 1:1 / small-group threads?
4. **Inbox agent product surface:** CLI daemon? Cloud function triggered by Gmail push? MCP tool for Claude? All three?
5. **Privacy:** Email content is inherently sensitive. What guardrails should the inbox agent have? Local-only mode? No-telemetry flag?
