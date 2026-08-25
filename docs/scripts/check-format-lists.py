#!/usr/bin/env python3
"""Check the advertised format lists against the parser that actually runs.

Why this exists
---------------
RTF parsed correctly on the hosted API for weeks while every format list said
it was unsupported. A caller checking /api/v1/formats first would conclude it
could not send an .rtf — and the docs site meanwhile shipped a whole
rtf-parsing.html page. Three hardcoded copies of the list had drifted from
format_router, and nothing compared them.

The lists are hand-maintained on purpose: a service can legitimately decline to
offer something it can technically parse. What is NOT legitimate is drifting
without noticing. So this does not force the lists to match the router — it
forces every difference to be *declared* below, with a reason.

Run:  python3 docs/scripts/check-format-lists.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROUTER = ROOT / "docparse/services/format_router.ail"
MCP_TOOLS = ROOT / "docparse/services/mcp/tools.ail"

# Extensions the router recognises but mcpFormats deliberately does not list,
# each with the reason it is out. Anything not named here must be advertised.
DELIBERATE_OMISSIONS = {
    # Aliases — the canonical extension is advertised instead.
    "jpeg": "alias of jpg",
    "htm": "alias of html",
    "xhtml": "alias of html",
    "markdown": "alias of md",
    "tsv": "covered by csv",
    "latex": "alias of tex",
    "ltx": "alias of tex",
    # Generic text fallback, not a document format with structure to extract.
    "txt": "plain text fallback, no structure",
    "xml": "generic text fallback",
    "json": "generic text fallback",
    # Image/audio/video variants beyond the representative ones advertised.
    "gif": "image variant; png/jpg represent the class",
    "bmp": "image variant",
    "webp": "image variant",
    "tiff": "image variant",
    "wav": "audio variant; mp3 represents the class",
    "aiff": "audio variant",
    "aac": "audio variant",
    "ogg": "audio variant",
    "flac": "audio variant",
    "mpeg": "video variant; mp4 represents the class",
    "mov": "video variant",
    "avi": "video variant",
    "flv": "video variant",
    "mpg": "video variant",
    "webm": "video variant",
    "wmv": "video variant",
    "3gpp": "video variant",
}


def router_extensions() -> set[str]:
    """Every extension detectFormat maps to something other than "unknown"."""
    src = ROUTER.read_text()
    m = re.search(r"func detectFormat.*?\n\}", src, re.S)
    if not m:
        sys.exit("could not locate detectFormat in format_router.ail")
    body = m.group(0)
    # Only the dispatch arms: `ext == "docx"`, etc.
    return set(re.findall(r'ext\s*==\s*"([a-z0-9]+)"', body))


def advertised_extensions() -> set[str]:
    """Extensions listed by mcpFormats via mcpFormatEntry."""
    src = MCP_TOOLS.read_text()
    m = re.search(r'kv\("input_formats".*?\]\)\)', src, re.S)
    if not m:
        sys.exit("could not locate input_formats in mcp/tools.ail")
    return set(re.findall(r'mcpFormatEntry\("([a-z0-9]+)"', m.group(0)))


def main() -> int:
    routed = router_extensions()
    advertised = advertised_extensions()

    if not routed or not advertised:
        sys.exit("parsed an empty list — the source shape probably changed")

    undeclared = sorted(routed - advertised - set(DELIBERATE_OMISSIONS))
    phantom = sorted(advertised - routed)
    stale_omissions = sorted(set(DELIBERATE_OMISSIONS) - routed)

    print(f"format_router recognises {len(routed)} extensions")
    print(f"mcpFormats advertises    {len(advertised)}")

    failed = False

    if undeclared:
        failed = True
        print("\n✗ parseable but not advertised, and not declared as deliberate:")
        for e in undeclared:
            print(f"    .{e}")
        print("\n  Either add it to mcpFormats' input_formats, or add it to")
        print("  DELIBERATE_OMISSIONS in this script with the reason it is out.")

    if phantom:
        failed = True
        print("\n✗ advertised but the router cannot parse them:")
        for e in phantom:
            print(f"    .{e}")
        print("\n  These promise a capability that does not exist.")

    if stale_omissions:
        failed = True
        print("\n✗ declared as deliberate omissions but the router no longer knows them:")
        for e in stale_omissions:
            print(f"    .{e} ({DELIBERATE_OMISSIONS[e]})")
        print("\n  Remove them from DELIBERATE_OMISSIONS — the exemption is dead.")

    if failed:
        return 1

    print(f"\n✓ every parseable format is advertised or declared "
          f"({len(DELIBERATE_OMISSIONS)} deliberate omissions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
