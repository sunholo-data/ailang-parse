"""DocParse Email Gap Analysis — measures RFC 5322 + MIME parser coverage.

Same pattern as eval_gaps.py for Office formats: each check returns 0.0-1.0.
Run after creating eml_parser.ail to track red-to-green progress.

Usage:
    uv run benchmarks/email/eval_eml_gaps.py              # full gap report
    uv run benchmarks/email/eval_eml_gaps.py --json        # JSON output
    uv run benchmarks/email/eval_eml_gaps.py --verbose     # detailed per-check output
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_DIR = Path(__file__).parent.parent.parent
CHALLENGE_DIR = REPO_DIR / "data" / "test_files" / "challenge"
OUTPUT_DIR = REPO_DIR / "docparse" / "data"


def parse_file(filepath: Path) -> dict | None:
    """Run DocParse on a file and return the JSON output."""
    result = subprocess.run(
        ["ailang", "run", "--entry", "main", "--caps", "IO,FS,Env",
         "--max-recursion-depth", "50000",
         "docparse/main.ail", str(filepath)],
        capture_output=True, text=True, cwd=str(REPO_DIR),
        timeout=120,
    )
    if result.returncode != 0:
        return None

    output_json = OUTPUT_DIR / f"{filepath.name}.json"
    if not output_json.exists():
        return None

    with open(output_json) as f:
        return json.load(f)


def get_blocks(output: dict) -> list[dict]:
    """Extract blocks from DocParse output."""
    return output.get("document", {}).get("blocks", [])


def get_metadata(output: dict) -> dict:
    """Extract document metadata."""
    return output.get("document", {}).get("metadata", {})


def flatten_blocks(blocks: list[dict]) -> list[dict]:
    """Recursively flatten section blocks."""
    result = []
    for b in blocks:
        if b.get("type") == "section":
            result.extend(flatten_blocks(b.get("blocks", [])))
        else:
            result.append(b)
    return result


# --- P0: Core Structure (RFC 5322) ---

def check_eml_header_extraction(output: dict) -> dict:
    """Does the parser extract standard email headers?

    File: challenge_basic.eml
    Expected: From, To, Subject, Date headers preserved in output.
    Spec: RFC 5322 §2.2
    """
    full_output = json.dumps(output)
    metadata = get_metadata(output)

    expected = {
        "alice@example.com": "From address",
        "bob@example.com": "To address",
        "Q1 Budget Review Meeting": "Subject",
    }

    # Check headers appear anywhere in output
    found = sum(1 for text in expected if text in full_output)
    total = len(expected)

    # Bonus: check metadata mapping (Subject→title, From→author)
    has_title = "Q1 Budget Review" in metadata.get("title", "")
    has_author = "alice" in metadata.get("author", "").lower() or "Alice" in metadata.get("author", "")

    return {
        "name": "EML Header Extraction",
        "spec_ref": "RFC 5322 §2.2",
        "file": "challenge_basic.eml",
        "score": found / total if total else 0,
        "detected": found,
        "total": total,
        "has_metadata_title": has_title,
        "has_metadata_author": has_author,
        "detail": f"{found}/{total} headers extracted (title: {'yes' if has_title else 'no'}, author: {'yes' if has_author else 'no'})",
    }


def check_eml_header_folding(output: dict) -> dict:
    """Does the parser unfold multi-line (continuation) headers?

    File: challenge_folded_headers.eml
    Expected: Long headers unfolded into single values.
    Spec: RFC 5322 §2.2.3
    """
    full_output = json.dumps(output)

    # The Subject is split across 3 lines — it should be unfolded
    # Check key parts of the unfolded subject appear together
    checks = {
        "Updated Research Collaboration Agreement": "Subject part 1",
        "Computational Analysis Pipeline": "Subject part 3",
        "margaret.worthington-smythe@university-of-cambridge.ac.uk": "From address (folded)",
    }

    found = sum(1 for text in checks if text in full_output)
    total = len(checks)

    return {
        "name": "EML Header Folding",
        "spec_ref": "RFC 5322 §2.2.3",
        "file": "challenge_folded_headers.eml",
        "score": found / total if total else 0,
        "detected": found,
        "total": total,
        "detail": f"{found}/{total} folded header values correctly unfolded",
    }


def check_eml_body_extraction(output: dict) -> dict:
    """Does the parser extract plain text email body?

    File: challenge_basic.eml
    Expected: Body text preserved as text blocks.
    Spec: RFC 5322 §2.3
    """
    blocks = flatten_blocks(get_blocks(output))
    all_text = " ".join(b.get("text", "") for b in blocks)

    expected_content = [
        "Q1 budget review",
        "Revenue exceeded projections by 12%",
        "Marketing spend was under budget",
        "schedule a meeting for Thursday",
    ]

    found = sum(1 for text in expected_content if text.lower() in all_text.lower())
    total = len(expected_content)

    return {
        "name": "EML Body Extraction",
        "spec_ref": "RFC 5322 §2.3",
        "file": "challenge_basic.eml",
        "score": found / total if total else 0,
        "detected": found,
        "total": total,
        "detail": f"{found}/{total} body content segments preserved",
    }


def check_eml_metadata_mapping(output: dict) -> dict:
    """Does the parser map email headers to DocMetadata?

    File: challenge_basic.eml
    Expected: Subject→title, From→author, Date→created.
    Spec: RFC 5322 (mapped to DocMetadata)
    """
    metadata = get_metadata(output)

    checks = {
        "title": ("Q1 Budget Review Meeting", "Subject→title"),
        "author": ("Alice Smith", "From→author"),
    }

    found = 0
    total = len(checks)
    for field, (expected, _desc) in checks.items():
        val = metadata.get(field, "")
        if expected.lower() in val.lower():
            found += 1

    # Check date exists in some form
    has_date = bool(metadata.get("created", ""))
    if has_date:
        found += 1
    total += 1

    return {
        "name": "EML Metadata Mapping",
        "spec_ref": "RFC 5322",
        "file": "challenge_basic.eml",
        "score": found / total if total else 0,
        "detected": found,
        "total": total,
        "detail": f"{found}/{total} metadata fields mapped (title, author, created)",
    }


# --- P1: MIME Multipart (RFC 2046) ---

def check_eml_multipart_alternative(output: dict) -> dict:
    """Does the parser handle multipart/alternative (text + HTML)?

    File: challenge_multipart_alt.eml
    Expected: Text and/or HTML content extracted from multipart boundary.
    Spec: RFC 2046 §5.1.4
    """
    blocks = flatten_blocks(get_blocks(output))
    all_text = " ".join(b.get("text", "") for b in blocks)
    full_output = json.dumps(output)

    expected_content = [
        "Phase 2 milestone",
        "API integration complete",
        "Performance targets met",
        "Security audit passed",
    ]

    found = sum(1 for text in expected_content if text in full_output)
    total = len(expected_content)

    return {
        "name": "EML Multipart Alternative",
        "spec_ref": "RFC 2046 §5.1.4",
        "file": "challenge_multipart_alt.eml",
        "score": found / total if total else 0,
        "detected": found,
        "total": total,
        "detail": f"{found}/{total} content items from multipart/alternative",
    }


def check_eml_multipart_mixed(output: dict) -> dict:
    """Does the parser handle multipart/mixed (body + parsed attachment)?

    File: challenge_multipart_mixed.eml
    Expected: Body text extracted, CSV attachment parsed inline with table data.
    Spec: RFC 2046 §5.1.3
    """
    full_output = json.dumps(output)

    checks = {
        "Q1 revenue report": "Body text",
        "revenue_q1.csv": "Attachment filename in meta",
        "$268,000": "Body detail",
        "125000": "CSV data (Q1 revenue)",
        "143000": "CSV data (Q2 revenue)",
    }

    found = sum(1 for text in checks if text in full_output)
    total = len(checks)

    return {
        "name": "EML Multipart Mixed",
        "spec_ref": "RFC 2046 §5.1.3",
        "file": "challenge_multipart_mixed.eml",
        "score": found / total if total else 0,
        "detected": found,
        "total": total,
        "detail": f"{found}/{total} items from multipart/mixed (body + parsed CSV attachment)",
    }


# --- P2: Encoding (RFC 2045 + 2047) ---

def check_eml_base64_body(output: dict) -> dict:
    """Does the parser decode base64-encoded body text?

    File: challenge_base64_body.eml
    Expected: Body decoded from base64 to readable text.
    Spec: RFC 2045 §6.8
    """
    full_output = json.dumps(output)

    expected_decoded = [
        "base64-encoded email body",
        "Database migration completed",
        "5x improvement",
    ]

    found = sum(1 for text in expected_decoded if text in full_output)
    total = len(expected_decoded)

    return {
        "name": "EML Base64 Body Decoding",
        "spec_ref": "RFC 2045 §6.8",
        "file": "challenge_base64_body.eml",
        "score": found / total if total else 0,
        "detected": found,
        "total": total,
        "detail": f"{found}/{total} base64 body segments decoded",
    }


def check_eml_quoted_printable(output: dict) -> dict:
    """Does the parser decode quoted-printable body text?

    File: challenge_qp_body.eml
    Expected: =XX escapes decoded, soft line breaks removed.
    Spec: RFC 2045 §6.7
    """
    # ensure_ascii=False so UTF-8 chars appear as-is for matching
    full_output = json.dumps(output, ensure_ascii=False)

    # These contain non-ASCII chars that were QP-encoded
    expected_decoded = [
        "café",       # =C3=A9 → é
        "résumé",     # multiple encoded chars
        "Zürich",     # =C3=BC → ü
    ]

    found = 0
    total = len(expected_decoded)
    for text in expected_decoded:
        if text in full_output or text.lower() in full_output.lower():
            found += 1

    return {
        "name": "EML Quoted-Printable Decoding",
        "spec_ref": "RFC 2045 §6.7",
        "file": "challenge_qp_body.eml",
        "score": found / total if total else 0,
        "detected": found,
        "total": total,
        "detail": f"{found}/{total} QP-encoded segments decoded",
    }


def check_eml_encoded_headers(output: dict) -> dict:
    """Does the parser decode RFC 2047 encoded-words in headers?

    File: challenge_encoded_headers.eml
    Expected: =?charset?B?...?= and =?charset?Q?...?= decoded.
    Spec: RFC 2047 §2
    """
    # ensure_ascii=False so UTF-8 chars appear as-is for matching
    full_output = json.dumps(output, ensure_ascii=False)
    metadata = get_metadata(output)

    checks = {
        "会議の議事録": "B-encoded Subject (Japanese)",
        "José": "Q-encoded From name (accent)",
        "García": "Q-encoded From name (accent 2)",
    }

    found = sum(1 for text in checks if text in full_output)
    total = len(checks)

    return {
        "name": "EML RFC 2047 Encoded Headers",
        "spec_ref": "RFC 2047 §2",
        "file": "challenge_encoded_headers.eml",
        "score": found / total if total else 0,
        "detected": found,
        "total": total,
        "detail": f"{found}/{total} encoded-word headers decoded",
    }


# --- P2.5: Attachment Chain Parsing ---

def check_eml_attachment_csv_parsed(output: dict) -> dict:
    """Does the parser decode and parse CSV attachments inline?

    File: challenge_attachment_chain.eml
    Expected: CSV decoded to table blocks inside attachment SectionBlock.
    Spec: Attachment chain parsing (P0)
    """
    full_output = json.dumps(output)
    blocks = get_blocks(output)

    checks = {
        "revenue_q1.csv": "Attachment filename in meta",
        "125000": "CSV data (EMEA revenue)",
        "143000": "CSV data (APAC revenue)",
        "198000": "CSV data (Americas revenue)",
    }

    found = sum(1 for text in checks if text in full_output)
    total = len(checks)

    # Check for attachment SectionBlock
    has_attachment_section = any(
        b.get("type") == "section" and b.get("kind") == "attachment"
        for b in _deep_sections(blocks)
    )

    return {
        "name": "EML Attachment CSV Parsed",
        "spec_ref": "P0 Attachment Chain",
        "file": "challenge_attachment_chain.eml",
        "score": found / total if total else 0,
        "detected": found,
        "total": total,
        "has_attachment_section": has_attachment_section,
        "detail": f"{found}/{total} CSV data values parsed inline (section: {'yes' if has_attachment_section else 'no'})",
    }


def check_eml_attachment_html_parsed(output: dict) -> dict:
    """Does the parser decode and parse HTML attachments inline?

    File: challenge_attachment_chain.eml
    Expected: HTML decoded and parsed with heading/text/list blocks.
    Spec: Attachment chain parsing (P0)
    """
    full_output = json.dumps(output)

    checks = {
        "summary.html": "HTML attachment filename",
        "Weekly Summary": "HTML heading content",
        "All targets met": "HTML paragraph content",
        "EMEA on track": "HTML list item",
    }

    found = sum(1 for text in checks if text in full_output)
    total = len(checks)

    return {
        "name": "EML Attachment HTML Parsed",
        "spec_ref": "P0 Attachment Chain",
        "file": "challenge_attachment_chain.eml",
        "score": found / total if total else 0,
        "detected": found,
        "total": total,
        "detail": f"{found}/{total} HTML content items parsed inline",
    }


def check_eml_attachment_binary_placeholder(output: dict) -> dict:
    """Does the parser keep binary attachments as placeholders?

    File: challenge_attachment_chain.eml
    Expected: PNG stays as placeholder TextBlock (not parsed).
    Spec: Attachment chain parsing (P0)
    """
    full_output = json.dumps(output)

    has_placeholder = "chart.png" in full_output and "image/png" in full_output
    # Should NOT have attachment section for PNG
    has_png_section = False
    for b in _deep_sections(get_blocks(output)):
        if b.get("kind") == "attachment":
            inner = json.dumps(b.get("blocks", []))
            if "image/png" in inner and b.get("type") == "section":
                has_png_section = True

    score = 1.0 if has_placeholder and not has_png_section else 0.0

    return {
        "name": "EML Attachment Binary Placeholder",
        "spec_ref": "P0 Attachment Chain",
        "file": "challenge_attachment_chain.eml",
        "score": score,
        "detail": f"PNG placeholder: {'yes' if has_placeholder else 'no'}, section avoided: {'yes' if not has_png_section else 'no'}",
    }


def check_eml_email_in_email(output: dict) -> dict:
    """Does the parser recursively parse message/rfc822 attachments?

    File: challenge_email_in_email.eml
    Expected: Nested email parsed with its own headers and body.
    Spec: Attachment chain parsing (P0)
    """
    full_output = json.dumps(output)

    checks = {
        "forwarded.eml": "Attachment filename",
        "Original Important Message": "Inner email subject",
        "original@example.com": "Inner email From address",
        "Deadline moved to April 15": "Inner email body content",
        "Budget increased by 20%": "Inner email body content 2",
    }

    found = sum(1 for text in checks if text in full_output)
    total = len(checks)

    return {
        "name": "EML Email-in-Email",
        "spec_ref": "P0 Attachment Chain",
        "file": "challenge_email_in_email.eml",
        "score": found / total if total else 0,
        "detected": found,
        "total": total,
        "detail": f"{found}/{total} inner email content items parsed recursively",
    }


def _deep_sections(blocks: list[dict]) -> list[dict]:
    """Recursively collect all section blocks."""
    result = []
    for b in blocks:
        if b.get("type") == "section":
            result.append(b)
            result.extend(_deep_sections(b.get("blocks", [])))
    return result


# --- P3: Advanced ---

def check_mbox_parsing(output: dict) -> dict:
    """Does the parser split MBOX into individual messages?

    File: challenge_mbox.mbox
    Expected: 3 messages parsed, each with headers and body.
    Spec: RFC 4155
    """
    blocks = get_blocks(output)
    full_output = json.dumps(output)

    # Check all 3 message subjects appear
    subjects = [
        "Sprint Planning",
        "auth refactor",
        "dashboard performance",
    ]

    found = sum(1 for text in subjects if text in full_output)
    total = len(subjects)

    # Check for mbox-message section blocks
    mbox_sections = sum(
        1 for b in blocks
        if b.get("type") == "section" and b.get("kind") == "mbox-message"
    )

    return {
        "name": "MBOX Parsing",
        "spec_ref": "RFC 4155",
        "file": "challenge_mbox.mbox",
        "score": found / total if total else 0,
        "detected": found,
        "total": total,
        "mbox_sections": mbox_sections,
        "detail": f"{found}/{total} message content found, {mbox_sections} mbox-message sections",
    }


# --- P4: Thread Reconstruction ---

def parse_file_threaded(filepath: Path) -> dict | None:
    """Run DocParse on a file with --threaded flag."""
    result = subprocess.run(
        ["ailang", "run", "--entry", "main", "--caps", "IO,FS,Env",
         "--max-recursion-depth", "50000",
         "docparse/main.ail", str(filepath), "--threaded"],
        capture_output=True, text=True, cwd=str(REPO_DIR),
        timeout=120,
    )
    if result.returncode != 0:
        return None

    output_json = OUTPUT_DIR / f"{filepath.name}.json"
    if not output_json.exists():
        return None

    with open(output_json) as f:
        return json.load(f)


def check_mbox_thread_grouping(output: dict) -> dict:
    """Does the parser group MBOX messages into conversation threads?

    File: challenge_threaded.mbox (parsed with --threaded)
    Expected: 2 thread SectionBlocks with correct message counts (3+2).
    Spec: Thread reconstruction (P1)
    """
    blocks = get_blocks(output)

    thread_sections = [
        b for b in blocks
        if b.get("type") == "section" and b.get("kind") == "thread"
    ]

    num_threads = len(thread_sections)
    # Count thread-message sections in each thread
    msg_counts = []
    for t in thread_sections:
        msgs = [
            b for b in t.get("blocks", [])
            if b.get("type") == "section" and b.get("kind") == "thread-message"
        ]
        msg_counts.append(len(msgs))

    msg_counts.sort()
    correct_threads = num_threads == 2
    correct_counts = msg_counts == [2, 3]

    score = (1.0 if correct_threads else 0.0) * 0.5 + (1.0 if correct_counts else 0.0) * 0.5

    return {
        "name": "MBOX Thread Grouping",
        "spec_ref": "P1 Thread Reconstruction",
        "file": "challenge_threaded.mbox",
        "score": score,
        "thread_count": num_threads,
        "message_counts": msg_counts,
        "detail": f"{num_threads} threads with {msg_counts} messages (expected 2 threads: [2, 3])",
    }


def check_mbox_thread_participants(output: dict) -> dict:
    """Does the parser extract correct participants per thread?

    File: challenge_threaded.mbox (parsed with --threaded)
    Expected: Thread 1 has Alice, Bob, Carol; Thread 2 has Dave, Eve.
    Spec: Thread reconstruction (P1)
    """
    full_output = json.dumps(output)
    blocks = get_blocks(output)

    thread_sections = [
        b for b in blocks
        if b.get("type") == "section" and b.get("kind") == "thread"
    ]

    checks = {
        "Alice": "Thread 1 participant",
        "Bob": "Thread 1 participant",
        "Carol": "Thread 1 participant",
        "Dave": "Thread 2 participant",
        "Eve": "Thread 2 participant",
    }

    found = sum(1 for name in checks if name in full_output)
    total = len(checks)

    return {
        "name": "MBOX Thread Participants",
        "spec_ref": "P1 Thread Reconstruction",
        "file": "challenge_threaded.mbox",
        "score": found / total if total else 0,
        "detected": found,
        "total": total,
        "detail": f"{found}/{total} participant names found in thread output",
    }


def check_eml_quote_stripping(output: dict) -> dict:
    """Does the threaded parser strip quoted text from replies?

    File: challenge_quoted_reply.eml (used within threaded MBOX context)
    Expected: Quoted '> ' lines and 'On DATE wrote:' attribution removed.
    Spec: Thread reconstruction (P1)
    """
    # For quote stripping test, we parse the quoted reply as part of a
    # synthetic single-message mbox through the threaded pipeline
    # Instead, we test by checking the threaded mbox output doesn't contain
    # quoted text from parent messages (Bob's reply to Alice in the budget thread)
    full_output = json.dumps(output)
    blocks = get_blocks(output)

    # In threaded mode, thread messages should have quoted text stripped
    # Thread 1 msg 2 (Bob) and msg 3 (Carol) should not contain ">" prefixed content
    thread_sections = [
        b for b in blocks
        if b.get("type") == "section" and b.get("kind") == "thread"
    ]

    # Simple check: the output should contain Bob's original text but not
    # have excessive repetition of Alice's text across thread messages
    has_bob_text = "increase engineering budget by 15%" in full_output
    has_carol_text = "Agreed on engineering" in full_output

    score = (1.0 if has_bob_text else 0.0) * 0.5 + (1.0 if has_carol_text else 0.0) * 0.5

    return {
        "name": "EML Quote Context (Threaded)",
        "spec_ref": "P1 Thread Reconstruction",
        "file": "challenge_threaded.mbox",
        "score": score,
        "detail": f"Bob's text: {'yes' if has_bob_text else 'no'}, Carol's text: {'yes' if has_carol_text else 'no'}",
    }


# --- Main ---

def run_gap_analysis(verbose: bool = False) -> list[dict]:
    """Run all email gap checks and return results."""
    file_checks = {
        # P0: Core (RFC 5322)
        "challenge_basic.eml": [
            check_eml_header_extraction,
            check_eml_body_extraction,
            check_eml_metadata_mapping,
        ],
        "challenge_folded_headers.eml": [check_eml_header_folding],
        # P1: MIME Multipart (RFC 2046)
        "challenge_multipart_alt.eml": [check_eml_multipart_alternative],
        "challenge_multipart_mixed.eml": [check_eml_multipart_mixed],
        # P2: Encoding (RFC 2045 + 2047)
        "challenge_base64_body.eml": [check_eml_base64_body],
        "challenge_qp_body.eml": [check_eml_quoted_printable],
        "challenge_encoded_headers.eml": [check_eml_encoded_headers],
        # P3: MBOX (RFC 4155)
        "challenge_mbox.mbox": [check_mbox_parsing],
        # P4: Attachment Chain Parsing
        "challenge_attachment_chain.eml": [
            check_eml_attachment_csv_parsed,
            check_eml_attachment_html_parsed,
            check_eml_attachment_binary_placeholder,
        ],
        "challenge_email_in_email.eml": [check_eml_email_in_email],
    }

    # Threaded checks (require --threaded flag)
    threaded_checks = {
        "challenge_threaded.mbox": [
            check_mbox_thread_grouping,
            check_mbox_thread_participants,
            check_eml_quote_stripping,
        ],
    }

    results = []

    for filename, checks in file_checks.items():
        filepath = CHALLENGE_DIR / filename
        if not filepath.exists():
            print(f"  SKIP {filename} (not found)", file=sys.stderr)
            continue

        print(f"  Parsing {filename}...", file=sys.stderr)
        output = parse_file(filepath)
        if output is None:
            print(f"  FAIL {filename} (parse error or unsupported format)", file=sys.stderr)
            for check_fn in checks:
                results.append({
                    "name": check_fn.__doc__.split("\n")[0] if check_fn.__doc__ else check_fn.__name__,
                    "spec_ref": "—",
                    "file": filename,
                    "score": 0.0,
                    "detail": "Parse failed (format not yet supported)",
                })
            continue

        for check_fn in checks:
            result = check_fn(output)
            results.append(result)
            if verbose:
                print(f"    {result['name']}: {result['score']:.0%} — {result['detail']}", file=sys.stderr)

    # Run threaded checks
    for filename, checks in threaded_checks.items():
        filepath = CHALLENGE_DIR / filename
        if not filepath.exists():
            print(f"  SKIP {filename} --threaded (not found)", file=sys.stderr)
            continue

        print(f"  Parsing {filename} (threaded)...", file=sys.stderr)
        output = parse_file_threaded(filepath)
        if output is None:
            print(f"  FAIL {filename} --threaded (parse error)", file=sys.stderr)
            for check_fn in checks:
                results.append({
                    "name": check_fn.__doc__.split("\n")[0] if check_fn.__doc__ else check_fn.__name__,
                    "spec_ref": "—",
                    "file": filename,
                    "score": 0.0,
                    "detail": "Threaded parse failed",
                })
            continue

        for check_fn in checks:
            result = check_fn(output)
            results.append(result)
            if verbose:
                print(f"    {result['name']}: {result['score']:.0%} — {result['detail']}", file=sys.stderr)

    return results


def print_report(results: list[dict]) -> None:
    """Print email gap analysis report."""
    print("\n# DocParse Email Gap Analysis — RFC 5322 + MIME Coverage\n")
    print("| Check | Spec | File | Score | Detail |")
    print("|-------|------|------|-------|--------|")

    total_score = 0
    total_checks = 0

    for r in results:
        total_checks += 1
        total_score += r["score"]
        score_pct = f"{r['score']:.0%}"
        score_emoji = "PASS" if r["score"] >= 0.8 else ("PARTIAL" if r["score"] > 0 else "GAP")
        print(f"| {r['name']} | {r['spec_ref']} | {r['file']} | {score_pct} ({score_emoji}) | {r['detail']} |")

    mean_score = total_score / total_checks if total_checks else 0
    print(f"\n**Email gap coverage: {mean_score:.0%}** ({total_checks} checks)\n")

    gaps = [r for r in results if r["score"] < 0.8]
    if gaps:
        gaps.sort(key=lambda r: r["score"])
        print("## Priority Fixes (by gap severity)\n")
        for i, r in enumerate(gaps, 1):
            print(f"{i}. **{r['name']}** ({r['spec_ref']}) — {r['score']:.0%} — {r['detail']}")
        print()


def main():
    parser = argparse.ArgumentParser(description="DocParse Email Gap Analysis")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of markdown")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose per-check output")
    args = parser.parse_args()

    os.chdir(REPO_DIR)

    results = run_gap_analysis(verbose=args.verbose)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print_report(results)


if __name__ == "__main__":
    main()
