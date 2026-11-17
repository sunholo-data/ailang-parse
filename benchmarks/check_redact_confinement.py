#!/usr/bin/env python3
"""Stop-gap lint: the redaction boundary is where the design says it is.

The compiler proves each IFC rule inside docparse/redact/ (benchmarks/
check_redact_ifc.sh shows it rejecting every leak). What it cannot prove yet is
the boundary itself, because AILANG's stdlib egress (std/fs.writeFile, std/io,
std/net, std/ai) accepts labelled values and FS also permits writes. Until
AILANG ships an egress policy and FS[mode=read] (design v0_58_0_ifc_redaction.md,
AILANG dependencies 1-2), this lint checks:

  1. effect rows: policy.ail and core.ail declare no IO/FS/Net/AI/Process/Env/
     Clock/Rand effects; source.ail only FS; egress.ail only FS and IO;
  2. imports: only egress.ail imports std/fs, std/io, std/net, std/ai or
     std/process; source.ail imports only parseDocumentPure, defaultParseOptions
     and ParseOutcome from the orchestrator;
  3. exactly one `! {Declassify...}` site, core.redactOutcome, scoped to
     [label=doc_content];
  4. every string parameter of every egress.ail export is {not doc_content};
  5. no other module exists in docparse/redact/ (a new module is reviewed and
     added here on purpose).

Usage: python3 benchmarks/check_redact_confinement.py [ROOT]   (ROOT = repo root)
"""
import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
REDACT = ROOT / "docparse" / "redact"

EGRESS_EFFECTS = {"IO", "FS", "Net", "AI", "Process", "Env", "Clock", "Rand", "Secret", "SharedMem"}
ALLOWED_EFFECTS = {
    "policy.ail": set(),
    "core.ail": set(),
    "source.ail": {"FS"},
    "egress.ail": {"FS", "IO"},
}
EGRESS_STD = ("std/fs", "std/io", "std/net", "std/ai", "std/process", "std/env")

failures = []


def fail(msg):
    failures.append(msg)
    print("  FAIL " + msg)


def strip_comments(text):
    return "\n".join(line.split("--", 1)[0] if not line.lstrip().startswith("--") else ""
                     for line in text.splitlines())


def effect_rows(text):
    """Every `! { ... }` row: (row text, line number)."""
    for m in re.finditer(r"!\s*\{([^}]*)\}", text):
        yield m.group(1), text[: m.start()].count("\n") + 1


def main():
    if not REDACT.is_dir():
        sys.exit(f"no {REDACT}")
    files = {p.name: strip_comments(p.read_text()) for p in sorted(REDACT.glob("*.ail"))}

    print("redaction confinement (docparse/redact/)")
    extra = sorted(set(files) - set(ALLOWED_EFFECTS))
    if extra:
        fail(f"rule 5: unreviewed module(s) in docparse/redact/: {extra}")
    for name in ALLOWED_EFFECTS:
        if name not in files:
            fail(f"rule 5: {name} missing")

    declass_sites = []
    for name, text in files.items():
        allowed = ALLOWED_EFFECTS.get(name, set())
        for row, line in effect_rows(text):
            atoms = [a.strip() for a in row.split(",") if a.strip()]
            for atom in atoms:
                base = atom.split("[", 1)[0]
                if base == "Declassify":
                    declass_sites.append((name, line, atom))
                elif base in EGRESS_EFFECTS and base not in allowed:
                    fail(f"rule 1: {name}:{line} declares {atom}; allowed here: {sorted(allowed) or 'none'}")
        for m in re.finditer(r"^\s*import\s+(\S+)\s*(\(([^)]*)\))?", text, re.M):
            mod, names = m.group(1), m.group(3) or ""
            if mod.startswith(EGRESS_STD) and name != "egress.ail":
                fail(f"rule 2: {name} imports {mod}; only egress.ail may")
            if name == "source.ail":
                got = {n.strip().split(" as ")[0] for n in names.split(",") if n.strip()}
                ok = (mod == "std/result" and got <= {"Ok", "Err", "Result"}) or (
                    mod == "docparse/services/orchestrator" and got <= {
                        "parseDocumentPure", "defaultParseOptions", "ParseOutcome"})
                if not ok:
                    fail(f"rule 2: source.ail imports {mod} ({', '.join(sorted(got))}); "
                         "only parseDocumentPure/defaultParseOptions/ParseOutcome from the orchestrator")

    want = [("core.ail", "Declassify[label=doc_content]")]
    got = [(n, a.replace(" ", "")) for n, _, a in declass_sites]
    if got != want:
        fail(f"rule 3: Declassify sites {[(n, l, a) for n, l, a in declass_sites]}; "
             "want exactly one, Declassify[label=doc_content] on core.redactOutcome")
    elif not re.search(r"export func redactOutcome\([^!]*!\s*\{\s*Declassify\[label=doc_content\]\s*\}",
                       files.get("core.ail", ""), re.S):
        fail("rule 3: the Declassify site is not core.redactOutcome")

    egress = files.get("egress.ail", "")
    for m in re.finditer(r"export func (\w+)\(([^)]*)\)", egress):
        fn, params = m.group(1), m.group(2)
        for p in [p.strip() for p in params.split(",") if p.strip()]:
            pname, _, ptype = p.partition(":")
            ptype = ptype.strip()
            if ptype.startswith("string") and ptype.replace(" ", "") != "string{notdoc_content}":
                fail(f"rule 4: egress.{fn} parameter {pname.strip()}: {ptype} is not {{not doc_content}}")
            if not ptype.startswith("string"):
                fail(f"rule 4: egress.{fn} parameter {pname.strip()}: {ptype}; egress takes strings only")

    if failures:
        print(f"\n{len(failures)} confinement rule(s) broken")
        sys.exit(1)
    print("  ok   effects, imports, one declassifier, guarded egress, no unreviewed modules")
    print("\nredaction confinement: all rules hold")


if __name__ == "__main__":
    main()
