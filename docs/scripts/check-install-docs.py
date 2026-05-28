#!/usr/bin/env python3
"""
Regression guard for the Claude Code plugin install instructions.

A user (issue #1) hit a dead install command twice in a row: first the docs
pointed at a repo that didn't exist (`sunholo-data/ailang-parse-skill`), then
we "fixed" it to `claude install github:sunholo-data/docparse-skill` — which
*also* fails, because `claude install` is Claude Code's CLI channel updater
(it only accepts `latest`/`stable`), not a plugin installer. Nothing in CI
exercised the documented command, so both breakages shipped and only surfaced
when the user reported them.

The correct flow is two slash commands run *inside* Claude Code:

    /plugin marketplace add sunholo-data/docparse-skill
    /plugin install ailang-parse@ailang-parse-marketplace

This script makes that flow a tested invariant. It enforces:

  1. NO doc may contain a known-broken install incantation:
       - `claude install github:` (wrong command — channel updater)
       - `ailang-parse-skill`     (dead repo from the original report)
       - `skills/docparse/`       (stale skill dir; real path is
                                    skills/ailang-parse/)

  2. The canonical commands MUST appear somewhere in the docs:
       - `/plugin marketplace add sunholo-data/docparse-skill`
       - `/plugin install ailang-parse@ailang-parse-marketplace`

  3. (network, best-effort) The canonical command MUST match what the skill
     repo actually publishes. We fetch `.claude-plugin/marketplace.json` from
     sunholo-data/docparse-skill and rebuild the `/plugin install
     <plugin>@<marketplace>` string from its live `name` + `plugins[].name`
     fields. If the skill repo renames the plugin or marketplace, this fails
     in CI and tells us to update both the repo and these docs together. On a
     network error it prints a warning and skips (so offline dev isn't noisy);
     set DOCPARSE_SKIP_LIVE_INSTALL_CHECK=1 to skip it explicitly.

Run from repo root:

    python3 docs/scripts/check-install-docs.py

Exit code: 0 = pass, 1 = at least one invariant violated.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# --- The contract -----------------------------------------------------------
# The GitHub repo that hosts the plugin marketplace.
SKILL_REPO = "sunholo-data/docparse-skill"
# Derived from that repo's .claude-plugin/{marketplace,plugin}.json. The live
# check below confirms these still match what the repo publishes.
PLUGIN_NAME = "ailang-parse"
MARKETPLACE_NAME = "ailang-parse-marketplace"

EXPECTED_MARKETPLACE_ADD = f"/plugin marketplace add {SKILL_REPO}"
EXPECTED_PLUGIN_INSTALL = f"/plugin install {PLUGIN_NAME}@{MARKETPLACE_NAME}"

# Strings that must never appear in a doc — each is a real way users got stuck.
FORBIDDEN = {
    "claude install github:": (
        "`claude install` is Claude Code's CLI channel updater (latest/stable), "
        "not a plugin installer — it errors with 'Invalid channel'. Use "
        f"`{EXPECTED_MARKETPLACE_ADD}` then `{EXPECTED_PLUGIN_INSTALL}`."
    ),
    "ailang-parse-skill": (
        "the `sunholo-data/ailang-parse-skill` repo does not exist (the skill "
        f"lives at `{SKILL_REPO}`)."
    ),
    "skills/docparse/": (
        f"stale skill directory — the plugin's scripts live under "
        f"`skills/{PLUGIN_NAME}/` in {SKILL_REPO}."
    ),
}

# Files to scan: human-facing docs and design notes (not vendored JS/CSS).
SCAN_GLOBS = [
    ("docs", "*.html"),
    ("design_docs", "*.md"),
    ("sdks", "*/README.md"),
]
SCAN_EXTRA_FILES = [ROOT / "README.md"]

RAW_BASE = f"https://raw.githubusercontent.com/{SKILL_REPO}/main/.claude-plugin"


def fail(msg: str) -> None:
    print(f"  ✗ {msg}", file=sys.stderr)


def ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def warn(msg: str) -> None:
    print(f"  ⚠ {msg}")


def scan_files() -> list[Path]:
    seen: list[Path] = []
    for sub, pat in SCAN_GLOBS:
        base = ROOT / sub
        if base.exists():
            seen.extend(sorted(base.rglob(pat)))
    seen.extend(f for f in SCAN_EXTRA_FILES if f.exists())
    return seen


def check_forbidden(files: list[Path]) -> int:
    failures = 0
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        for needle, why in FORBIDDEN.items():
            if needle in text:
                # Report each offending line for a quick fix.
                for i, line in enumerate(text.splitlines(), 1):
                    if needle in line:
                        fail(
                            f"{f.relative_to(ROOT)}:{i} contains '{needle}' — {why}"
                        )
                        failures += 1
    if not failures:
        ok(f"No broken install incantations in {len(files)} scanned docs")
    return failures


def check_required_present(files: list[Path]) -> int:
    blob = "\n".join(
        f.read_text(encoding="utf-8", errors="replace") for f in files
    )
    failures = 0
    for needle in (EXPECTED_MARKETPLACE_ADD, EXPECTED_PLUGIN_INSTALL):
        if needle in blob:
            ok(f"Docs document the correct command: `{needle}`")
        else:
            fail(
                f"No doc contains the canonical command `{needle}` — the "
                f"install instructions are missing or wrong."
            )
            failures += 1
    return failures


def _fetch_json(name: str) -> dict:
    url = f"{RAW_BASE}/{name}"
    req = urllib.request.Request(url, headers={"User-Agent": "docparse-ci"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check_live_source_of_truth() -> int:
    """Confirm the documented command matches what the skill repo publishes."""
    if os.environ.get("DOCPARSE_SKIP_LIVE_INSTALL_CHECK"):
        warn("Live skill-repo check skipped (DOCPARSE_SKIP_LIVE_INSTALL_CHECK set)")
        return 0
    try:
        # marketplace.json is the source of truth for the install command:
        # its `name` is the @marketplace and its plugins[].name is the plugin.
        # (Plugin-manifest *schema* is validated by `claude plugin validate
        # --strict` in the docparse-skill repo's own CI.)
        marketplace = _fetch_json("marketplace.json")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        warn(
            f"Could not fetch {SKILL_REPO} marketplace.json ({e}) — skipping live "
            f"source-of-truth check. CI with network access will enforce it."
        )
        return 0

    failures = 0
    live_marketplace = marketplace.get("name")
    plugins = marketplace.get("plugins") or []

    if live_marketplace != MARKETPLACE_NAME:
        fail(
            f"{SKILL_REPO} marketplace.json name='{live_marketplace}' but docs/"
            f"this check expect '{MARKETPLACE_NAME}'. Update MARKETPLACE_NAME "
            f"and every doc's `/plugin install` command together."
        )
        failures += 1
    if not any(p.get("name") == PLUGIN_NAME for p in plugins):
        listed = ", ".join(p.get("name", "?") for p in plugins) or "(none)"
        fail(
            f"{SKILL_REPO} marketplace.json does not list a plugin named "
            f"'{PLUGIN_NAME}' (lists: {listed})."
        )
        failures += 1

    if not failures:
        ok(
            f"Live {SKILL_REPO} manifests match the documented command "
            f"`{EXPECTED_PLUGIN_INSTALL}`"
        )
    return failures


def main() -> int:
    files = scan_files()
    failures = 0
    failures += check_forbidden(files)
    failures += check_required_present(files)
    failures += check_live_source_of_truth()

    print()
    if failures:
        print(f"✗ {failures} install-docs check(s) failed", file=sys.stderr)
        return 1
    print("✓ All install-docs checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
