# Design Doc: Privacy Policy & Terms of Service Pages

**Status:** Draft for review
**Date:** 2026-04-01
**Author:** Claude (for Mark)

---

## Background

AILANG Parse (docparse) is a paid SaaS product that processes user-uploaded documents via API and browser. It currently has no legal pages. The parent company site (sunholo.com) has a privacy policy but no terms of service, and its privacy policy doesn't cover document parsing, file uploads, or API usage.

**Entity:** Holosun ApS (Denmark) — GDPR applies.
**Key fact:** No Google Analytics or tracking on the docparse site (intentional — avoids cookie/analytics complexity). Analytics exist on www.sunholo.com only.

## Scope

Three deliverables:

1. **`/privacy.html`** — Privacy Policy
2. **`/terms.html`** — Terms of Service
3. **Data Processing Agreement (DPA)** — available as a linked document or dedicated page

All follow the existing docs site pattern (static HTML, shared components.js/site-data.js, same design system). Footer updated to link to both.

---

## GDPR Roles: Controller vs Processor

This is the core legal architecture for the service:

| Party | GDPR Role | Responsibilities |
|-------|-----------|-----------------|
| **Customer** (API caller) | **Data Controller** | Decides what data to upload, must have lawful basis for processing personal data, responsible for data subject rights, must assess whether cloud processing is appropriate for their data |
| **Holosun ApS** | **Data Processor** | Processes data only on controller's instructions, implements appropriate security, assists controller with obligations, maintains Article 30 records, notifies controller of breaches |
| **Google Cloud / Gemini** | **Sub-processor** | Same obligations as processor, bound by contract flowing down from the DPA |
| **Browser WASM / CLI** | **N/A** | Data never reaches our servers — we are not a processor at all for these modes. We provide software, not a service. |

**Key principle:** The customer is responsible for what they upload. We are responsible for processing it securely and only as instructed. We cannot disclaim our processor obligations, but we can (and should) clearly state that the controller bears responsibility for lawfulness of their uploads.

### Recommended language for Terms:

> "You (the customer) are the data controller for any personal data contained in documents you submit to our service. You are responsible for ensuring you have a lawful basis to process this data and for fulfilling your obligations to data subjects. We (Holosun ApS) act as data processor and will process your data only in accordance with your instructions and our Data Processing Agreement.
>
> For documents containing sensitive personal data (Article 9 GDPR), we recommend using our browser-based or CLI parsing modes, which process data entirely on your device without transmitting it to our servers.
>
> When you select AI-assisted parsing, your documents are transmitted to the AI provider you select (e.g., Google Gemini). By using this feature, you instruct us to engage this sub-processor for your parsing request."

---

## What We Must Have as a Data Processor

### Legally Required (GDPR Article 28)

1. **Data Processing Agreement (DPA)** — Contract with customers covering: subject matter, duration, nature/purpose of processing, types of personal data, categories of data subjects, and all eight Article 28(3) obligations. **Use Datatilsynet's standard DPA template** ("Standardkontraktsbestemmelser") as starting point — carries weight with the Danish DPA.

2. **Article 30 Records** — A spreadsheet documenting: what we process, categories of customers, sub-processors, data transfers, security measures. Simple format is fine.

3. **Sub-processor list** — Public page listing Google Cloud and Google Gemini, with links to their DPAs. Must include a notification mechanism for changes (email is fine).

4. **Technical & organisational measures document** — Written description of security: ephemeral processing, TLS, access controls, Cloud Run architecture, breach detection.

5. **Breach notification process** — Documented procedure: how we detect breaches, how we notify affected controllers (without undue delay), who is responsible.

6. **Privacy policy** — For our own data processing (accounts, billing, contact). This is where we're the controller.

### NOT Required

- **ISO 27001 / SOC 2** — Not legally required. Disproportionate for a small SaaS with ephemeral processing. Document actual measures instead.
- **Data Protection Officer (DPO)** — Not required (our core activity is document parsing, not systematic monitoring of data subjects). Designate a privacy contact instead.
- **DPIA** — The controller's obligation, not ours. We must assist if asked.
- **EU representative** — Not needed, we're in Denmark.
- **Cookie consent banner** — No analytics cookies on docparse site, so not needed (only essential Firebase Auth session cookie).

---

## Privacy Policy — Key Sections

### 1. Identity & Contact
- Holosun ApS, Denmark
- Privacy contact: `docparse@sunholo.com`

### 2. Data We Collect

| Category | What | Retention |
|----------|------|-----------|
| **Small documents** | Files sent via API for parsing | **Ephemeral** — processed in memory, discarded after response returned |
| **Large PDFs** | PDFs too large for in-memory processing | **Temporary storage** — stored for processing, **auto-deleted after 1 day** |
| **AI-routed documents** | PDFs/images sent to user-selected AI provider (e.g. Gemini) | Subject to AI provider's data processing terms. We do not retain AI inputs/outputs after the response. |
| **Browser / CLI parsing** | WASM-parsed docs never leave the user's device | **No server involvement.** We are not a data processor for this mode. |
| **API keys & auth** | Firebase Auth tokens, API keys | Until account deletion |
| **Usage metrics** | Request counts, file types, response times (no document content) | 12 months |
| **Contact / email** | Name, email, message | 24 months |

**No website analytics.** The docparse site does not use Google Analytics, tracking pixels, or advertising cookies.

### 3. Legal Basis (GDPR)
- **Contract** (Art. 6(1)(b)) — processing documents you submit via the API
- **Legitimate interest** (Art. 6(1)(f)) — usage metrics for service improvement, security
- **Consent** — contact form submissions

### 4. Data Processor Role
- When you upload documents containing personal data, **you are the data controller**
- We act as **data processor** under Article 28 GDPR
- We process your data only as instructed (to parse and return results)
- We do not anonymise, profile, or make decisions based on document content
- We do not use document content for training, analytics, or any purpose beyond fulfilling your parsing request
- **For sensitive personal data (Art. 9):** We recommend browser-based or CLI parsing, which keeps data entirely on your device

### 5. AI Provider Data Handling
- When you select AI-assisted parsing (PDFs/images), content is sent to the AI provider you configure
- By selecting an AI provider, you instruct us to engage them as a sub-processor
- We use enterprise/Cloud API endpoints (e.g. Google Vertex AI), not consumer APIs — data is not used for model training under Google Cloud's data processing terms
- We do not retain AI inputs or outputs after your response is delivered
- Users should review their chosen AI provider's data processing terms

### 6. Sub-processors

| Provider | Purpose | Location | DPA |
|----------|---------|----------|-----|
| Google Cloud Platform | API hosting (Cloud Run) | EU (europe-west1) | [Google Cloud DPA](https://cloud.google.com/terms/data-processing-addendum) |
| Firebase | Authentication | US (EU-US DPF + SCCs) | [Firebase Data Processing Terms](https://firebase.google.com/terms/data-processing-terms) |
| Google Gemini (Vertex AI) | AI-assisted PDF/image parsing (when selected by user) | Per API config | [Google Cloud DPA](https://cloud.google.com/terms/data-processing-addendum) |

We will notify customers before adding new sub-processors, with the right to object.

### 7. International Transfers
- Primary infrastructure in EU (europe-west1)
- Firebase in US — covered by EU-US Data Privacy Framework + Standard Contractual Clauses as fallback
- AI providers per user selection — Google is on the EU-US DPF list

### 8. Data Subject Rights
Standard GDPR rights (access, rectification, erasure, portability, objection, restriction, withdrawal of consent). Contact: `docparse@sunholo.com`. We will assist data controllers in responding to data subject requests.

### 9. Security
- TLS encryption in transit
- Ephemeral processing: most documents processed in memory only
- Large PDFs: temporary storage with automatic deletion after 1 day
- Cloud Run ephemeral containers
- API key authentication
- No human review of uploaded document content
- Access controls on infrastructure

### 10. Cookies
- **Essential only:** Firebase Auth session cookie
- **No analytics cookies** — we do not use Google Analytics or any tracking
- **No advertising cookies**
- No cookie consent banner needed

---

## Terms of Service — Key Sections

### 1. Service Description
- Document parsing API and browser tool
- Formats: 13 input, 9 output
- AI-assisted parsing for PDFs/images via user-selected providers
- Browser WASM and CLI modes available for local-only processing

### 2. Data Controller Responsibility
- You are the data controller for personal data in your documents
- You are responsible for having a lawful basis to upload and process this data
- You must assess whether cloud processing is appropriate for your data's sensitivity
- For sensitive/special category data, use browser or CLI mode
- We do not anonymise, pseudonymise, or redact data — documents are parsed as-is
- A Data Processing Agreement governs our processor obligations

### 3. Pricing & Billing
- Reference pricing page; tiers (Browser Free, Free API, Pro, Business)
- EUR pricing, monthly billing
- Rate limits per tier
- Right to change pricing with 30 days notice

### 4. Acceptable Use
- No illegal content
- No reverse engineering the parsing engine
- No reselling API access without agreement
- No automated scraping of the documentation site
- Rate limits are hard limits, not suggestions

### 5. Intellectual Property
- Users retain all rights to their uploaded documents and parsed output
- Holosun ApS retains rights to the parsing engine, AILANG runtime, and documentation
- We claim no rights over your document content or parsing results

### 6. Document Handling
- Most documents processed in memory only, not stored
- Large PDFs may be temporarily stored for processing, auto-deleted after 1 day
- No human review of uploaded content
- AI-routed content subject to the AI provider's terms
- By selecting an AI provider, you instruct us to use them as sub-processor

### 7. API Usage
- API keys are confidential; user responsible for securing them
- We may suspend keys for abuse or non-payment
- No SLA for Free tier; Pro/Business SLAs TBD

### 8. Limitation of Liability
- Service provided "as is"
- Not liable for parsing accuracy (deterministic for Office; AI-dependent for PDF)
- Not liable for AI provider actions
- Liability capped at fees paid in prior 12 months

### 9. Termination
- Users can delete account at any time
- We can terminate for breach with 14 days notice
- On termination: API access revoked, any temporarily stored files deleted immediately

### 10. Governing Law
- Danish law (Holosun ApS jurisdiction)
- Copenhagen courts for disputes

### 11. Changes
- 30 days notice for material changes
- Continued use = acceptance

---

## Data Processing Agreement (DPA) — Outline

A separate DPA document (or page) that customers can reference. Based on Datatilsynet's standard template.

### Must contain:
1. Subject matter: document parsing and format conversion
2. Duration: for the term of the service agreement
3. Nature and purpose: parsing uploaded documents, returning structured output
4. Types of personal data: any personal data contained in uploaded documents (determined by controller)
5. Categories of data subjects: determined by controller's use case
6. Processor obligations (all eight from Article 28(3)):
   - Process only on documented instructions
   - Confidentiality commitments for personnel
   - Appropriate technical and organisational measures
   - Sub-processor rules (list + notification + right to object)
   - Assist controller with data subject rights
   - Assist with security obligations, breach notification, DPIAs
   - Delete/return data after service ends (trivially satisfied — we don't store documents long-term)
   - Allow audits / provide compliance information
7. Sub-processor list (Google Cloud, Firebase, Gemini)
8. International transfer mechanisms (SCCs, EU-US DPF)
9. Breach notification: without undue delay to the controller
10. Audit rights: satisfied by providing documentation of measures (proportionate for small SaaS)

### Approach:
- Start from Datatilsynet's "Standardkontraktsbestemmelser" template
- Adapt for docparse's specific service model
- Recommend 1-2 hours of Danish lawyer review (~3,000 DKK)
- Make available as a linked PDF or dedicated page

---

## Key GDPR Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| **AI provider data handling** | HIGH | Use only enterprise API endpoints (Vertex AI, not consumer Gemini). Verify Google Cloud DPA covers our use. Offer non-AI alternatives for sensitive data. |
| **Large PDF temporary storage** | MEDIUM | Auto-delete after 1 day. Encrypt at rest. Document retention clearly in privacy policy. |
| **International transfers** | MEDIUM | EU-US DPF + SCCs as fallback. Monitor for "Schrems III" developments. Document transfer impact assessment. |
| **Special category data uploads** | MEDIUM | Ephemeral processing is strong mitigation. Recommend browser/CLI for sensitive data. Clear controller responsibility language. |
| **Breach notification at scale** | MEDIUM | Maintain logs to identify affected customers (no document content in logs). Have documented response plan. |
| **Datatilsynet enforcement** | LOW | Follow Danish DPA guidance on cloud services. Keep Article 30 records. Document transfer impact assessment. |

---

## Implementation Plan

### New Files
- `docs/privacy.html` — follows existing page template
- `docs/terms.html` — same structure
- DPA document (PDF or HTML page, linked from terms)

### Page Design
- Use `dp-docs-layout` (sidebar + content) like api.html
- Sidebar with section links for easy navigation
- Clean typography — these are reference documents
- Mobile-responsive (768px breakpoint)

### Footer Update
Update `components.js` footer to add Privacy & Terms links:
```
© 2026 Holosun ApS · Privacy · Terms
```

### Cross-links
- Pricing page: "By using our service you agree to our Terms"
- API page: link to terms in authentication section
- Browser demo: reinforce that browser parsing has no server involvement

### Compliance Artefacts (non-page)
- Article 30 records spreadsheet (internal)
- Sub-processor list (can be a section on the privacy page)
- Technical measures document (internal, referenced in DPA)
- Breach notification procedure (internal)
- Transfer impact assessment (internal, for Datatilsynet)

---

## Open Questions for Review

1. **Contact email** — Use `docparse@sunholo.com` or `privacy@sunholo.com`?
2. **SLA for paid tiers** — Any uptime commitments for Pro/Business?
3. **Data retention for usage metrics** — 12 months reasonable?
4. **Large PDF auto-delete** — 1 day confirmed. Is the storage encrypted at rest?
5. **AI provider list** — Currently just Gemini. Keep generic ("user-selected") or enumerate?
6. **DPA format** — Separate PDF, dedicated HTML page, or section within terms?
7. **Governing law** — Danish law + Copenhagen courts. Confirm.
8. **Legal review budget** — Datatilsynet template + 1-2h lawyer review recommended (~3,000 DKK). Worth it?
9. **Should sunholo.com privacy policy be updated** to reference docparse, or keep separate?
10. **Transfer impact assessment** — Datatilsynet expects this for Google Cloud usage. Should we draft one?
