# v0.14.0 — Publish AILANG Parse to the Official MCP Registry

**Status**: Planned
**Target version**: 0.14.0 (SDK release 0.4.1 carries the package metadata)
**Owner**: Mark
**Drafted**: 2026-04-08

## Goal

List AILANG Parse in the [official MCP Registry](https://github.com/modelcontextprotocol/registry) so that Claude Desktop, Cursor, VS Code, and any future MCP client that browses the registry can discover and one-click install our parser. The registry is becoming the canonical discovery layer for MCP servers; not being on it is a free distribution channel left on the table.

This doc covers **what we register, under which namespace, and how the release pipeline keeps the registry entry in sync** with our SDK releases. It does **not** cover server feature work — the bridge code already shipped in `sdk-v0.3.1` and the server-side tool naming was fixed in `v0.10.12`.

## Why now

Three things converged this week:

1. **Server tool names are now registry-compliant.** v0.10.12 emits bare names (`mcpParse`, not `docparse.services.mcp_tools.mcpParse`) — see GitHub issue #153. Before that, any registry submission would have been rejected by clients enforcing the `^[a-zA-Z0-9_-]{1,64}$` pattern.
2. **Three SDK bridges are published and feature-equivalent.** `@ailang/parse@0.4.0`, `ailang-parse==0.4.0`, and the Go binary all forward stdio JSON-RPC to the hosted endpoint, auto-load saved credentials, and have been smoke-tested against prod. There's nothing left to fix in the bridges before listing.
3. **The hosted endpoint is stable on a public URL** (`https://docparse.ailang.sunholo.com/mcp/`) with healthy uptime, so we can offer a `remotes` entry for clients that prefer Streamable HTTP over a stdio bridge.

## Background — what the registry expects

The registry is a community-run index keyed by a **namespaced server name**, e.g. `io.github.sunholo-data/parse`. Each entry has a `server.json` describing how clients should run it. Two transport classes are supported:

- **`packages`** — published artifacts (npm, PyPI, NuGet, Docker, etc.) that the client downloads and runs as a local stdio subprocess. This is what `@ailang/parse mcp` already is.
- **`remotes`** — direct HTTP endpoints (`streamable-http` or `sse`) that the client connects to without spawning anything. This is what our hosted MCP endpoint already is.

A single `server.json` can list **both**, and clients pick the most efficient one they support. Today most desktop clients still need stdio, but Claude Code and Cursor handle remotes natively, so listing both is the right call.

The registry supports exactly five package types, no more: **`npm`, `pypi`, `nuget`, `oci` (Docker), `mcpb`**. There is **no `go install` source, no CRAN, no R-universe**. This is a hard constraint, not a documentation gap — the registry's verification logic is type-specific and only knows how to verify these five.

The registry verifies ownership differently depending on type:

- **npm**: reads an `mcpName` field from `package.json`, must match the server name.
- **pypi**: greps the package's README (which becomes the PyPI long description) for an `mcp-name: <server-name>` string. Can be inside an HTML comment `<!-- mcp-name: ... -->`. **No `pyproject.toml` field needed** — this is simpler than the npm path.
- **oci**: reads the `io.modelcontextprotocol.server.name` LABEL from the image manifest, must match the server name.
- **mcpb**: requires the `.mcpb` URL to contain the string "mcp" + a `fileSha256` hash.

If verification fails for any listed package, the entire submission is rejected. This is the only piece of work that requires touching the SDKs themselves — and it's all metadata, no code.

## Decisions

### Namespace: `io.github.sunholo-data/parse`

- **Pro**: GitHub device flow auth, no DNS verification, can be published today.
- **Pro**: Matches the GitHub org we already use (`sunholo-data`), so the namespace is self-evidently ours to anyone who finds the listing.
- **Con**: Less prestigious than a domain-verified namespace.

A second listing under `com.sunholo/parse` (DNS-verified on `sunholo.com`) is **deferred to v0.15.0** as a "polish" item. Listing twice is allowed and gets us a verified-domain badge once we want it, but it costs nothing to wait — and we need a working `io.github.*` listing in production anyway to learn the operational pieces.

### Server name: `parse` (not `ailang-parse` or `docparse`)

The full identifier becomes `io.github.sunholo-data/parse`. Clients display the bare leaf, not the namespace, so users see "parse" alongside "github" / "filesystem" / "memory" — short, recognizable, and disambiguated by the namespace prefix when there's a conflict. The npm package keeps its scoped name `@ailang/parse` for consistency with existing installs; mismatching the package name and the server leaf is allowed and common.

### Single server.json with both packages and remotes

```json
{
  "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
  "name": "io.github.sunholo-data/parse",
  "title": "AILANG Parse",
  "description": "Parse 13 document formats (DOCX, PPTX, XLSX, ODT, ODP, ODS, EPUB, HTML, PDF, etc.) into structured blocks. Drop-in Unstructured.io replacement with deterministic Office parsing.",
  "websiteUrl": "https://www.sunholo.com/ailang-parse/",
  "repository": {
    "url": "https://github.com/sunholo-data/ailang-parse",
    "source": "github"
  },
  "version": "0.4.1",
  "packages": [
    {
      "registryType": "npm",
      "identifier": "@ailang/parse",
      "version": "0.4.1",
      "transport": { "type": "stdio" }
    },
    {
      "registryType": "pypi",
      "identifier": "ailang-parse",
      "version": "0.4.1",
      "transport": { "type": "stdio" }
    }
  ],
  "remotes": [
    {
      "type": "streamable-http",
      "url": "https://docparse.ailang.sunholo.com/mcp/"
    }
  ]
}
```

**Only the npm and PyPI packages go in the registry today.** The Go SDK, and any future R bindings, are documented in prose in our own README and `docs/mcp.html` but are *not* listed in `server.json`. The reason is structural, not a doc gap: the registry's five supported package types (npm/pypi/nuget/oci/mcpb) don't include `go install`, CRAN, or R-universe, and the registry's verification logic is type-specific. We could in principle ship Go as a Docker image (`oci`) or as a `.mcpb` release artifact later, but that's a separate piece of work and is deferred — for v0.14.0 we list the two SDKs the registry can natively verify and call out the others in the listing description and our docs.

### What goes in the description

The description is the listing's elevator pitch and the most important field for discoverability. Constraints:

- Must lead with what it does (`Parse N document formats`) so it's intelligible without context
- Must include the formats list because users search by format name (`docx`, `pptx`)
- Must mention Unstructured.io because that's the keyword most users searching for an alternative type
- Must not exceed ~250 chars — the registry truncates long descriptions in browse views

The draft above is 215 characters and hits all of those.

## Required SDK changes

Three small changes carried in **SDK release 0.4.1**:

1. **`sdks/js/package.json`** — add `"mcpName": "io.github.sunholo-data/parse"` at the top level. This is the field the registry reads to confirm the npm package belongs to the namespace.
2. **`sdks/python/README.md`** — add an HTML comment `<!-- mcp-name: io.github.sunholo-data/parse -->` somewhere in the file. The README becomes the PyPI long description, and the registry's PyPI verifier greps the long description for that exact `mcp-name:` marker. **No `pyproject.toml` change needed.** Place the comment near the top of the README so it survives any future README rewrites that might trim trailing sections.
3. **`server.json`** at repo root — the metadata file the publisher CLI uploads. New file.

No code changes to the bridges themselves. The bridges already work — this is purely metadata-and-publishing.

## Publishing flow

The `mcp-publisher` CLI is a one-binary Go tool from the registry repo. Workflow:

```bash
# One-time per machine
brew install mcp-publisher                       # or download release binary
mcp-publisher login github                       # device flow against an account in sunholo-data org

# Per release
cd /Users/mark/dev/sunholo/ailang-parse
mcp-publisher publish                            # reads ./server.json, validates, submits
```

The `mcp-publisher publish` step:
1. Reads `server.json`
2. Fetches each listed package from npm/PyPI
3. Reads the `mcpName` field from each package's metadata
4. Confirms it matches `server.json` `name`
5. POSTs the entry to the registry API with the GitHub OIDC token

If any package fails validation (wrong `mcpName`, version mismatch, package not yet on the registry), the publish fails before anything is registered.

## CI integration

Goal: pushing the `sdk-v0.4.1` git tag should publish to npm, PyPI, **and** the MCP registry in one shot, with no manual `mcp-publisher publish` step required.

Concrete plan for `.github/workflows/publish-sdks.yml`:

1. After the existing `publish-npm` and `publish-python` jobs succeed, add a new `publish-mcp-registry` job.
2. Job needs:
   - `mcp-publisher` binary (download from GitHub releases, cache by version)
   - GitHub OIDC token (already available via `id-token: write` permission)
   - `server.json` at repo root
3. Job runs `mcp-publisher publish` with the OIDC token as auth.
4. Job's `version` field in `server.json` must be templated from the git tag — either the workflow rewrites `server.json` before publishing (sed/yq), or `server.json` references `${VERSION}` and the publisher does the substitution. Need to check which the CLI supports; if neither, sed in the workflow is fine.

Open question: does the registry support OIDC at all, or is `mcp-publisher login github` strictly device-flow / personal-token? If it's device-flow only, the CI step has to use a long-lived PAT stored in repo secrets, which is uglier but workable. **Resolve before implementing CI step.**

## Operational concerns

### What happens when we ship a new SDK version?

Every `sdk-v*` tag should re-publish to the registry with the new version number. The registry stores entries as version-tagged immutable records — old versions remain queryable, but clients see the latest. This means:

- No need for manual de-listing when superseded
- Bug fixes in 0.4.2 silently win
- Major version jumps that break tool surface (rare for us) should bump the description too so users browsing see the change

### Versions are immutable — always advance, never republish

The registry treats `(name, version)` as a primary key. **You cannot re-publish the same version with different content.** If we ship `0.4.1` and discover a metadata bug five minutes later, the fix has to go out as `0.4.2` — there's no "force overwrite" path. This is a feature, not a limitation: it means clients and supply-chain tools can pin a registry entry by version and trust it never silently mutates.

Practical consequences for our release process:

- The `version` in `server.json`, `sdks/js/package.json`, and `sdks/python/pyproject.toml` must always move forward together. If any one of them is behind, the publish step fails.
- Hot-fixes are version bumps. Even a one-character README typo that affects the PyPI long description (and therefore the `mcp-name:` marker) requires bumping the patch version.
- The CI workflow should *refuse* to publish if the tag's version already exists in the registry, rather than appearing to succeed silently. Worth checking what `mcp-publisher publish` does on a duplicate-version submission and adding an explicit pre-check if it doesn't already fail loudly.

### What happens when the hosted endpoint changes URL?

The `remotes` entry hard-codes `https://docparse.ailang.sunholo.com/mcp/`. If we ever migrate the prod endpoint to a different domain, we publish a new registry entry pointing at the new URL. Old clients with the old URL cached keep working until they refresh — the bridge falls back gracefully because the URL is the only thing in `remotes`. **Don't change the hosted MCP URL casually** — it's now an external contract.

### What happens if mcp-publisher rejects our submission?

Most likely failure modes and responses:

- **`mcpName` mismatch**: re-publish the SDK with the right field. ~5min to fix.
- **Namespace conflict**: someone squatted `io.github.sunholo-data/parse`. Vanishingly unlikely (the namespace is gated on GitHub org membership) but if it happens, we file a registry issue and switch to `io.github.sunholo-data/ailang-parse` as a fallback name.
- **Description too long / contains emoji**: tighten the description, no SDK rebuild needed.
- **Schema version drift**: registry rolls out a new schema, our `$schema` URL points at the old one, validator complains. Bump the URL, retry. We should pin the schema version we test against in CI.

### Discoverability — what we're optimizing for

The registry's search ranks by a few signals we can influence and several we can't:

- **Description match** (we control — keyword-rich)
- **Listed formats** (we control — explicit in description)
- **Number of installs / downloads** (we control indirectly via marketing)
- **Stars on the linked repo** (we control indirectly)
- **Has both `packages` and `remotes`** (we control — listing both is a quality signal)

Things we can't influence: registry-internal popularity scores, official "verified" badges (would need DNS-namespace).

## What this does NOT do

- Does not change the bridges (already done in `sdk-v0.3.1`).
- Does not add new tools (server already exposes 26 compliant ones).
- Does not require infrastructure changes — the hosted endpoint is unchanged.
- Does not affect users who installed via `npx -y @ailang/parse mcp` directly. Their config keeps working. Registry listing is purely additive discoverability.
- Does not include a `com.sunholo/parse` DNS-verified listing — that's a v0.15.0 polish item.
- Does not include a Go binary entry — registry doesn't support Go install paths yet.

## Acceptance criteria

1. `io.github.sunholo-data/parse` appears in the registry's public browse view.
2. The npm and PyPI listings under that name resolve to versions matching `sdks/js/package.json` and `sdks/python/pyproject.toml`.
3. The `remotes` entry resolves: a registry-aware client following the entry connects to `docparse.ailang.sunholo.com/mcp/` and gets the 26-tool list back without manual config.
4. Pushing a `sdk-v0.4.2` (or later) tag automatically updates the registry entry to the new version, no manual `mcp-publisher publish` step required.
5. We have docs at `docs/mcp.html` explaining one-click install via registry-aware clients (alongside the existing manual config snippets).

## Open questions to resolve at implementation time

1. **Does `mcp-publisher` accept GitHub Actions OIDC, or only personal device-flow auth?** If OIDC works, CI is clean. If not, we store a PAT in repo secrets.
2. **Does `server.json` `version` get templated by the publisher, or do we rewrite the file in CI?** Trivial either way (sed in the workflow works), just need to know which path is canonical.
3. **What does `mcp-publisher publish` do on a duplicate-version submission?** We expect it to fail loudly (see "Versions are immutable" above). If it silently succeeds or partially succeeds, we add an explicit pre-check in CI that queries the registry API for the version before submitting.
4. **Should we ship a Docker (`oci`) image as a follow-up to get Go into the registry?** The registry supports `oci` natively and a Docker image wrapping the Go binary would qualify. Decide as a v0.14.1 / v0.15.0 follow-up — out of scope for this doc, which sticks to npm + PyPI.

## Sequencing (not committing to dates)

1. Write `server.json` and add `mcpName` to JS / Python package metadata. Resolve the `pyproject.toml` location question by reading the registry source. ← **before SDK 0.4.1 release**
2. Bump SDKs to 0.4.1 with the new metadata fields. Tag `sdk-v0.4.1`. Verify the npm and PyPI artifacts have `mcpName` populated correctly.
3. Manually run `mcp-publisher login github` + `mcp-publisher publish` once, locally, against `sdk-v0.4.1`. Verify the entry appears.
4. Add `publish-mcp-registry` job to `.github/workflows/publish-sdks.yml`. Test on a `sdk-v0.4.2-rc1` tag against a staging registry if available, or just against prod with a small version bump.
5. Update [docs/mcp.html](../../../docs/mcp.html) with a "One-click install via MCP registry" section above the existing manual config snippets.
6. Tweet / blog / announce. (Out of scope for this doc but worth noting the registry listing is a marketing event.)
