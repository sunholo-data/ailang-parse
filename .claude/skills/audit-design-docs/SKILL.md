---
name: audit-design-docs
description: Audit the design_docs/ folder structure against the current project version. Use when user says 'audit design docs', 'check design docs', 'are design docs organized', 'verify design doc placement', 'tidy design docs', or asks about misplaced/stale design documents. Also use when the user asks to reorganize planned vs implemented docs, or after a version bump.
---

# Audit Design Docs

## How It Works

The audit compares the project's current version (from `ailang.toml`) against every design doc in `design_docs/` and flags inconsistencies. The `implemented/` folder is a changelog — version folders reflect the actual release each feature shipped in. The `planned/` folder has target versions for future work.

## Workflow

### Step 1: Get Current Version

```bash
grep '^version' ailang.toml
```

### Step 2: Run the Audit Script

```bash
bash .claude/skills/audit-design-docs/scripts/audit.sh
```

### Step 3: Review Findings

| Category | Severity | Meaning |
|----------|----------|---------|
| `VERSION_MISMATCH` | High | Implemented doc with version > current (impossible — hasn't shipped) |
| `STATUS_CONTRADICTION` | High | Doc's Status: header contradicts its folder |
| `LOOSE_FILE` | Medium | File not in a version subfolder |
| `STALE_PLANNED` | Medium | Planned doc with version <= current (should be implemented or re-versioned) |

### Step 4: Propose and Execute Fixes

For each finding, propose a move. Use `git mv` for tracked files. Always ask user to confirm before executing. After moves, update `design_docs/README.md`.

## Rules

1. Never delete design docs — move to `archive/` if superseded
2. `implemented/` folders must use the actual release version, not the design milestone version
3. The Go binary doc is intentionally unversioned (blocked on external compiler bugs) — don't flag it
4. When moving to `implemented/`, strip old version prefixes from filenames
5. Update Status: headers when moving docs between folders
