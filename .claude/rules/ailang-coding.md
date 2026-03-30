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

28+ contracts across modules. Verify with:
- `ailang run --verify-contracts ...` (runtime)
- `ailang verify <file>` or `./bin/docparse --prove` (static Z3)
