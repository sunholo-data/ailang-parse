# Design Doc: List AILANG Parse in the Anthropic and OpenAI Directories (v0.49.0)

**Status**: Planned
**Date**: 2026-10-01
**Author**: Mark + Claude
**Follow-on**: Secure AILANG code execution as a plugin (separate doc, after this ships)

## Goal

Get AILANG Parse listed in the two vendor-run directories that now drive discovery:

1. **Anthropic's directory** (claude.ai/directory/manage). One listing reaches claude.ai web, desktop
   and mobile, Cowork, and Claude Code.
2. **OpenAI's Plugin Directory**. One listing reaches ChatGPT and Codex.

After the first, manual submission, a release should keep all three listings (these two plus the
MCP Registry) current with no further manual steps, as far as each vendor allows.

## Status quo (measured 2026-10-01)

| Channel | State | Mechanism |
|---|---|---|
| **Official MCP Registry** (`io.github.sunholo-data/parse`) | **Listed.** | `publish-sdks.yml` job `publish-mcp-registry` runs `mcp-publisher publish` with GitHub OIDC on every `sdk-v*` tag; `server.json` is at 0.13.1. |
| **Claude Code plugin** (`ailang-parse@ailang-parse-marketplace`) | Self-hosted marketplace in `sunholo-data/docparse-skill` (the repo the directory submissions will use), plugin v0.15.0. CI (`validate.yml`) runs strict validation and an install smoke test on every push and PR. | Users run `claude plugin marketplace add`. **Not in Anthropic's directory.** |
| **Codex** | Skill metadata (`skills/ailang-parse/agents/openai.yaml`) and README `codex mcp add` instructions. | Manual. **No `plugin.json` in the Agent Plugins format, and not in OpenAI's directory.** |
| **Anthropic directory** | Not submitted. | — |
| **OpenAI Plugin Directory** | Not submitted. | — |

**MCP Registry freshness (checked 2026-10-01).**
- **Versions match.** The registry's latest is 0.13.1, published 2026-09-01. That equals
  `sdk-v0.13.1`, npm `@ailang/parse` and PyPI `ailang-parse`.
- **Why it looks stale:**
  - The registry only moves on `sdk-v*` tags. The service has shipped v0.46 through v0.48
    (108 commits) since then without one, because the version check ties `server.json` to the
    SDK package versions.
  - The listing **description** still says "Deterministic DOCX/PPTX/XLSX/PDF parser: track
    changes, comments, headers, footers, merged cells". That predates document generation, the
    17 input / 9 output formats, and editing.
- **What is not stale:** the `remotes` entry is just a URL, so registry users already get the
  current server.
- **Fix (part of M7):**
  - refresh the `server.json` description, title and icons to match the plugin copy;
  - have CI fail if the `server.json` description drifts from the plugin `description`;
  - decide whether a service release with no SDK change should also cut an `sdk-v*` patch, so
    the listing date and changelog keep moving.

The MCP Registry is a community index that MCP clients browse. It is **not** what
claude.ai or ChatGPT show users, which is why Parse is invisible there even though the
registry listing has been live since April.

## What the directories require (vendor docs, 2026-10-01)

**Anthropic** (https://claude.com/docs/directory/publish)
- Two submission types, and they recommend both:
  - an **MCP connector** (a remote server URL);
  - a **plugin bundle** (a GitHub repo containing skills and an MCP config).
- Every tool must have a **title** and a **`readOnlyHint` or `destructiveHint`** annotation.
- Authenticated services need a **supported OAuth flow**.
- A **public privacy policy** is mandatory.
- A populated **reviewer account** must be supplied.
- Plugins go through automated validation, a security scan and a human review. Connectors are
  policy-scanned and listed as "Community".
- **Updates:** the plugin bundle tracks a branch, so a merge ships it with no resubmission. A
  connector is a URL, so server changes are live immediately.

**OpenAI** (https://developers.openai.com/apps-sdk/deploy/submission, https://developers.openai.com/plugins/build/plugins)
- A ZIP upload on the OpenAI Platform containing:
  - a root `plugin.json` (Agent Plugins schema), with OpenAI-specific fields under
    `extensions.com.openai`;
  - `skills/`;
  - `mcp.json`.
- Four stages: automated validation, metadata review, MCP setup (domain verification and a tool
  scan), then formal review.
- Formal review needs:
  - **5 positive and 3 negative test cases**;
  - a **demo video**;
  - a **test account without MFA**.
- OAuth is supported.
- **Updates:** MCP server changes go live automatically once they pass checks. Metadata and skill
  changes are a resubmission; whether that can be done through an API is unverified.
- Custom GPTs and Actions retire on 2026-12-11. Build nothing there.

## Gaps (measured against prod, 2026-10-01)

### G1 — No tool titles or annotations (hard blocker for Anthropic)

`tools/list` on `https://docparse.ailang.sunholo.com/mcp/` returns `title: null` and
`annotations: null` for all 10 tools. The cause is in AILANG, not Parse: `ailang serve-api`
builds every tool as `mcp.Tool{Name, Description, InputSchema}`
(`ailang/internal/apiserver/mcp.go`, Phase 3 of `registerTools`). No annotation can express a
title or a hint today; only `@mcp_name` and `@nomcp` exist (`ailang/internal/parser/parser_decl.go`).

We can't derive the hints from effect rows. Every Parse tool declares a broad row (for example,
`mcpParse` is `! {Clock, AI, Env, FS, IO, Net}`), even though most of them are read-only from
the user's point of view. The author has to state them.

### G2 — No MCP OAuth (likely blocker for both)

- `/.well-known/oauth-protected-resource` and `/.well-known/oauth-authorization-server` both
  return 404.
- Today auth works in two ways:
  - the **tools** `mcpAuth` and `mcpAuthPoll` run an RFC 8628 device-code flow that hands the
    model a `dp_` API key, which it then passes back as `apiKey`;
  - an `Authorization: Bearer dp_…` header.
- Directory clients expect the MCP authorization spec instead: a 401 with
  `WWW-Authenticate`, protected-resource metadata, then an OAuth 2.1 + PKCE flow run by the
  **client**, not by the model.

### G3 — No OpenAI package

`docparse-skill` has `.claude-plugin/` manifests only. It needs a root `plugin.json` (Agent
Plugins) and `mcp.json` that point at the same skill tree and the same remote URL.

### G4 — Review collateral

These don't exist yet:
- a reviewer/test account (populated, no MFA);
- 5+3 test cases;
- a demo video.

The privacy policy and terms already exist (`docs/privacy.html`, `docs/terms.html`). M4 checks
they are reachable at their public URLs.

## Decisions

### D1 — Tool annotations are an AILANG fix, not a Parse workaround

Add two author annotations to the language, next to `@mcp_name`:

```
@mcp_title("Parse document")
@mcp_hints(readOnly, openWorld)        -- any of: readOnly, destructive, idempotent, openWorld
export func mcpParse(...) -> string ! {...}
```

- `serve-api` maps them onto `mcp.Tool.Title` and `mcp.Tool.Annotations`.
- With no `@mcp_hints`, **pure** exports default to `readOnlyHint: true`.
- An effectful export with no hints gets **no annotation, plus a startup warning**. It does not
  get a guessed one: a wrong `readOnlyHint` is worse than none (CLAUDE.md §2, no silent fallbacks).

This goes in the **AILANG-fix lane** (PROGRAM.md routing): every `serve-api` server benefits,
including the hosted knowledge MCP at `mcp.ailang.sunholo.com`, which will need the same thing
when the code-execution plugin is listed. Parse picks it up by bumping its AILANG pin.

Proposed mapping for Parse (to confirm against each tool's behaviour in hosted mode):

| Tool | Title | readOnly | destructive | openWorld | Note |
|---|---|---|---|---|---|
| `mcpParse` | Parse document | ✓ | | ✓ | |
| `mcpConvert` | Convert document | | ✗ | ✓ | Writes `outputPath` in local mode; hosted mode returns the result inline. |
| `editDocument` | Edit document | | ✗ | ✓ | Verify whether it ever writes in place. If it can overwrite, mark it `destructive`. |
| `getUploadUrl` | Get upload URL | | ✗ | ✓ | |
| `mcpFormats` | List supported formats | ✓ | | | |
| `mcpEstimate` | Estimate cost | ✓ | | | |
| `mcpAccount` | Account and usage | ✓ | | | |
| `mcpAuth` / `mcpAuthPoll` | Sign in / check sign-in | | ✗ | | Kept for clients without OAuth (D2). |
| `submit_feedback` | Send feedback | | ✗ | ✓ | |

### D2 — Device-code auth stays the core; MCP OAuth is a thin front door onto it

**Today's model (keep it).** Auth is RFC 8628 device authorization. An agent calls `mcpAuth`,
shows the user a URL and code, the user signs in in their own browser, and `mcpAuthPoll`
returns a key. That works in **every** MCP client, including headless agents and CLIs that
have no browser of their own. Since #85 the key can also arrive as an
`Authorization: Bearer` or `X-API-Key` header, so a client that can inject headers keeps it
out of model context.

**Why the directories still need more.** Directory clients (claude.ai, ChatGPT) do not let the
model run a login. They run the MCP authorization flow themselves: a 401 with a
`WWW-Authenticate` header, then protected-resource metadata, then OAuth 2.1 authorization code
+ PKCE in the user's browser. They then attach the token as a `Bearer` header on every call.
With only tool-mediated auth, Codex already reports the server's auth as **"Unsupported"**
(`codex mcp list`, 2026-10-01). In the directory clients, the key would also travel through
the model as an `apiKey` argument, which reviewers will flag.

**Design: reuse the device-auth backend; add no second identity system.**
- **`/.well-known/oauth-protected-resource` on the MCP host** names the authorization server.
- **Authorization server endpoints:** `/authorize`, `/token`, `/register` (dynamic client
  registration; both directory clients use it), and `/.well-known/oauth-authorization-server`.
  - `/authorize` renders the **same sign-in page** the device flow's verification URL uses.
  - `/token` mints a token that resolves to the same account and quota as a `dp_` key.
    Simplest version: the token *is* a scoped `dp_` key, so the existing `Bearer` path (#85)
    validates it unchanged.
- **The 401 challenge only goes to calls that need auth.** `tools/list`, `mcpFormats`,
  `mcpEstimate` and `mcpAuth*` stay open, so discovery and the device flow still work
  unauthenticated.
- **`mcpAuth` / `mcpAuthPoll` stay** for agents and clients without OAuth. The server
  instructions tell OAuth-capable clients that they are unnecessary.

**Measured 2026-10-01: there is no anonymous tier.** `mcpParse` on a sample with no key
returns `AUTH_REQUIRED`. So a directory listing cannot ship without auth, and **M3 is on the
critical path for both directories.**

The OAuth layer belongs to the Parse service (`/api/v1/auth/*`), not to AILANG. Whether
`serve-api` should grow generic OAuth resource-server support is a question for the
code-execution doc.

### D3 — One repo, two manifest sets, one skill tree

`docparse-skill` gets these files:

```
.claude-plugin/marketplace.json              (exists)
plugins/ailang-parse/.claude-plugin/plugin.json   (exists, Claude)
plugins/ailang-parse/.mcp.json               (exists, remote URL)
plugins/ailang-parse/plugin.json             (NEW, Agent Plugins, extensions.com.openai)
plugins/ailang-parse/mcp.json                (NEW, same remote URL)
plugins/ailang-parse/skills/ailang-parse/    (shared, unchanged)
```

There is one source for the skill text and one MCP URL. The Anthropic directory submission
points at this repo and branch, and the OpenAI ZIP is built from the same directory.

### D4 — CI keeps the listings current; the first submission is manual

Neither vendor offers a submission API we can verify, so the **first** submission to each is a
one-off portal step.

**Extend `docparse-skill/.github/workflows/validate.yml`.** It already runs
`claude plugin validate --strict` plus an install smoke test that asserts one skill and one MCP
server register; it was added after the repo broke twice for real users
(sunholo-data/ailang-parse#1). On every PR, add these checks to it:
- schema-validate the root `plugin.json` against Agent Plugins;
- an equivalent install smoke test for Codex, if the Codex CLI can install from a local path;
- check that both MCP configs name the same URL as `ailang-parse/server.json` `remotes[0]`;
- check that the plugin versions match each other.

**Release job (`sdk-v*` tag in `ailang-parse`), extends `publish-sdks.yml`:**
1. MCP Registry (unchanged).
2. **Anthropic:** fast-forward the tracked branch of `docparse-skill`. The directory picks the
   merge up with no resubmission.
3. **OpenAI:** build the plugin ZIP and attach it to the GitHub release. Server-side tool
   changes reach OpenAI automatically. A metadata or skill change opens a "resubmit to OpenAI"
   checklist issue until a submission API is verified.

**Server-side gate:** a prod smoke test asserts every tool in `tools/list` has a `title` and at
least one hint. A new tool without annotations would get the listing delisted on rescan, so it
should fail CI first.

## Milestones

| # | Milestone | Repo | Done when |
|---|---|---|---|
| M1 ✅ | `@mcp_title` / `@mcp_hints` in `serve-api` | ailang | **Done 2026-10-01 (ailang `9305f1c19`).** Emitted by both MCP implementations; the built-in `submit_feedback` is annotated. Also fixed: zero-arg tools advertised a required `"_"`, so prod `mcpFormats` rejected `{}` (`290e53886`). Purity bugs found on the way are filed as ailang#1443. |
| M2 | Annotate Parse tools and bump the AILANG pin (**needs an AILANG release containing M1**; the current pin rejects `@mcp_title` as an unknown attribute) | ailang-parse | Prod `tools/list` shows a title and a hint on all 10 tools; the smoke gate is in CI. |
| M3 | MCP OAuth front door onto the device-auth backend (D2) | ailang-parse | A connector added by URL in claude.ai and ChatGPT developer mode completes OAuth and calls `mcpParse` on a real document; `Bearer dp_` and the device-flow tools still work. |
| M4 ✅ | Agent Plugins manifest and CI validation | docparse-skill | **Done 2026-10-01 (docparse-skill `a573d7c`).** Strict Claude validation, the Agent Plugins schema and cross-manifest checks, and a Codex install smoke test all run in CI and are green. The OpenAI ZIP build moves to M7. |
| M5 | Review collateral | ailang-parse | Reviewer account seeded (no MFA); 5+3 test cases written; demo video recorded; privacy and terms URLs return 200. |
| M6 | Submit to both directories (manual) | — | Anthropic submission (connector and plugin bundle) and OpenAI submission accepted into review. |
| M7 | Release-time sync | ailang-parse, docparse-skill | One `sdk-v*` tag updates the MCP Registry, fast-forwards the Anthropic-tracked branch and attaches the OpenAI ZIP. |

M1 is the critical path for Anthropic, and M3 is the critical path for both.

## Out of scope

- **Secure AILANG code execution as a plugin (hosted `check`/`run` MCP).** It gets its own doc
  after this ships. M1 is shared groundwork for it.
- `.mcpb` desktop extensions: the Anthropic directory no longer accepts them.
- GPT Actions and custom GPTs: retiring.
- The DNS-verified `com.sunholo/parse` registry namespace, still deferred from v0.14.0.

## Open questions

1. ~~Do Parse tools work anonymously?~~ **No** (measured 2026-10-01: `AUTH_REQUIRED` on a
   sample). OAuth (M3) is required before either listing.
2. Which tracked branch should Anthropic follow: `main` of `docparse-skill`, or a `release`
   branch the tag job fast-forwards? A release branch keeps unreleased skill edits out of the
   directory.
3. Does `editDocument` ever overwrite its input in place? That decides its `destructiveHint`.
4. Who owns the reviewer account and its seed data, given the account must not have MFA?

## Verification notes

**Measured in this session:**
- the MCP Registry publish job;
- `server.json` contents;
- that prod `tools/list` has no titles or annotations;
- that both `.well-known` OAuth endpoints return 404;
- the `serve-api` tool construction;
- that the device-flow auth tools exist;
- that the privacy and terms pages exist.

**Taken from vendor docs, read through a research agent and not re-fetched here:**
- the directory requirements;
- the Agent Plugins format.

**Dated from secondary sources only:**
- OpenAI renaming apps to plugins (2026-07-09);
- the Anthropic portal opening (around 2026-09-25).

Re-check all of these against the live portals at M6.
