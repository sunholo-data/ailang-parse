# DocParse v0.8.0 — Per-User API Keys & Cloud Deployment

**Status**: IMPLEMENTED (2026-03-19) — Note: `/api/v1/keys/generate` was removed in v0.10.0. All key generation now uses device auth flow. See `v0_10_0_auth_security.md`.
**Theme**: Self-service API key management, tiered access control, and production deployment via YOUR_GCP_PROJECT Terraform
**Depends on**: v0.7.0 (API server), v0.6.0 (generation, for convert/generate endpoints)

## Motivation

DocParse has a working API server (v0.7.0) with native and Unstructured-compatible endpoints, but no auth, no deployment infrastructure, and no way for users to self-serve. This milestone turns DocParse from a demo into a product:

1. **Self-service API keys**: Users sign up on the static website (docs/), generate their own API key, and start parsing documents immediately
2. **Tiered access control**: Free/Pro/Enterprise tiers enforced at two levels — per-request AILANG capability budgets (hard type-level guarantee) and per-period Firestore quota tracking (cumulative metering)
3. **Production deployment**: Terraform in YOUR_GCP_PROJECT provisions all GCP infrastructure; CI/CD rebuilds on push
4. **Reusable module**: The api_keys module is designed for extraction into a shared AILANG module repo for use by other AILANG services

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│  docs/ (Static Website — GitHub Pages)                           │
│  ├── index.html           — marketing / landing page             │
│  ├── dashboard.html       — sign in + generate/view API keys     │
│  └── js/firebase.js       — Firebase Auth + Firestore client SDK │
│                                                                  │
│  Firebase Auth handles sign-in (Google/email), runs client-side  │
│  Dashboard calls Cloud Run API for key generation                │
└──────────┬───────────────────────────────────────────────────────┘
           │ POST /api/v1/keys/generate (with Firebase ID token)
           ▼
┌──────────────────────────────────────────────────────────────────┐
│  Cloud Run: docparse-api (single service)                        │
│                                                                  │
│  ┌─────────────────────────────────────┐                         │
│  │  Auth Middleware                     │                         │
│  │  1. Read x-api-key header           │                         │
│  │  2. Hash key → lookup in Firestore  │                         │
│  │  3. Check tier + cumulative quota   │                         │
│  │  4. Set AILANG capability budget    │                         │
│  └──────────┬──────────────────────────┘                         │
│             │                                                    │
│  ┌──────────▼──────────────────────────┐                         │
│  │  API Endpoints                      │                         │
│  │  /api/v1/parse        — parse doc   │                         │
│  │  /api/v1/convert      — convert doc │                         │
│  │  /api/v1/keys/*       — key mgmt   │                         │
│  │  /general/v0/general  — Unstructured│                         │
│  └──────────┬──────────────────────────┘                         │
│             │                                                    │
│  ┌──────────▼──────────────────────────┐                         │
│  │  Firestore ("docparse" database)    │                         │
│  │  api_keys/{hash}  — key + tier      │                         │
│  │  usage/{auto_id}  — request logs    │                         │
│  └─────────────────────────────────────┘                         │
└──────────────────────────────────────────────────────────────────┘
```

## Decision: Application-Level Auth (not GCP API Gateway)

### Why NOT GCP API Gateway for v1

GCP API Gateway validates **GCP-managed API keys** — project-scoped keys created in the Cloud Console. These are designed for identifying which GCP project a client belongs to, not for per-user tiering.

To use API Gateway for per-user auth, we'd need to:
- Create a GCP API key per user (programmatically, via `google_apikeys_key` Terraform resource)
- Map GCP keys to tiers in a separate system
- Lose the ability to enforce AILANG capability budgets per tier (the budget selection happens in application code)

API Gateway also has limitations:
- **32MB request/response limit** (fine for DocParse)
- **No streaming** (not needed)
- **OpenAPI spec required** for every config change (adds deploy friction)
- **Payload inspection** adds latency (~10-20ms per request)

### Why Application-Level Auth

- **Full control**: Key format, tier mapping, quota logic all in AILANG code
- **AILANG capability budgets**: Tier → budget profile is set in the same process that handles the request — no external system can enforce this
- **Simpler infrastructure**: One Cloud Run service, one Firestore database, no API Gateway
- **Already built**: `api_keys.ail` already implements generate/list/revoke/validate against Firestore

### Phase 2: Add API Gateway as Infrastructure Shield

Once there are paying users, add API Gateway in front of Cloud Run for:
- DDoS protection (GCP-managed, absorbs volumetric attacks)
- Global rate limiting (before requests reach Cloud Run, prevents cost spikes)
- OpenAPI spec as public documentation
- The app still does per-user tier validation; Gateway is just the outer shield

## Tier System

### Tiers and Limits

| | Free | Pro | Enterprise |
|---|---|---|---|
| **Monthly price** | $0 | $29/mo | Custom |
| **Requests/day** | 20 | 2,000 | Unlimited |
| **Pages/month** | 100 | 10,000 | 100,000 |
| **Max file size** | 5MB | 25MB | 50MB |
| **AI pages/request** | 5 | 50 | 500 |
| **FS ops/request** | 100 | 5,000 | 50,000 |
| **Concurrent requests** | 1 | 5 | 20 |
| **Rate limit** | 1 req/s | 10 req/s | 50 req/s |
| **Formats** | All 13 | All 13 | All 13 + priority |
| **Support** | Community | Email | Dedicated |

### Two-Layer Enforcement

Enforcement happens at two distinct layers, each doing what it's good at:

#### Layer 1: Cumulative Quota (Firestore — per period)

Tracks how many requests/resources a user has consumed over time. Checked **before** processing each request.

```
Request arrives with x-api-key
  → Hash key → Firestore lookup → get tier + usage counters
  → Is requests_today < tier.requests_per_day?        → 429 if no
  → Is pages_this_month < tier.pages_per_month?       → 429 if no
  → Is request within rate limit (1/s, 10/s, 100/s)?  → 429 if no
  → Allow request through
```

**Reset mechanism**: Cloud Scheduler triggers a Cloud Run endpoint daily at midnight UTC to reset `requests_today`. Monthly counters reset on the 1st.

**Race condition handling**: Firestore transactions ensure atomic read-check-increment. Two simultaneous requests from the same key can't both sneak past the quota.

#### Layer 2: Per-Request Budget (AILANG Capability Budgets — per request)

Controls what a single request can do. This is the hard type-level guarantee — exceed it and the AILANG runtime halts the request deterministically.

```
Tier lookup → set budget profile:
  Free:       AI @limit=5,   FS @limit=100
  Pro:        AI @limit=50,  FS @limit=5000
  Enterprise: AI @limit=500, FS @limit=50000

Request processing runs within this budget.
Budget exceeded → runtime halts → return 400 "Budget exceeded for tier"
```

**Why both layers are needed**:
- Budgets alone: a free user calls the API 10,000 times at 5 pages each = 50,000 pages (no cumulative limit)
- Quotas alone: a single request could consume unbounded AI/FS resources (no per-request limit)
- Together: quotas limit total usage, budgets limit per-request cost

**The unique value proposition**: AILANG capability budgets are not middleware rate limiting bolted on after the fact. They're a type-level guarantee — you can prove to customers (via Z3 verification) that their free tier literally cannot make more than 5 AI calls per request. This is billing enforcement in the type system.

## Firestore Schema

### Database: `docparse` (dedicated, separate from default)

```
api_keys/{sha256_hash_prefix_12}
  ├── user_id: string          # Firebase Auth UID
  ├── key_hash: string         # Full SHA-256 hash (for validation)
  ├── label: string            # User-provided label ("my-app", "testing")
  ├── tier: string             # "free" | "pro" | "enterprise"
  ├── active: bool             # false = revoked
  ├── created: timestamp
  ├── last_used: timestamp
  ├── revoked_at: timestamp    # null if active
  │
  ├── quota: map
  │   ├── requests_per_day: int
  │   ├── pages_per_month: int
  │   ├── max_file_size_mb: int
  │   ├── ai_limit: int        # AILANG AI budget per request
  │   └── fs_limit: int        # AILANG FS budget per request
  │
  └── usage: map
      ├── requests_today: int
      ├── pages_this_month: int
      ├── total_requests: int
      ├── total_pages: int
      ├── last_reset_daily: timestamp
      └── last_reset_monthly: timestamp

usage_logs/{auto_id}
  ├── key_id: string           # First 12 chars of hash
  ├── user_id: string
  ├── endpoint: string         # "/api/v1/parse", "/general/v0/general"
  ├── timestamp: timestamp
  ├── duration_ms: int
  ├── pages_processed: int
  ├── ai_calls: int
  ├── input_format: string
  ├── file_size_bytes: int
  ├── status: string           # "success" | "error" | "quota_exceeded" | "budget_exceeded"
  └── error_message: string    # null on success
```

### Firestore Security Rules

```
rules_version = '2';
service cloud.firestore {
  match /databases/docparse/documents {

    // API keys: only the Cloud Run service account can read/write
    // Users never access Firestore directly for keys — they go through the API
    match /api_keys/{keyDoc} {
      allow read, write: if false;  // Server-side only via ADC
    }

    // Usage logs: same — server-side only
    match /usage_logs/{logDoc} {
      allow read, write: if false;
    }
  }
}
```

Note: Unlike website-builder (where the browser talks to Firestore directly), DocParse keys are server-side only. The Cloud Run service uses ADC (Application Default Credentials) to access Firestore. The browser never touches the api_keys collection.

## API Endpoints

### Key Management (requires Firebase Auth ID token)

These endpoints validate the user via Firebase Auth ID token in the `Authorization: Bearer <token>` header. The token proves who the user is; the key management endpoints then operate on that user's keys.

```
POST /api/v1/keys/generate
  Headers: Authorization: Bearer <firebase_id_token>
  Body: {"label": "my-app"}
  Response: {"status": "ok", "key": "dp_a1b2c3d4...", "keyId": "abc123...", "tier": "free"}
  Note: raw key shown ONCE — store it immediately

GET /api/v1/keys/list
  Headers: Authorization: Bearer <firebase_id_token>
  Response: {"keys": [{"keyId": "abc123", "label": "my-app", "tier": "free", "created": "...", "active": true}]}

POST /api/v1/keys/revoke
  Headers: Authorization: Bearer <firebase_id_token>
  Body: {"keyId": "abc123"}
  Response: {"status": "ok", "message": "Key revoked"}

GET /api/v1/keys/usage
  Headers: Authorization: Bearer <firebase_id_token>
  Response: {"requests_today": 12, "pages_this_month": 67, "quota": {"requests_per_day": 20, "pages_per_month": 100}}
```

### Document Parsing (requires API key)

These endpoints validate via `x-api-key` header (or `unstructured-api-key` for compat). No Firebase token needed — the API key is self-contained.

```
POST /api/v1/parse
  Headers: x-api-key: dp_a1b2c3d4...
  Body: multipart/form-data with file
  Response: parsed blocks JSON

POST /api/v1/convert
  Headers: x-api-key: dp_a1b2c3d4...
  Body: multipart/form-data with file + target_format
  Response: converted file binary

POST /general/v0/general
  Headers: unstructured-api-key: dp_a1b2c3d4...
  Body: multipart/form-data (Unstructured format)
  Response: Unstructured element JSON
```

### Health (no auth)

```
GET /api/v1/health     → no auth required
GET /api/_meta/docs    → Swagger UI, no auth
```

## Request Flow (Detailed)

```
1. Request arrives at Cloud Run
   │
2. Read auth header:
   ├── x-api-key / unstructured-api-key → API key flow (parsing endpoints)
   └── Authorization: Bearer <token>     → Firebase Auth flow (key mgmt endpoints)
   │
3. API Key Flow:
   ├── Check key format: starts with "dp_", length 35 → 401 if invalid
   ├── Hash key (SHA-256 when std/crypto ships, djb2 for now)
   ├── Firestore: GET api_keys/{hash_prefix_12}
   ├── Check: document exists, active == true, key_hash matches → 401 if no
   ├── Check: requests_today < quota.requests_per_day → 429 "Daily quota exceeded"
   ├── Check: pages_this_month < quota.pages_per_month → 429 "Monthly quota exceeded"
   ├── Set AILANG budget: AI @limit={quota.ai_limit}, FS @limit={quota.fs_limit}
   ├── Process request within budget
   ├── On success: Firestore transaction → increment usage counters
   └── Return response
   │
4. Firebase Auth Flow:
   ├── Verify Firebase ID token (via Google's public keys)
   ├── Extract user_id from token
   ├── Execute key management operation for that user_id
   └── Return response
```

## Terraform Infrastructure (YOUR_GCP_PROJECT repo)

### New File: `terraform/docparse.tf`

```hcl
# DocParse API — Cloud Run + Firestore + Firebase

# ══════════════════════════════════════════════════
# CLOUD RUN SERVICE
# ══════════════════════════════════════════════════

resource "google_cloud_run_v2_service" "docparse" {
  count    = var.bootstrap ? 0 : 1
  name     = "${var.prefix}-docparse-api"
  location = var.region
  project  = var.project_id

  template {
    service_account = google_service_account.docparse.email

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/ailang/${var.prefix}-docparse:${var.docparse_image_tag}"

      ports {
        container_port = 8080
      }

      env {
        name  = "PORT"
        value = "8080"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "FIRESTORE_DATABASE"
        value = var.docparse_firestore_database
      }
      env {
        name  = "FIRESTORE_COLLECTION"
        value = "api_keys"
      }
      env {
        name  = "GOOGLE_API_KEY"
        value = ""  # Force ADC for Vertex AI
      }

      resources {
        limits = {
          cpu    = var.docparse_cpu
          memory = var.docparse_memory
        }
      }
    }

    scaling {
      min_instance_count = var.docparse_min_instances
      max_instance_count = 10
    }
  }

  depends_on = [google_project_service.apis]
}

# Allow unauthenticated access (API key checked in application layer)
resource "google_cloud_run_v2_service_iam_member" "docparse_public" {
  count    = var.bootstrap ? 0 : 1
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.docparse[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ══════════════════════════════════════════════════
# DEDICATED FIRESTORE DATABASE
# ══════════════════════════════════════════════════

resource "google_firestore_database" "docparse" {
  provider    = google-beta
  project     = var.project_id
  name        = var.docparse_firestore_database
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  deletion_policy = "DELETE"  # Change to PRESERVE for prod

  depends_on = [google_project_service.apis]
}

# Composite index for usage queries
resource "google_firestore_index" "docparse_usage_by_key" {
  project    = var.project_id
  database   = google_firestore_database.docparse.name
  collection = "usage_logs"

  fields {
    field_path = "key_id"
    order      = "ASCENDING"
  }
  fields {
    field_path = "timestamp"
    order      = "DESCENDING"
  }
}

# ══════════════════════════════════════════════════
# FIREBASE WEB APP (for docs/ dashboard)
# ══════════════════════════════════════════════════

resource "google_firebase_web_app" "docparse" {
  provider     = google-beta
  project      = var.project_id
  display_name = "DocParse Portal"

  depends_on = [google_firebase_project.default]
}

data "google_firebase_web_app_config" "docparse" {
  provider   = google-beta
  project    = var.project_id
  web_app_id = google_firebase_web_app.docparse.app_id
}

# ══════════════════════════════════════════════════
# SERVICE ACCOUNT
# ══════════════════════════════════════════════════

resource "google_service_account" "docparse" {
  project      = var.project_id
  account_id   = "sa-docparse"
  display_name = "DocParse API Service Account"
}

# Firestore read/write on docparse database
resource "google_project_iam_member" "docparse_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.docparse.email}"
}

# Vertex AI for PDF/image parsing
resource "google_project_iam_member" "docparse_vertex" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.docparse.email}"
}

# Cloud Trace
resource "google_project_iam_member" "docparse_trace" {
  project = var.project_id
  role    = "roles/cloudtrace.agent"
  member  = "serviceAccount:${google_service_account.docparse.email}"
}

# Logging
resource "google_project_iam_member" "docparse_logging" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.docparse.email}"
}
```

### New Variables in `variables.tf`

```hcl
# DocParse configuration
variable "docparse_cpu" {
  description = "CPU allocation for DocParse API service"
  type        = string
  default     = "2"
}

variable "docparse_memory" {
  description = "Memory allocation for DocParse API service"
  type        = string
  default     = "2Gi"
}

variable "docparse_min_instances" {
  description = "Minimum instances for DocParse API (0 = scale to zero)"
  type        = number
  default     = 0
}

variable "docparse_image_tag" {
  description = "Docker image tag for DocParse API"
  type        = string
  default     = "latest"
}

variable "docparse_firestore_database" {
  description = "Name of the dedicated Firestore database for DocParse"
  type        = string
  default     = "docparse"
}
```

### New Outputs in `outputs.tf`

```hcl
output "docparse_api_url" {
  description = "DocParse API URL"
  value       = var.bootstrap ? "" : google_cloud_run_v2_service.docparse[0].uri
}

output "docparse_firebase_config" {
  description = "Firebase config for DocParse portal (docs/dashboard.html)"
  value       = var.bootstrap ? {} : data.google_firebase_web_app_config.docparse
  sensitive   = false
}
```

### CI/CD: New Trigger

Add to `YOUR_BUILD_PROJECT` project:

```bash
gcloud builds triggers create github \
  --project=YOUR_BUILD_PROJECT \
  --region=europe-west3 \
  --name=docparse-dev \
  --repository=projects/YOUR_BUILD_PROJECT/locations/europe-west3/connections/github/repositories/sunholo-data-docparse \
  --branch-pattern='^main$' \
  --build-config=cloudbuild.yaml \
  --service-account=projects/YOUR_BUILD_PROJECT/serviceAccounts/YOUR_BUILD_SA \
  --substitutions=_TARGET_PROJECT=YOUR_GCP_PROJECT,_REGION=europe-west1,_PREFIX=ailang-dev
```

DocParse repo needs a `cloudbuild.yaml`:

```yaml
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', '${_REGION}-docker.pkg.dev/${_TARGET_PROJECT}/ailang/${_PREFIX}-docparse:latest', '.']
  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', '${_REGION}-docker.pkg.dev/${_TARGET_PROJECT}/ailang/${_PREFIX}-docparse:latest']
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    entrypoint: 'gcloud'
    args: ['run', 'services', 'update', '${_PREFIX}-docparse-api',
           '--image', '${_REGION}-docker.pkg.dev/${_TARGET_PROJECT}/ailang/${_PREFIX}-docparse:latest',
           '--region', '${_REGION}', '--project', '${_TARGET_PROJECT}']
substitutions:
  _TARGET_PROJECT: YOUR_GCP_PROJECT
  _REGION: europe-west1
  _PREFIX: ailang-dev
options:
  logging: CLOUD_LOGGING_ONLY
```

## Website Dashboard (docs/dashboard.html)

Static HTML/JS page on GitHub Pages. Uses Firebase JS SDK client-side.

### User Flow

```
1. User visits docs/dashboard.html
2. Clicks "Sign in with Google" → Firebase Auth popup
3. Dashboard shows:
   ├── API Keys table (label, created, status, usage)
   ├── "Generate New Key" button
   ├── Usage chart (requests today, pages this month)
   └── Tier info + upgrade CTA
4. User clicks "Generate New Key":
   ├── Prompt for label ("my-app", "testing")
   ├── POST /api/v1/keys/generate with Firebase ID token
   ├── Modal shows raw key: "dp_a1b2c3d4e5f6..."
   ├── "Copy to clipboard" button
   └── Warning: "This key will not be shown again"
5. User copies key, uses it in their code
```

### Firebase Config

```javascript
const firebaseConfig = {
  apiKey: "...",           // from terraform output docparse_firebase_config
  authDomain: "YOUR_GCP_PROJECT.firebaseapp.com",
  projectId: "YOUR_GCP_PROJECT",
};

firebase.initializeApp(firebaseConfig);
const auth = firebase.auth();

// Sign in
async function signIn() {
  const provider = new firebase.auth.GoogleAuthProvider();
  await firebase.auth().signInWithPopup(provider);
}

// Generate key
async function generateKey(label) {
  const token = await auth.currentUser.getIdToken();
  const response = await fetch('https://docparse-api-xxxxx.run.app/api/v1/keys/generate', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ label }),
  });
  return response.json();  // { key: "dp_...", keyId: "..." }
}
```

## Changes to api_keys.ail

The existing module needs these additions for v0.8.0:

### 1. Tier + Quota Fields in Key Documents

Currently stores: `userId`, `keyHash`, `label`, `created`, `active`
Add: `tier`, `quota`, `usage` maps (see Firestore schema above)

### 2. Quota Check Function (new)

```ailang
-- Check cumulative quota before allowing request.
-- Returns Ok(tier) if within quota, Err(message) if exceeded.
export func checkQuota(rawKey: string) -> Result<string, string> ! {IO, Net, Env, Clock}
```

### 3. Usage Increment Function (new)

```ailang
-- Increment usage counters after successful request.
-- Uses Firestore transaction for atomic read-check-increment.
export func recordUsage(rawKey: string, pagesProcessed: int, aiCalls: int) -> string ! {IO, Net, Env, Clock}
```

### 4. Firebase ID Token Validation (new)

```ailang
-- Verify Firebase ID token using Google's public keys.
-- Returns userId if valid.
export func verifyFirebaseToken(idToken: string) -> string ! {Net}
```

### 5. Quota Reset Endpoint (new, for Cloud Scheduler)

```ailang
-- Reset daily/monthly counters. Called by Cloud Scheduler.
@route("POST", "/api/v1/admin/reset-quotas")
export func resetQuotas(resetType: string) -> string ! {IO, Net, Env, Clock}
```

### 6. SHA-256 Hashing

Current hashing is a simple djb2-style hash (not cryptographic). When AILANG ships `std/crypto`, switch to SHA-256. For now, the djb2 hash is sufficient for key identification — the security model doesn't depend on hash collision resistance because we also compare the full hash string.

## Upgrade Path (Free → Paid)

### Phase 1: Manual (launch)
- User contacts us → we update Firestore tier field manually
- `gcloud firestore documents update` or admin endpoint

### Phase 2: Stripe Integration (when there are paying users)
- docs/ adds Stripe Checkout for Pro tier
- Stripe webhook → Cloud Run endpoint → update tier in Firestore
- No new key needed — same key, higher limits

### Phase 3: Self-Service Portal
- Full dashboard with billing history, invoices, team management
- Automatic downgrade on payment failure (tier → "free", quotas reset)

## Cost Estimate

### Infrastructure (monthly)

| Resource | Free Tier | With Users |
|----------|-----------|------------|
| Cloud Run (scale-to-zero, 2 vCPU) | ~$0 | ~$15-40 |
| Firestore (docparse DB) | ~$0 | ~$1-5 |
| Vertex AI (Gemini Flash, PDF only) | ~$0 | ~$5-20 |
| Firebase Auth | $0 | $0 (< 50K MAU) |
| Artifact Registry | ~$0.10 | ~$0.10 |
| **Total** | **~$0** | **~$20-65** |

### Revenue Model

| Tier | Price | Margin at 100 users |
|------|-------|---------------------|
| Free | $0 | N/A (acquisition) |
| Pro | $29/mo | ~$25/user (Vertex AI cost ~$4/user at avg usage) |
| Enterprise | Custom | High margin (volume discounts on Vertex AI) |

Break-even: ~3 Pro users cover the infrastructure.

## Implementation Plan

### Phase 1: Terraform Infrastructure (YOUR_GCP_PROJECT)
- [ ] Add `terraform/docparse.tf` (Cloud Run, Firestore, SA, IAM)
- [ ] Add variables to `terraform/variables.tf`
- [ ] Add outputs to `terraform/outputs.tf`
- [ ] Add docparse to `terraform/environments/dev/terraform.tfvars`
- [ ] `terraform plan` and `terraform apply` for dev
- [ ] Create Cloud Build trigger for docparse repo

### Phase 2: API Key Enhancements (docparse repo)
- [ ] Add tier + quota + usage fields to `api_keys.ail`
- [ ] Implement `checkQuota()` with Firestore transaction
- [ ] Implement `recordUsage()` with atomic increment
- [ ] Implement `verifyFirebaseToken()` for key management endpoints
- [ ] Add quota reset endpoint for Cloud Scheduler
- [ ] Update `api_server.ail` to call quota check before processing

### Phase 3: Website Dashboard (docparse repo, docs/)
- [ ] Create `docs/dashboard.html` with Firebase Auth
- [ ] "Generate Key" flow with one-time key display
- [ ] Key list table with status + usage
- [ ] Usage chart (requests today, pages this month)
- [ ] Responsive design, works on mobile

### Phase 4: Deploy & Test End-to-End
- [ ] Build and push Docker image
- [ ] Deploy to Cloud Run (dev environment)
- [ ] Smoke test: sign up → generate key → parse document → check usage
- [ ] Verify quota enforcement: exceed free tier → get 429
- [ ] Verify budget enforcement: large PDF → budget halts at limit
- [ ] Set up Cloud Scheduler for daily quota reset

### Phase 5: Production Hardening
- [ ] Switch Firestore deletion_policy to PRESERVE
- [ ] Set min_instances=1 for production
- [ ] Add Cloud Monitoring alerts (error rate, latency, quota exhaustion)
- [ ] Add rate limiting (requests/second per key)
- [ ] Security audit: verify tokens, check CORS, test injection vectors
- [ ] Load test with concurrent users

## Resolved Questions

1. **Dedicated database or default?** → **Dedicated `docparse` Firestore DB.** Configurable via `FIRESTORE_DATABASE` env var (default: "docparse"). Cleaner separation, same as website-builder pattern.

2. **Cloud Scheduler for quota reset vs. lazy reset?** → **Lazy reset.** Implemented in `apiKeyNeedsDailyReset()` / `apiKeyNeedsMonthlyReset()` — compares epoch timestamps, resets counters in Firestore on first request after the interval. No Cloud Scheduler infrastructure needed. Pure functions, Z3-verifiable.

3. **Firebase Auth for key management endpoints?** → **Yes, keep Firebase Auth.** Dashboard needs user identity. Key management endpoints use `Authorization: Bearer <firebase_id_token>`.

4. **Which GCP project?** → **`YOUR_GCP_PROJECT`** (same project, reuses existing Firebase). Terraform in `YOUR_GCP_PROJECT` repo.

5. **AILANG `serve-api` blockers from v0.7.0** → **All resolved.** Custom routes (`@route`), file upload (multipart), CORS (`--cors`), API key auth (`--api-key-header`), header access — all shipped. No reverse proxy needed.

6. **Concurrency** → **Confirmed working.** Initial deadlock reports were test harness issues (stderr redirect). Cloud Run `concurrency=80` is safe. Sequential: 1-6ms per request.

## Open Questions

1. **std/crypto for SHA-256** — Current key hashing uses `foldl * 31` (non-cryptographic). Requested from AILANG. Full hash string comparison prevents collisions for now.

2. **Rate limiting (requests/second/key)** — Not yet implemented in v0.8.0. Cumulative quotas (requests/day, pages/month) are enforced. Per-second rate limiting deferred to v0.9.0 or API Gateway phase.

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Firestore latency on quota check | 20-50ms added per request | Acceptable for v1; add in-memory cache in v2 |
| SHA-256 not available in AILANG | Weak key hashing | djb2 + full hash string comparison prevents collisions; std/crypto requested |
| Multiple Cloud Run instances race on quota | Over-counting possible | Firestore transactions handle this; small window acceptable |
| Firebase Auth token verification in AILANG | Need to fetch Google public keys, verify JWT | Can defer to a sidecar or Cloud Run middleware |

## Implementation Status (2026-03-19)

### Completed
- [x] `api_keys.ail` — tier system (free/pro/enterprise), 7 Z3-verifiable pure functions
- [x] `api_keys.ail` — quota checking with lazy daily/monthly reset
- [x] `api_keys.ail` — usage recording (requestsToday, pagesThisMonth, totalRequests, totalPages)
- [x] `api_keys.ail` — key rotation endpoint (`/api/v1/keys/rotate`)
- [x] `api_keys.ail` — usage stats endpoint (`/api/v1/keys/usage`)
- [x] `api_keys.ail` — configurable Firestore database name (`FIRESTORE_DATABASE` env var)
- [x] `main.ail` — imports updated for new api_keys exports
- [x] Dockerfile — updated with Firestore env vars, latest AILANG
- [x] Test suite — 32/32 tests pass (25 parse + 5 key mgmt + 2 OpenAPI)
- [x] Type-check — 31 modules, all pass
- [x] Concurrency confirmed working (test harness was the issue)

### Deployed (2026-03-19)
- [x] Terraform in YOUR_GCP_PROJECT: Cloud Run, Firestore, SA, IAM, CI/CD triggers
- [x] Cloud Run: https://api.parse.sunholo.com
- [x] Firestore DB: `docparse` (dedicated)
- [x] Service account: `YOUR_SERVICE_ACCOUNT`
- [x] CI/CD: `docparse-dev` trigger on push to main, `docparse-firestore-rules` for rules
- [x] All 13 parse formats verified working on Cloud Run
- [x] Health, formats, OpenAPI, Swagger UI — all working
- [x] Unstructured compat endpoint — working
- [x] Cold start: ~20s (31 modules), warm: 0ms health, 2-10ms parse

### Blocked
- [ ] Key management endpoints fail with `_json_decode: expected string, got *eval.TaggedValue`
  - All api_keys.ail functions fail, even simple single-arg ones
  - Other modules (api_server.ail) work fine with identical arg formats
  - Bug reported to AILANG (msg_20260319_154107_80a588f1)
  - SHA-256, effects, JSON encoding all work in isolation — issue is module-specific

### Remaining
- [ ] Fix key management endpoint bug (blocked on AILANG)
- [ ] Website dashboard (`docs/dashboard.html`) with Firebase Auth
- [ ] Production hardening (monitoring, alerts, min_instances=1, rate limiting)

## Dependencies

- **YOUR_GCP_PROJECT**: Terraform changes — in progress
- **docparse**: api_keys.ail — done, api_server.ail — done
- **AILANG runtime**: serve-api features — all shipped. Pending: std/crypto (SHA-256)
- **Firebase**: Provisioned in YOUR_GCP_PROJECT (shared with website-builder)
- **docparse Dockerfile**: Updated for v0.8.0

## Success Criteria

1. A user can sign up on docs/dashboard.html, generate an API key, and parse a document — all self-service, no manual intervention
2. Free tier limits are enforced: 429 after 20 requests/day or 100 pages/month
3. AILANG capability budget halts a free-tier request that tries to parse >5 PDF pages
4. The same API key works with both native and Unstructured-compatible endpoints
5. Upgrade from free to pro takes effect immediately (next request uses new limits)
6. Infrastructure is fully Terraform-managed — `terraform apply` deploys everything
