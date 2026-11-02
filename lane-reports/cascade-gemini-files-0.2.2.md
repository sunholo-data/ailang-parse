# Cascade lane report — sunholo/gemini_files 0.2.1 → 0.2.2 (class C) into sunholo/ailang_parse@0.55.2

**Task**: task-dee1a1a0 · **Date**: 2026-11-02 · **Outcome**: bump artifacts landed, code repair BLOCKED by environment

## What landed

- `ailang.toml`: `"sunholo/gemini_files" = "0.2.1"` → `"0.2.2"` (all other deps untouched).
- `ailang.lock`: `sunholo/gemini_files` entry updated to `0.2.2` with the interface/content hashes
  from the cascade message (`sha256:b5c0f0ae…` / `sha256:8371450c…`), effects row unchanged
  (`[Clock, Env, FS, Net]` — matches "Effects widened: false"). All other entries byte-identical
  to the previous lock. Hand-edited because `ailang lock` cannot run on this lane (see below);
  a wrapper-side `ailang lock` regeneration will normalise formatting if needed.

## Why the consumer repair could not be completed

The sole consumer of the changed surface in this package is:

- `docparse/services/direct_ai_parser.ail` — the only file importing
  `pkg/sunholo/gemini_files/upload`, using exactly:
  - `uploadFile(base64Data: string, mimeType: string, filepath: string) -> Result[UploadedFile, string] ! {Clock, Net, FS, Env}` (via `prepareUpload`, line ~169)
  - `UploadedFile.uri` (via `uploadedUri`, line ~175)
  - `deleteFile(uploaded: UploadedFile) -> Result[(), string]` (via `cleanupUpload`, line ~182)

A class-C repair needs the 0.2.2 interface (which export/signature changed). That interface is
**not observable from this agent sandbox**:

1. The registry cache (`~/.ailang/cache/registry/…`) is completely empty in this container.
   Verified by pinning each dependency in turn: resolution fails with
   `failed to hash registry dependency … lstat …: no such file or directory` for
   `sunholo/a2ui@0.2.0`, `sunholo/gemini_files@0.2.1` **and** `sunholo/gemini_files@0.2.2`.
   With an empty lock, arbitrary probe programs run fine — so the sandbox itself works; only the
   package cache is missing.
2. `ailang pkg-docs sunholo/gemini_files` → `not provisioned: confined by AILANG_AGENT_POLICY:
   fetching from the registry is operator authority — provision AILANG_PACKAGE_ROOT or run
   'ailang install' outside the sandbox`. There is no `ailang install` op on this lane and no
   shell, so the cache cannot be populated from inside.
3. `ailang check` / `ailang test` / `ailang run` therefore abort at package-resolution setup for
   every file in the package (93/94 files fail with the resolution error, before any type
   checking), so neither the old breakage nor a candidate repair can be type-checked here.

Consequently `ailang check --package .` and `ailang test --package .` could not be run to green
on this lane. The wrapper's own check failure (in its environment, where the cache presumably
exists) remains the authoritative error signal; that output was not included in the cascade
message.

## Why no speculative code edit was made

The consumer's call sites are correct against 0.2.1 and the file compiles there. Guessing the
0.2.2 shape (renamed export? changed `uploadFile` arity? different `UploadedFile` fields?) without
being able to type-check the result risks shipping a change that is wrong in a *new* way and
would have to be re-reverted. Leaving the 0.2.1-correct source in place plus the bumped
manifest/lock keeps the failure mode at worst identical to today's and is trivially reviewable.

## What a human / re-run needs

1. Re-run this lane in a container with the registry cache provisioned
   (`ailang install sunholo/gemini_files@0.2.2` outside the sandbox, or set `AILANG_PACKAGE_ROOT`),
   or paste the wrapper's `ailang check` failure output into the cascade message.
2. Then adapt `docparse/services/direct_ai_parser.ail` (`prepareUpload` / `uploadedUri` /
   `cleanupUpload`) to the new `sunholo/gemini_files/upload` surface and re-run
   `ailang check --package .` + `ailang test --package .`.

## Artifacts changed in the working tree

- `ailang.toml` (dep pin 0.2.1 → 0.2.2)
- `ailang.lock` (gemini_files entry → 0.2.2, new hashes)
- this report

No commits made (lane policy: read-only git; the wrapper commits).
