#!/usr/bin/env python3
"""
Regression guard for the browser WASM bundle.

The homepage demo and workbench rely on a small set of invariants that have
broken silently in the past:

  1. Every symbol called from JS via `engine.call('NAME', ...)` must be
     exported as `export ... func NAME` from the canonical source
     `docparse/services/docparse_browser.ail`. We learned this the hard way
     when commit 6cd2d48 sync'd source → vendored and silently dropped
     `parseCsvContent` / `parseMarkdownContent` etc., breaking text-format
     parsing on the deployed homepage for several days.

  2. Every module path in `MODULES_TO_LOAD` (docs/js/wasm-demo.js) must
     resolve to a real file under `docparse/` so the vendor script and the
     CI workflow can copy it.

  3. Every module the vendor script copies must also be referenced from
     `MODULES_TO_LOAD`. Otherwise we ship dead code into the bundle.

  4. Every HTML page that loads `js/wasm-demo.js` must also load
     `js/docparse-blocks.js` *before* it. wasm-demo.js delegates markdown
     conversion (and the workbench delegates more) to that shared module —
     loading them out of order silently breaks both pages.

Run from repo root:

    python3 docs/scripts/check-wasm-bindings.py

Exit code: 0 = pass, 1 = at least one invariant violated.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = ROOT / "docs"
WASM_DEMO_JS = DOCS_DIR / "js" / "wasm-demo.js"
BLOCKS_JS = DOCS_DIR / "js" / "docparse-blocks.js"
SOURCE_BROWSER = ROOT / "docparse" / "services" / "docparse_browser.ail"
SOURCE_DOCPARSE = ROOT / "docparse"
VENDOR_SCRIPT = DOCS_DIR / "scripts" / "vendor-wasm-packages.sh"
VENDORED_PKG_DIR = DOCS_DIR / "ailang" / "pkg"
VENDORED_DOCPARSE_DIR = DOCS_DIR / "ailang" / "docparse"

# Symbols that exist on the engine wrapper itself (not in docparse_browser.ail).
# Add to this set when wasm-demo.js gets new front-end-only call targets.
JS_ONLY_SYMBOLS: set[str] = set()


def fail(msg: str) -> None:
    print(f"  ✗ {msg}", file=sys.stderr)


def ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def extract_engine_calls(js_source: str) -> set[str]:
    """Find every `engine.call('NAME', ...)` and `engine.callAsync('NAME', ...)`."""
    pattern = re.compile(r"engine\.(?:call|callAsync)\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]")
    return set(pattern.findall(js_source))


def extract_repl_calls(js_source: str) -> set[str]:
    """Find every `repl.call(MODULE, 'NAME', ...)` and `repl.callAsync(MODULE, 'NAME', ...)`."""
    pattern = re.compile(
        r"repl\.(?:call|callAsync)\(\s*[A-Za-z_][A-Za-z0-9_]*\s*,\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"
    )
    return set(pattern.findall(js_source))


def extract_ailang_exports(ail_source: str) -> set[str]:
    """Find every `export [pure] func NAME(...)` and `export [pure] func NAME =`."""
    pattern = re.compile(
        r"^\s*export\s+(?:pure\s+)?func\s+([A-Za-z_][A-Za-z0-9_]*)",
        re.MULTILINE,
    )
    return set(pattern.findall(ail_source))


def extract_modules_to_load(js_source: str) -> list[tuple[str, str]]:
    """Pull (name, path) tuples out of the MODULES_TO_LOAD literal."""
    block_match = re.search(
        r"MODULES_TO_LOAD\s*=\s*\[(.*?)\];",
        js_source,
        re.DOTALL,
    )
    if not block_match:
        return []
    block = block_match.group(1)
    entry_pattern = re.compile(
        r"\{\s*name:\s*['\"]([^'\"]+)['\"]\s*,\s*path:\s*['\"]([^'\"]+)['\"]\s*\}"
    )
    return entry_pattern.findall(block)


def extract_pkg_imports(ail_source: str) -> list[tuple[str, list[str]]]:
    """Pull (pkg_path, [imported_names]) tuples from `import pkg/...` lines.

    Matches both single-line and the common `(name1, name2, ...)` form. Skips
    type-only imports inside parens — we deliberately treat all bracketed
    names uniformly because the AILANG resolver does too.
    """
    pattern = re.compile(
        r"^\s*import\s+(pkg/[A-Za-z0-9_/]+)\s*\(([^)]*)\)",
        re.MULTILINE,
    )
    results: list[tuple[str, list[str]]] = []
    for pkg_path, names_blob in pattern.findall(ail_source):
        names: list[str] = []
        for raw in names_blob.split(","):
            tok = raw.strip()
            if not tok:
                continue
            # Handle "X as Y" — we want the source name X.
            tok = tok.split(" as ")[0].strip()
            if tok:
                names.append(tok)
        results.append((pkg_path, names))
    return results


def extract_vendor_modules(vendor_source: str) -> list[str]:
    """Pull the MODULES bash array out of vendor-wasm-packages.sh."""
    block_match = re.search(r"MODULES=\(\s*(.*?)\s*\)", vendor_source, re.DOTALL)
    if not block_match:
        return []
    block = block_match.group(1)
    return re.findall(r'"([^"]+)"', block)


def main() -> int:
    print("→ Checking WASM bindings...")
    failures = 0

    if not WASM_DEMO_JS.exists():
        fail(f"Missing {WASM_DEMO_JS}")
        return 1
    if not SOURCE_BROWSER.exists():
        fail(f"Missing {SOURCE_BROWSER}")
        return 1
    if not VENDOR_SCRIPT.exists():
        fail(f"Missing {VENDOR_SCRIPT}")
        return 1

    js = WASM_DEMO_JS.read_text()
    ail = SOURCE_BROWSER.read_text()
    vendor = VENDOR_SCRIPT.read_text()

    # ── Invariant 1: every engine.call('NAME', ...) is exported ──────────
    # `engine` wraps DOCPARSE_MODULE = 'docparse/services/docparse_browser',
    # so every engine.call symbol must be exported from that module.
    engine_calls = extract_engine_calls(js)
    exports = extract_ailang_exports(ail)
    print(f"  Found {len(engine_calls)} engine.call() symbols, {len(exports)} exports in docparse_browser.ail")

    missing = (engine_calls - JS_ONLY_SYMBOLS) - exports
    if missing:
        for name in sorted(missing):
            fail(
                f"engine.call('{name}', ...) in wasm-demo.js — but no `export func {name}` "
                f"in docparse/services/docparse_browser.ail"
            )
        failures += len(missing)
    else:
        ok("All engine.call() symbols are exported by source docparse_browser.ail")

    # ── Invariant 1b: every repl.call(MODULE, 'NAME', ...) is also exported ──
    # These bypass the engine wrapper and call DOCPARSE_MODULE directly.
    repl_calls = extract_repl_calls(js)
    if repl_calls:
        repl_missing = repl_calls - exports - JS_ONLY_SYMBOLS
        if repl_missing:
            for name in sorted(repl_missing):
                fail(
                    f"repl.call(MODULE, '{name}', ...) in wasm-demo.js — but no `export func {name}` "
                    f"in docparse/services/docparse_browser.ail"
                )
            failures += len(repl_missing)
        else:
            ok(f"All {len(repl_calls)} repl.call() symbols are exported")

    # ── Invariant 2: every MODULES_TO_LOAD path resolves to a source file ──
    modules = extract_modules_to_load(js)
    if not modules:
        fail("Could not parse MODULES_TO_LOAD from wasm-demo.js — regex needs updating")
        failures += 1
    else:
        print(f"  Found {len(modules)} entries in MODULES_TO_LOAD")
        unresolved: list[tuple[str, str]] = []
        for name, path in modules:
            # MODULES_TO_LOAD paths are relative to docs/ailang/. Skip vendored
            # packages (pkg/...) which come from the registry cache, not source.
            if path.startswith("pkg/"):
                continue
            if not path.startswith("docparse/"):
                fail(f"MODULES_TO_LOAD entry has unexpected path: {path}")
                failures += 1
                continue
            relative = path[len("docparse/"):]
            source_file = SOURCE_DOCPARSE / relative
            if not source_file.exists():
                unresolved.append((name, path))
        if unresolved:
            for name, path in unresolved:
                fail(f"MODULES_TO_LOAD references {path} but {SOURCE_DOCPARSE / path[len('docparse/'):]} does not exist")
            failures += len(unresolved)
        else:
            ok("All MODULES_TO_LOAD paths resolve to source files")

    # ── Invariant 3: vendor script and MODULES_TO_LOAD agree ─────────────
    vendor_modules = extract_vendor_modules(vendor)
    if not vendor_modules:
        fail("Could not parse MODULES array from vendor-wasm-packages.sh")
        failures += 1
    else:
        # Vendor module paths are relative to docparse/ (e.g. "services/csv_parser.ail")
        # MODULES_TO_LOAD paths are relative to docs/ailang/ (e.g. "docparse/services/csv_parser.ail")
        vendor_set = {f"docparse/{m}" for m in vendor_modules}
        loaded_set = {path for _, path in modules if not path.startswith("pkg/")}

        loaded_not_vendored = loaded_set - vendor_set
        vendored_not_loaded = vendor_set - loaded_set

        if loaded_not_vendored:
            for path in sorted(loaded_not_vendored):
                fail(f"{path} is loaded by wasm-demo.js but not copied by vendor-wasm-packages.sh")
            failures += len(loaded_not_vendored)
        if vendored_not_loaded:
            for path in sorted(vendored_not_loaded):
                fail(f"{path} is vendored but never loaded by wasm-demo.js (dead vendoring)")
            failures += len(vendored_not_loaded)
        if not loaded_not_vendored and not vendored_not_loaded:
            ok(f"vendor-wasm-packages.sh and MODULES_TO_LOAD agree on {len(vendor_set)} modules")

    # ── Invariant 3b: vendored pkg/... packages export every imported symbol ──
    # The browser bundle has no package resolution — it loads exactly the
    # vendored .ail files. If a docparse module imports a symbol from
    # `pkg/sunholo/foo` that the vendored copy doesn't export (e.g. version
    # drift between ailang.lock and the vendored bundle), WASM init fails at
    # runtime with "undefined global variable" and tests don't catch it
    # because `ailang check` resolves against the *registry* version.
    pkg_failures = 0
    pkg_checked = 0
    for vendored_module in sorted(VENDORED_DOCPARSE_DIR.rglob("*.ail")):
        for pkg_path, imported in extract_pkg_imports(vendored_module.read_text()):
            # pkg_path is like "pkg/sunholo/a2ui/components" — strip leading
            # "pkg/" and append .ail to find the vendored file.
            rel = pkg_path[len("pkg/"):]
            pkg_file = VENDORED_PKG_DIR / f"{rel}.ail"
            if not pkg_file.exists():
                fail(
                    f"{vendored_module.relative_to(ROOT)} imports {pkg_path} but "
                    f"{pkg_file.relative_to(ROOT)} is not vendored"
                )
                pkg_failures += 1
                continue
            pkg_exports = extract_ailang_exports(pkg_file.read_text())
            # Type names also count as exports — they're declared via
            # `export type Foo = ...`. Pull those in too.
            type_pattern = re.compile(
                r"^\s*export\s+type\s+([A-Za-z_][A-Za-z0-9_]*)",
                re.MULTILINE,
            )
            pkg_exports |= set(type_pattern.findall(pkg_file.read_text()))
            missing = [n for n in imported if n not in pkg_exports]
            if missing:
                fail(
                    f"{vendored_module.relative_to(ROOT)} imports {missing} from "
                    f"{pkg_path} but vendored {pkg_file.relative_to(ROOT)} does not "
                    f"export them — re-run docs/scripts/vendor-wasm-packages.sh "
                    f"(version drift between ailang.lock and vendored bundle)"
                )
                pkg_failures += len(missing)
            pkg_checked += 1
    if pkg_checked == 0:
        ok("No pkg/ imports in vendored modules to check")
    elif pkg_failures == 0:
        ok(f"All pkg/ imports across {pkg_checked} vendored module(s) resolve to vendored exports")
    failures += pkg_failures

    # ── Invariant 4: HTML pages load docparse-blocks.js before wasm-demo.js ──
    if not BLOCKS_JS.exists():
        fail(f"Missing {BLOCKS_JS} — the shared block helpers module")
        failures += 1
    else:
        script_re = re.compile(
            r'<script[^>]+src=["\']js/(docparse-blocks|wasm-demo)\.js["\']',
        )
        html_pages = sorted(DOCS_DIR.glob("*.html"))
        checked = 0
        for page in html_pages:
            text = page.read_text()
            order = [m.group(1) for m in script_re.finditer(text)]
            if "wasm-demo" not in order:
                continue  # page doesn't use the WASM demo at all
            checked += 1
            if "docparse-blocks" not in order:
                fail(
                    f"{page.name} loads wasm-demo.js but not docparse-blocks.js — "
                    f"add `<script src=\"js/docparse-blocks.js\"></script>` before wasm-demo.js"
                )
                failures += 1
                continue
            if order.index("docparse-blocks") > order.index("wasm-demo"):
                fail(
                    f"{page.name} loads docparse-blocks.js AFTER wasm-demo.js — "
                    f"wasm-demo.js reads window.DocParseBlocks and will fail silently"
                )
                failures += 1
        if checked > 0 and not any(True for _ in []):
            ok(f"{checked} HTML page(s) load docparse-blocks.js before wasm-demo.js")

    print()
    if failures:
        print(f"✗ {failures} binding check(s) failed", file=sys.stderr)
        return 1
    print("✓ All WASM binding checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
