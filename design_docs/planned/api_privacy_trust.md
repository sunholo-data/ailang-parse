# API Privacy & Trust — Making the Hosted API More Attractive

**Date**: 2026-03-31
**Status**: Planned
**Related**: [WASM Threat Model](wasm_threat_model.md), [v0.10.0 Auth Security](../implemented/v0_10_0/v0_10_0_auth_security.md)

---

## Problem

The "Run Locally" page now clearly presents three tiers: Browser (WASM), API + SDKs, and Local CLI. The API tier currently says "Regional servers (EU, US)" and "Free tier, then paid" but has no concrete privacy commitments. For enterprise and regulated-industry customers, the API needs a stronger trust story to compete with the "just run it locally" option.

The WASM and local tiers are inherently private (data never leaves the user's machine). The API tier needs to earn equivalent trust through transparency and commitments.

---

## Current State

### What we do well
- **No document storage**: Documents are processed in-memory and returned as structured JSON. No files are persisted to GCS or databases.
- **Regional deployment**: Cloud Run supports EU (`europe-west1`) and US (`us-central1`) regions. We can deploy to either or both.
- **Firebase Auth**: All API keys tied to verified Firebase UIDs since v0.10.0.
- **Capability budgets**: Hard limits on AI calls, file ops per request — cost-predictable by design.
- **Request logs**: Capped at 10KB response, 200 entries per user in Firestore.

### What's missing
1. **No explicit data handling policy** on the website
2. **No region selection** — users can't choose EU vs US
3. **No data retention transparency** — users don't know what's logged or for how long
4. **No DPA** (Data Processing Agreement) for enterprise
5. **No deletion endpoint** — users can't purge their request history
6. **No compliance certifications** (SOC2, ISO 27001, GDPR Art. 28)
7. **No encryption-at-rest commitment** documented (GCP provides it, but we don't say so)

---

## Proposed Improvements

### P0 — Low effort, high trust impact

#### 1. Data Handling Statement (website)
Add a clear "How We Handle Your Data" section to the API page:
- Documents are processed in-memory and never stored
- Parsed output is returned to you and discarded server-side
- Request metadata (timestamp, format, page count) is logged for billing only
- No document content is used for training or analytics

**Effort**: Copy change on `api.html`. Half a day.

#### 2. Regional Server Selection
Allow users to choose their API region via a query parameter or header:
- `X-Region: eu` → routes to `europe-west1` Cloud Run instance
- `X-Region: us` → routes to `us-central1` Cloud Run instance
- Default: nearest region (geo-routing via Cloud Run multi-region)

Update SDKs to accept a `region` parameter:
```python
client = AilangParse(region="eu")
```

**Effort**: Deploy second Cloud Run instance + load balancer. SDK change is trivial. 1-2 days.

#### 3. Explicit Retention Policy
Document and enforce:
- Request logs: retained 30 days, then auto-deleted (Firestore TTL)
- API keys: retained until user deletes account
- No document content retained at any point

**Effort**: Add Firestore TTL policy + document on website. Half a day.

### P1 — Medium effort, enterprise unlock

#### 4. Delete My Data Endpoint
```
DELETE /api/v1/privacy/my-data
Authorization: Bearer <api-key>
```
Deletes all request logs, usage history, and API key for the authenticated user. Returns confirmation.

**Effort**: One new AILANG service module + API route. 1 day.

#### 5. Data Processing Agreement (DPA)
Standard GDPR Art. 28 DPA template for Business tier customers:
- Sunholo as data processor, customer as data controller
- Sub-processors listed (GCP Cloud Run, Firestore, Gemini API)
- Standard contractual clauses for international transfers
- Breach notification within 72 hours

**Effort**: Legal template + sign-on-request workflow. 2-3 days legal review.

#### 6. Privacy Dashboard
Add to user dashboard (already exists at `dashboard.html`):
- Show what data we hold (request count, last active, region)
- One-click "Delete all my data" button
- Download request history as JSON
- Show which AI sub-processors were used for their requests

**Effort**: Dashboard UI + 2 API endpoints. 2-3 days.

### P2 — Longer term, competitive moat

#### 7. SOC2 Type II
GCP infrastructure already meets SOC2 controls. Formal certification for Sunholo as an organization would unlock enterprise procurement.

**Effort**: 3-6 months, requires auditor engagement.

#### 8. Bring Your Own Key (BYOK) for AI
Let API users provide their own Gemini/Claude API key for PDF parsing, so document content never touches Sunholo's AI credentials:
```
X-AI-Key: <user's own gemini key>
```
Documents are still processed on our Cloud Run instances but AI calls go directly to the user's own project.

**Effort**: Pass-through in the AILANG AI effect. 1-2 days.

#### 9. End-to-End Encryption Option
For Business tier: client-side encryption of document content before upload, server-side decryption in a TEE (Confidential Computing on GCP), results encrypted before return.

**Effort**: Significant. Requires Confidential VMs + client SDK changes. Weeks.

#### 10. On-Premises / VPC Deployment
For enterprise customers who can't use shared infrastructure:
- Helm chart for GKE deployment in customer's own VPC
- Same AILANG Parse modules, customer's own GCP project
- Sunholo provides support + updates, customer owns data plane

**Effort**: Helm chart + deployment guide. 1-2 weeks. Already partially exists via Sunholo Multivac.

---

## Website Messaging Updates

### API Page (`api.html`)
Add a "Privacy & Trust" section after the SDK section:

**Your data stays yours**
- Documents processed in-memory, never stored
- Regional servers: choose EU or US
- Request metadata retained 30 days for billing, then deleted
- No content used for training or analytics
- GDPR-compliant data deletion on request
- Business tier: DPA available

### Comparison Table (selfhost.html)
Already updated with "Regional servers (EU, US)" — expand to link to the privacy section on api.html.

### Pricing Tiers — Privacy Features

| Feature | Free | Pro | Business |
|---------|------|-----|----------|
| Regional server selection | Default | Choose EU/US | Dedicated region |
| Data retention | 30 days | 30 days | Configurable |
| Delete my data | Yes | Yes | Yes |
| DPA | — | — | Yes |
| BYOK (own AI key) | — | Yes | Yes |
| SLA | — | 99.5% | 99.9% |
| Audit log export | — | — | Yes |

---

## Competitive Positioning

| | AILANG Parse | Unstructured | LlamaParse |
|--|--------------|-------------|------------|
| Browser parsing (zero data sent) | Yes (WASM) | No | No |
| Local CLI (zero cloud) | Yes | Self-host only | No |
| Regional API servers | EU + US | US only | US only |
| No document storage | Yes | Unclear | Unclear |
| Bring your own AI key | Planned | No | No |
| DPA available | Planned | Enterprise | Enterprise |

The unique advantage: **three privacy tiers** from "nothing leaves your browser" to "nothing leaves your region" to "nothing leaves your machine." No competitor offers all three.

---

## Windows CLI Wrapper

**Current state**: `bin/docparse` is a bash script (macOS/Linux only).

**Proposal**: Add `bin/docparse.ps1` (PowerShell) for Windows users. PowerShell is available on all modern Windows (5.1+ built-in, 7+ cross-platform).

The wrapper logic is straightforward — argument parsing, capability detection, and exec. A PowerShell port would be ~150 lines mirroring the bash version. Alternatively, a `.cmd` batch file for minimal Windows environments, though PowerShell is more capable.

**Priority**: P1 — Windows users currently must use `ailang run ...` directly, which works but is verbose. The wrapper is a convenience, not a blocker.

---

## Implementation Order

1. **Data handling statement** on api.html (P0, half day)
2. **Retention policy** with Firestore TTL (P0, half day)
3. **Regional server selection** — second Cloud Run + SDK param (P0, 1-2 days)
4. **Delete my data endpoint** (P1, 1 day)
5. **Privacy dashboard** (P1, 2-3 days)
6. **Windows CLI wrapper** (P1, 1 day)
7. **BYOK for AI** (P2, 1-2 days)
8. **DPA template** (P1, legal review)
9. **SOC2** (P2, 3-6 months)
