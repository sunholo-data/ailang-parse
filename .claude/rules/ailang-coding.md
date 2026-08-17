---
description: AILANG coding conventions, bug policy, and project-specific rules for .ail files
---

# AILANG Coding Rules for This Project

## Module Conventions

- `module` declarations use `docparse/` prefix (e.g., `module docparse/services/docx_parser`)
- Source must live under `docparse/` relative to working directory
- Type-check before committing: `ailang check docparse/`
- Use `ailang docs <module>` to check stdlib before assuming features are missing

## AILANG Bug Policy

**Do NOT work around AILANG bugs.** If you hit an AILANG compiler, runtime, or stdlib bug:

1. **Stop** — do not implement a hacky workaround
2. **Report it** via `ailang messages send ailang-core "<description>" --type bug --github`
3. **Tell the user** what you hit and that you've reported it
4. **Wait** for guidance before proceeding

Known bugs (for awareness, not workarounds):
- **Module scoping**: Non-exported internal functions with same name + type across modules collide at runtime. Prefix all internal helpers with module name.
- **Test harness**: Inline `tests [...]` on functions calling stdlib fail with "cannot apply non-function value: nil". Test via `main()` instead.
- **Transitive imports**: Entry module must import all transitive dependencies.
- **`callJson`**: Corrupts large responses with multimodal. Use `callJsonSimple` instead.
- **`call()`**: Truncates at ~491 chars. Use `callJsonSimple` for generation.

## Contracts

91 `ensures` clauses across modules; Z3 proves 14 of them, the rest skip as
recursive/higher-order. Verify with:
- `ailang run --verify-contracts ...` (runtime — this is where most of them fire)
- `ailang verify <file>` or `./bin/docparse --prove` (static Z3)

Both run in CI. `--prove` gates on VIOLATIONs only; skips and encoder errors
(upstream sunholo-data/ailang#755-757) are reported without failing the build.

**Write contracts that can be false.** An audit found 13 that could not be:
`ensures { listLength(result) >= 0 }` and friends hold of every list that has
ever existed, so Z3 discharged them for free and they read as coverage while
constraining nothing. In every case the comment above stated the real property
("empty content produces no blocks") and the contract stated its tautological
inverse. If a postcondition cannot fail, it is a comment — write it as one.

**There are zero `requires` clauses.** With no preconditions, every `ensures`
must hold for arbitrary input, which is the pressure that produces weak
postconditions. Reach for `requires` when adding a contract.
