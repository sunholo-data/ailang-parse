# Design Doc: Privacy Policy & Terms of Service Pages

**Status:** Draft for review — decisions locked in
**Date:** 2026-04-01
**Author:** Claude (for Mark)

---

## Background

AILANG Parse (docparse) is a paid SaaS product (currently in beta) that processes user-uploaded documents via API and browser. No legal pages exist yet. The parent site (sunholo.com) has a privacy policy but no terms of service, and its privacy policy doesn't cover document parsing.

**Entity:** Holosun ApS (Denmark) — GDPR applies.
**No Google Analytics** on the docparse site (intentional).
**Contact email:** `docparse@sunholo.com`
**Governing law:** Danish law, Copenhagen courts.

## Decisions Made

| Question | Decision |
|----------|----------|
| Contact email | `docparse@sunholo.com` |
| SLA | None yet — service is in beta |
| Governing law | Danish law, Copenhagen courts |
| DPA format | Included on the same terms page (not a separate document) |
| sunholo.com relationship | sunholo.com should link to these docparse terms/privacy pages, keeping them separate (multiple services planned) |
| AI providers | Currently Gemini only, will expand — keep language generic ("user-selected AI provider") |
| Storage | Large files temporarily stored, encrypted at rest (GCS), auto-deleted after 1 day |
| Analytics | None on docparse site — simplifies cookie requirements |
| Beta tag | Add beta badge to website header |

## Scope

Deliverables:

1. **`/privacy.html`** — Privacy Policy
2. **`/terms.html`** — Terms of Service + DPA (combined, DPA as a section)
3. **Beta badge** in header via `components.js`
4. **Footer links** to Privacy & Terms
5. **Transfer Impact Assessment** — done, at `compliance/tia-us-transfers.md`

---

## GDPR Roles

| Party | Role | Responsibilities |
|-------|------|-----------------|
| **Customer** | **Data Controller** | Decides what to upload, must have lawful basis, responsible for data subjects |
| **Holosun ApS** | **Data Processor** | Processes only on instruction, implements security, assists controller, maintains records, notifies of breaches |
| **Google Cloud / Gemini** | **Sub-processor** | Bound by Google Cloud DPA, no model training on customer data |
| **Browser WASM / CLI** | **N/A** | Data never reaches servers — not a processor for these modes |

**Key language for terms:**

> You are the data controller for personal data in documents you upload. You are responsible for lawful basis and data subject obligations. We act as data processor per our DPA below. For sensitive data (GDPR Article 9), we recommend browser or CLI mode — data stays on your device. When you select AI parsing, you instruct us to engage that sub-processor.

---

## What We Need as Data Processor

### Required

1. **DPA** (included in terms page, based on Datatilsynet template)
2. **Article 30 records** (internal spreadsheet)
3. **Sub-processor list** (on privacy page)
4. **Technical measures documentation** (in DPA appendices)
5. **Breach notification procedure** (internal)
6. **Privacy policy**

### Not Required

- ISO 27001 / SOC 2 (not legally required)
- DPO (document parsing ≠ systematic monitoring)
- DPIA (controller's obligation, not ours)
- Cookie consent banner (no analytics cookies)

---

## Privacy Policy Sections

### Data We Collect

| Category | What | Retention |
|----------|------|-----------|
| **Small documents** | Files parsed via API | Ephemeral — in memory, discarded after response |
| **Large files** | Files too large for in-memory | Temporary GCS storage, encrypted at rest, **auto-deleted after 1 day** |
| **AI-routed documents** | Content sent to user-selected AI provider | Per AI provider terms. We don't retain. |
| **Browser / CLI** | Never leaves user's device | No server involvement |
| **API keys & auth** | Firebase Auth | Until account deletion |
| **Usage metrics** | Counts, file types, response times (no content) | 12 months |
| **Contact / email** | Name, email, message | 24 months |

**No website analytics. No tracking cookies. No advertising.**

### Other Sections
- Legal basis: Contract, Legitimate interest, Consent
- Data processor role (clear controller/processor delineation)
- AI provider handling (pass-through, no retention, enterprise API only)
- Sub-processors table (GCP, Firebase, Gemini/Vertex AI with DPA links)
- International transfers (EU primary, Firebase/Vertex AI US via DPF + SCCs)
- Data subject rights
- Security measures
- Cookies (essential only: Firebase Auth session)

---

## Terms of Service Sections

- Service description (beta status noted)
- Data controller responsibility (you decide what to upload)
- No anonymisation disclaimer (we parse as-is, use browser/CLI for sensitive data)
- Pricing & billing (reference pricing page, 30 days notice for changes)
- Acceptable use
- IP (users own their documents and parsed output)
- Document handling (ephemeral + 1-day auto-delete for large files)
- API usage (keys confidential, suspension for abuse)
- Limitation of liability (as-is, liability capped at 12 months fees)
- Termination
- Governing law (Danish, Copenhagen)
- Changes (30 days notice)

---

## DPA (on same page as Terms)

Based on Datatilsynet standard template, adapted for docparse. Includes:

- **Clauses 1-15** from the Datatilsynet template
- **Appendix A** — Processing details (document parsing, personal data types determined by controller, duration = service term)
- **Appendix B** — Sub-processors: Google Cloud (Cloud Run, GCS), Firebase Auth, Vertex AI (Gemini). General authorisation with 30-day notice for additions, right to object.
- **Appendix C** — Instructions: parse documents and return results, no secondary use. Security measures. Breach notification within 24 hours. Erasure: trivially satisfied (no persistent storage, large files auto-deleted within 1 day). Transfers to US via DPF + SCCs.
- **Appendix D** — Liability per main Terms of Service.

Full adapted template provided separately: `compliance/dpa-template.md`

---

## Implementation Plan

### Files to Create
- `docs/privacy.html`
- `docs/terms.html` (includes DPA)

### components.js Changes
1. **Beta badge** after header title
2. **Footer links** to Privacy & Terms

### Cross-links
- Pricing page: "By using our service you agree to our Terms"
- sunholo.com: link to docparse privacy/terms (separate from sunholo.com's own policies)

### Compliance Files (internal, not published)
- `compliance/tia-us-transfers.md` — done
- `compliance/dpa-template.md` — Datatilsynet template adapted for docparse
- `compliance/article-30-records.md` — processing records
- `compliance/breach-procedure.md` — notification process

---

## Transfer Impact Assessment

Completed at `compliance/tia-us-transfers.md`. Summary:

- **Firebase Auth → US**: Very low risk (only auth metadata of B2B developers)
- **Vertex AI → US**: Low risk (ephemeral document processing, opt-in, no retention, no model training)
- **Legal basis**: EU-US DPF + SCCs as fallback
- **Can offer other regions** if requested
- **Annual review** scheduled
