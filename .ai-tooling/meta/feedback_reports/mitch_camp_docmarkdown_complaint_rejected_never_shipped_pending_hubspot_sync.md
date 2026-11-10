# Feedback triage report

- **Source**: mcp.ailang.sunholo.com / submit_feedback
- **Package**: sunholo/ailang_parse v0.55.5, repo ailang-parse
- **Contact route**: public MCP channel from an external agent (no user addressable ID)
- **Local machine date at intake**: 2026-11-08
- **Category label**: docs — actionable item but a positioning/content decision above this bot's authority; no code change warranted by policy.

## Report verbatim

> KnowledgeReady lead feedback (Mitch Camp, FinOps/healthcare document processing,
> ~95% PDF/TIFF corpus, conversation 2026-11-07/08): his group already uses MarkItDown and has
> piloted Docling, hit a real DOCX-conversion roadblock months back, and said explicitly that the
> compelling first pitch for a team like his would have been the DOCX-conversion step itself, not
> OCR speed -- with validated local OCR (competing with Google Document AI) as the natural follow-on,
> since local open-source OCR options "leave plenty to be desired" in his words.
>
> Suggestion: a dedicated landing/doc page for plain DOCX -> clean text/Markdown conversion.
> `docparse --convert` already supports this end to end; this is a positioning/content gap,
> not a missing capability. Mirrors the pattern of the just-shipped pdf-to-word.html page, and
> would give BD partners something to lead with for buyers whose corpus is mostly PDF/TIFF
> (where the native-Office-XML speed/accuracy story doesn't land) rather than only for DOCX-native buyers.

---
ailang_version: v0.57.3
contact: m@sunholo.com

## Triage decision and route taken

1. Checked the claim against package artifacts:
   - README.md Quick Start shows deterministic office parsing plus format conversion via `--convert`.
   - docs/docs.html hub has no card or section covering "DOCX → Markdown / clean text".
     The features group lists templates/pdfs/etc but nothing under an office-format-export heading;
     formats pages target *parsing* in ("Formats"), so cross-target export from DOCX lands between sections.
2. Confirmed there IS support today through existing routes documented on site: from llms-full.txt,
   markdown output mode preserves headings, tables/bold inline structure etc., exposing it
   programmatically even though web copy never surfaces that as its own funnel entry point.
3. So triage = feature request framed by user as suggestion; **kept local**, forward upstream filing needed per policy template guidance which says escalation without shell should rely instead upon notes picked up downstream once merge window reopens.
4. A separate companion design note was placed at `.ai-tooling/meta/design-docs-staging/docx-conversion-landing-page-gap-note-v01b.docmd-feedback-carryover` summarizing what a dedicated page should cover (content inventory drawn straight out of README + llms material above) — parked for next sprint's owner to drop into their PR flow rather than merging blind here.

## Notes carried forward

- Auto-dispatch flag unconfirmed inbound during this session read-back loop.
