# Releasing

## How

```bash
# 1. Bump the version in BOTH manifests
#    ailang.toml  version = "X.Y.Z"
#    pyproject.toml version = "X.Y.Z"

# 2. Turn the CHANGELOG's `## Unreleased` into a version heading with a
#    compare link and today's date.

# 3. Push main and let it go green — including `Install smoke test`, which is
#    the gate that the package actually contains a usable CLI.
gh run list --branch=main --limit 3

# 4. Only then tag. The tag fires publish-ailang.yml, which re-runs
#    ./bin/docparse --check before uploading.
git tag vX.Y.Z HEAD && git push origin vX.Y.Z
```

Do **not** run `ailang publish` by hand — tag-triggered CI does it, and a manual
run races the workflow and turns the release red.

**Ordering matters when docs are part of the release.** The README's install
one-liner points at `https://www.sunholo.com/ailang-parse/install.sh`, which is
`scripts/install.sh` copied into `_site/` by `pages.yml` on push to main. Push
and let Pages deploy *before* tagging, or the release ships pointing at a 404.

## If a tag fails validation

The publish workflow builds AILANG from the **dev** branch, which moves. A green
CI run does not guarantee a green publish an hour later. Re-run the failed job
rather than retagging.

## What ships in the package

`ailang publish` bundles `ailang.toml`, every `*.ail`, `AGENT.md`, and
**everything under `assets/`** — nothing else. The CLI wrapper
(`assets/bin/docparse`), the PDF adapter (`assets/pdf_backends/adapter.py`) and
`assets/backends-pyproject.toml` are real files there, with symlinks at their
historical paths for the clone workflow.

If you move any of those back out of `assets/`, they silently vanish from every
published version — which is exactly what happened to `bin/docparse` and the PDF
adapter up to v0.39.4. The `install-smoke` workflow is the gate: it installs
from the tarball with no checkout and fails if `assets/bin/docparse` is missing.
Do not disable it to get a release out.
