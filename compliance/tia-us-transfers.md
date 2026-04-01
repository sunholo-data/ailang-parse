# Transfer Impact Assessment (TIA)

**Controller:** Holosun ApS, Denmark (CVR: [INSERT])
**Service:** AILANG Parse / docparse — document parsing API
**Date:** 1 April 2026
**Author:** [Data Protection Lead]
**Review date:** 1 April 2027
**Version:** 1.0
**Framework:** EDPB Recommendations 01/2020 on measures that supplement transfer tools

---

## 1. Overview of the Processing

AILANG Parse is a document parsing API that extracts structured content from Office formats (DOCX, PPTX, XLSX, ODT, ODP, ODS, HTML, Markdown, CSV, EPUB) deterministically and from PDFs/images via pluggable AI models. The service is hosted on Google Cloud Run in the EU region `europe-west1` (Belgium).

**Categories of personal data potentially processed:** The service processes documents uploaded by customers. These documents *may* contain personal data depending on the customer's use case. Holosun ApS acts as a **data processor**; the customer (API user) is the controller of any personal data in the documents.

**Data subjects:** Individuals whose data appears in customer-uploaded documents (employees, customers, etc. of the API user).

**Volume:** Up to 500,000 documents/month per customer depending on tier.

---

## 2. Mapping of Transfers to Third Countries

### 2.1 Transfer 1: Firebase Authentication

| Item | Detail |
|---|---|
| **Recipient** | Google LLC (US) — Firebase Authentication |
| **Data transferred** | User email address, authentication tokens, IP address at login, device metadata |
| **Data subjects** | API customers (the developers/companies using the API) — typically <500 individuals |
| **Purpose** | Authenticating API users and issuing access tokens |
| **Transfer mechanism** | EU-US Data Privacy Framework (DPF) — Google LLC is listed on the Data Privacy Framework List. Standard Contractual Clauses (SCCs, June 2021 module) as fallback via Google Cloud Data Processing Addendum. |
| **Data volume** | Low. Authentication events only (login, token refresh). No document content flows through Firebase. |

### 2.2 Transfer 2: Vertex AI (Google Gemini)

| Item | Detail |
|---|---|
| **Recipient** | Google LLC — Vertex AI (Gemini models) |
| **Data transferred** | Document content (PDF pages, images) sent as API calls for AI-assisted parsing |
| **Data subjects** | Individuals whose data appears in customer-uploaded PDFs/images |
| **Purpose** | AI-assisted extraction of structured content from PDFs and images that cannot be parsed deterministically |
| **Transfer mechanism** | EU-US Data Privacy Framework (DPF) + SCCs as fallback. Vertex AI endpoint configured in `europe-west1`; Google's Vertex AI data processing terms apply. |
| **Data volume** | Variable. Only triggered when customer explicitly requests AI parsing (PDF/image files). Office format parsing is fully deterministic and involves no AI call — no transfer occurs. Limited to 1,000 AI parses/month on the highest self-service tier. |
| **Retention** | Ephemeral. Under Vertex AI's data governance terms, customer data submitted via the API is not used to train models and is not retained after processing. Large files temporarily staged in Google Cloud Storage (`europe-west1`, encrypted at rest with AES-256) are auto-deleted after 1 day. |

### 2.3 Transfers NOT present

- **Google Analytics:** Not used on the docparse site.
- **Document storage in US:** All Cloud Run instances and Cloud Storage buckets are in `europe-west1`. Document content does not leave the EU except when sent to Vertex AI as described above.
- **Sub-processors outside US/EU:** None identified.

---

## 3. Assessment of Third Country Legislation (United States)

Following EDPB Recommendations 01/2020, Step 3: assess whether the law or practice of the US impinges on the effectiveness of the transfer tools relied upon.

### 3.1 Relevant US surveillance laws

**FISA Section 702 (Foreign Intelligence Surveillance Act)**
- Allows the US government to compel US "electronic communication service providers" to provide data of non-US persons located outside the US for foreign intelligence purposes.
- Google LLC is an electronic communication service provider subject to FISA 702.
- Relevance: Both Firebase Authentication data and Vertex AI data could theoretically be subject to a FISA 702 directive.

**CLOUD Act (Clarifying Lawful Overseas Use of Data Act, 2018)**
- Allows US law enforcement to compel US-based providers to produce data they control regardless of where the data is stored geographically.
- Relevance: Even though data resides in `europe-west1`, Google could be compelled to produce it.

**Executive Order 14086 (October 2022)**
- Implements proportionality and necessity requirements on US signals intelligence.
- Establishes the Data Protection Review Court (DPRC) as a redress mechanism for EU individuals.
- Basis for the EU-US Data Privacy Framework adequacy decision (July 2023, renewed/confirmed).

### 3.2 Assessment of practical risk

We assess the *likelihood* and *severity* of US government access to the specific data transferred by this service:

| Factor | Assessment |
|---|---|
| **Nature of data** | Firebase: email + IP of a small number of B2B developers. Vertex AI: document fragments processed ephemerally. Neither category is of typical intelligence interest. |
| **Data subjects** | Primarily European SME developers/companies. Not targeted populations. |
| **Volume** | Low (Firebase) to moderate (Vertex AI), all ephemeral. |
| **Retention by Google** | Firebase auth logs: standard retention. Vertex AI: no retention of input/output data per Google's data processing terms. |
| **Sector** | Document parsing SaaS. Not in a sector of heightened surveillance interest (unlike telecoms, finance, defence). |
| **Google's track record** | Google publishes transparency reports. In 2024, Google received ~85,000 US government data requests globally, the vast majority being criminal law enforcement (not FISA). The probability of a FISA 702 directive targeting a small Danish SaaS company's document parsing data is assessed as **very low**. |
| **EO 14086 safeguards** | Proportionality and necessity requirements now bind US intelligence agencies. The DPRC provides redress. The European Commission assessed these safeguards as adequate in the DPF adequacy decision. |

**Overall assessment of US legislation risk: LOW.**

The data transferred is not of the type, volume, or subject matter likely to attract intelligence interest. The DPF adequacy decision and EO 14086 safeguards substantially reduce the residual risk identified in Schrems II.

---

## 4. Supplementary Measures

Even with the DPF adequacy finding and low assessed risk, the following supplementary measures are in place:

### 4.1 Technical measures

| Measure | Detail |
|---|---|
| **EU data residency** | All compute (Cloud Run) and storage (GCS) in `europe-west1`. No US region instances. |
| **Encryption in transit** | All API calls use TLS 1.2+. Document uploads, Firebase auth, and Vertex AI calls are encrypted end-to-end in transit. |
| **Encryption at rest** | GCS buckets use AES-256 encryption (Google-managed keys). |
| **Ephemeral processing** | Documents are parsed in memory. No persistent storage of document content. Large files temporarily staged in GCS are auto-deleted after 1 day via lifecycle policy. |
| **No training on customer data** | Vertex AI terms prohibit use of customer data for model training. |
| **Minimal data to Firebase** | Only authentication data (email, token) flows to Firebase. No document content. |
| **AI parsing is opt-in** | The Vertex AI transfer only occurs when the customer explicitly requests AI parsing for PDF/image files. Deterministic Office parsing involves zero data transfer to US. |
| **Region flexibility** | Holosun ApS can provision alternative regions on request for customers with heightened requirements. |

### 4.2 Contractual measures

| Measure | Detail |
|---|---|
| **Google Cloud DPA** | Google's Data Processing Addendum incorporates SCCs (2021 modules) and commits to challenging disproportionate government access requests. |
| **DPF certification** | Google LLC is certified under the EU-US Data Privacy Framework. |
| **Holosun ApS DPA** | Our DPA with customers specifies that document content is processed only on instruction, with no secondary use, and details the sub-processor chain. |

### 4.3 Organisational measures

| Measure | Detail |
|---|---|
| **Sub-processor register** | Maintained and available to customers. Currently: Google Cloud (Cloud Run, GCS, Vertex AI, Firebase Auth). |
| **Annual TIA review** | This assessment is reviewed annually or when material changes occur (new sub-processor, change in US law, invalidation of DPF). |
| **Monitoring DPF status** | Holosun ApS monitors CJEU/EDPB developments regarding the DPF adequacy decision. If invalidated, SCCs remain as fallback and this TIA will be immediately re-evaluated. |

---

## 5. Overall Risk Assessment

| Transfer | Legal basis | Risk of problematic access | Supplementary measures | Residual risk |
|---|---|---|---|---|
| Firebase Authentication | DPF + SCCs | Very low — only auth metadata of B2B developers | EU residency for all other data; minimal data scope | **Very low** |
| Vertex AI (Gemini) | DPF + SCCs | Low — ephemeral document processing, no retention | EU region, opt-in only, no model training, auto-delete | **Low** |

**Aggregate assessment:** The transfers do not undermine the level of protection guaranteed by the GDPR. The supplementary measures, combined with the DPF adequacy decision and the ephemeral nature of the processing, reduce residual risk to an acceptable level.

---

## 6. Conclusion and Recommendations

### Conclusion

Based on this assessment, Holosun ApS may continue the identified transfers to Google LLC in the United States for the purposes of Firebase Authentication and Vertex AI document parsing. The transfers rely on the EU-US Data Privacy Framework adequacy decision as the primary transfer mechanism, with Standard Contractual Clauses as a fallback. The nature of the data (B2B authentication metadata and ephemerally processed document content), combined with the technical and organisational measures in place, means the risk of problematic government access is very low.

### Recommendations

1. **Monitor the DPF:** If the CJEU invalidates the DPF adequacy decision (as it did Safe Harbor and Privacy Shield), immediately reassess. SCCs alone may require additional technical measures such as customer-managed encryption keys (CMEK).

2. **Evaluate CMEK for Vertex AI:** For customers processing sensitive personal data categories (Article 9), consider offering customer-managed encryption keys on GCS staging buckets as an additional safeguard. This is not currently necessary for the general service but could be offered as a Business-tier option.

3. **Firebase Auth alternatives:** Monitor the availability of EU-only authentication services. If a fully EU-based alternative becomes practical without degrading service quality, evaluate migration to eliminate Transfer 1 entirely.

4. **Customer transparency:** Ensure the privacy notice and DPA clearly disclose that (a) authentication data is processed by Firebase (US) and (b) AI parsing of PDFs/images involves Vertex AI (US, ephemeral). Customers who process only Office formats can be informed that no US transfer occurs for their document content.

5. **Annual review:** Repeat this TIA by April 2027 or earlier if triggered by:
   - Invalidation or modification of the DPF adequacy decision
   - Material change in US surveillance law
   - Addition of a new sub-processor
   - Significant change in data types or volume processed

---

## Appendix A: Relevant Legal References

- GDPR Chapter V (Articles 44-49) — Transfers to third countries
- CJEU C-311/18 (*Schrems II*), 16 July 2020
- European Commission Implementing Decision (EU) 2023/1795 of 10 July 2023 (EU-US DPF adequacy)
- EDPB Recommendations 01/2020 on supplementary measures (v2.0, June 2021)
- Executive Order 14086, 7 October 2022
- FISA Section 702, 50 U.S.C. § 1881a
- CLOUD Act, 18 U.S.C. § 2713
- Google Cloud Data Processing Addendum (current version)
- Google Vertex AI Service Specific Terms

## Appendix B: Document Approval

| Role | Name | Date | Signature |
|---|---|---|---|
| Prepared by | | | |
| Reviewed by | | | |
| Approved by | | | |

---

*This document is maintained as part of Holosun ApS's GDPR compliance records under Article 5(2) accountability principle.*
