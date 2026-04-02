"""Generate challenge EML/MBOX files that test DocParse's email parsing.

These files exercise RFC 5322 + MIME features, giving us an honest
benchmark baseline to improve against — same pattern as Office gaps.

Usage: uv run benchmarks/create_eml_challenge_files.py
"""

import os
import io
import zipfile
import base64
import quopri
from pathlib import Path

OUTPUT_DIR = Path("data/test_files/challenge")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def create_challenge_basic_eml():
    """Plain text email with standard headers.

    Tests: RFC 5322 §2.2 (headers), §2.3 (body)
    Expected: From, To, Subject, Date extracted; plain text body preserved.
    """
    eml = (
        "From: Alice Smith <alice@example.com>\r\n"
        "To: Bob Jones <bob@example.com>\r\n"
        "Subject: Q1 Budget Review Meeting\r\n"
        "Date: Mon, 15 Mar 2026 09:30:00 -0500\r\n"
        "Message-ID: <msg001@example.com>\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "Hi Bob,\r\n"
        "\r\n"
        "I wanted to follow up on our Q1 budget review. The key points are:\r\n"
        "\r\n"
        "1. Revenue exceeded projections by 12%\r\n"
        "2. Marketing spend was under budget by $15,000\r\n"
        "3. Engineering headcount increased by 3 FTEs\r\n"
        "\r\n"
        "Can we schedule a meeting for Thursday at 2pm to discuss next steps?\r\n"
        "\r\n"
        "Best regards,\r\n"
        "Alice\r\n"
    )
    (OUTPUT_DIR / "challenge_basic.eml").write_text(eml, newline="")
    print("  Created challenge_basic.eml")


def create_challenge_folded_headers_eml():
    """Email with folded (multi-line continuation) headers.

    Tests: RFC 5322 §2.2.3 (folding/unfolding)
    Expected: Long headers unfolded into single values.
    """
    eml = (
        "From: \"Dr. Margaret Elizabeth Worthington-Smythe\"\r\n"
        " <margaret.worthington-smythe@university-of-cambridge.ac.uk>\r\n"
        "To: \"Prof. Alexander Konstantinos Papadopoulos\"\r\n"
        " <alexander.papadopoulos@technical-university-munich.de>,\r\n"
        " \"Dr. Chen Wei-Lin\" <chen.weilin@national-taiwan-university.edu.tw>\r\n"
        "Subject: Re: [IMPORTANT] Updated Research Collaboration Agreement\r\n"
        " for the International Genomics Consortium — Phase 3\r\n"
        " Computational Analysis Pipeline\r\n"
        "Date: Tue, 16 Mar 2026 14:22:33 +0100\r\n"
        "Message-ID: <folded002@example.com>\r\n"
        "References: <ref001@example.com>\r\n"
        " <ref002@example.com>\r\n"
        " <ref003@example.com>\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "Dear colleagues,\r\n"
        "\r\n"
        "Please find the updated collaboration agreement attached.\r\n"
        "\r\n"
        "Best,\r\n"
        "Margaret\r\n"
    )
    (OUTPUT_DIR / "challenge_folded_headers.eml").write_text(eml, newline="")
    print("  Created challenge_folded_headers.eml")


def create_challenge_multipart_alt_eml():
    """Email with multipart/alternative (text + HTML body).

    Tests: RFC 2046 §5.1.4 (multipart/alternative)
    Expected: Both text and HTML parts extracted; boundary correctly parsed.
    """
    boundary = "----=_Part_001_boundary"
    eml = (
        "From: Carol Davis <carol@example.com>\r\n"
        "To: team@example.com\r\n"
        "Subject: Project Milestone Achieved\r\n"
        "Date: Wed, 17 Mar 2026 11:00:00 +0000\r\n"
        "Message-ID: <multi003@example.com>\r\n"
        "MIME-Version: 1.0\r\n"
        f"Content-Type: multipart/alternative;\r\n"
        f" boundary=\"{boundary}\"\r\n"
        "\r\n"
        f"--{boundary}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "Content-Transfer-Encoding: 7bit\r\n"
        "\r\n"
        "Team,\r\n"
        "\r\n"
        "Great news! We've hit the Phase 2 milestone ahead of schedule.\r\n"
        "\r\n"
        "Key achievements:\r\n"
        "- API integration complete\r\n"
        "- Performance targets met (sub-100ms p99)\r\n"
        "- Security audit passed\r\n"
        "\r\n"
        "Next sprint starts Monday.\r\n"
        "\r\n"
        "Carol\r\n"
        f"--{boundary}\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        "Content-Transfer-Encoding: 7bit\r\n"
        "\r\n"
        "<html><body>\r\n"
        "<h1>Phase 2 Milestone Achieved!</h1>\r\n"
        "<p>Team,</p>\r\n"
        "<p>Great news! We've hit the <strong>Phase 2 milestone</strong> ahead of schedule.</p>\r\n"
        "<h2>Key achievements:</h2>\r\n"
        "<ul>\r\n"
        "<li>API integration complete</li>\r\n"
        "<li>Performance targets met (sub-100ms p99)</li>\r\n"
        "<li>Security audit passed</li>\r\n"
        "</ul>\r\n"
        "<p>Next sprint starts Monday.</p>\r\n"
        "<p>Carol</p>\r\n"
        "</body></html>\r\n"
        f"--{boundary}--\r\n"
    )
    (OUTPUT_DIR / "challenge_multipart_alt.eml").write_text(eml, newline="")
    print("  Created challenge_multipart_alt.eml")


def create_challenge_multipart_mixed_eml():
    """Email with multipart/mixed (body + attachments).

    Tests: RFC 2046 §5.1.3 (multipart/mixed)
    Expected: Body text extracted, attachment metadata preserved.
    """
    boundary = "----=_Part_002_mixed"
    # Simulated small CSV attachment
    csv_content = "Name,Revenue,Target\r\nQ1,125000,110000\r\nQ2,143000,130000\r\n"
    csv_b64 = base64.b64encode(csv_content.encode()).decode()

    eml = (
        "From: Dave Wilson <dave@example.com>\r\n"
        "To: finance@example.com\r\n"
        "Subject: Q1 Revenue Report with Attachment\r\n"
        "Date: Thu, 18 Mar 2026 08:45:00 -0700\r\n"
        "Message-ID: <mixed004@example.com>\r\n"
        "MIME-Version: 1.0\r\n"
        f"Content-Type: multipart/mixed;\r\n"
        f" boundary=\"{boundary}\"\r\n"
        "\r\n"
        f"--{boundary}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "Hi Finance team,\r\n"
        "\r\n"
        "Please find the Q1 revenue report attached.\r\n"
        "\r\n"
        "Summary: Total revenue was $268,000 against a target of $240,000.\r\n"
        "\r\n"
        "Dave\r\n"
        f"--{boundary}\r\n"
        "Content-Type: text/csv; name=\"revenue_q1.csv\"\r\n"
        "Content-Disposition: attachment; filename=\"revenue_q1.csv\"\r\n"
        "Content-Transfer-Encoding: base64\r\n"
        "\r\n"
        f"{csv_b64}\r\n"
        f"--{boundary}--\r\n"
    )
    (OUTPUT_DIR / "challenge_multipart_mixed.eml").write_text(eml, newline="")
    print("  Created challenge_multipart_mixed.eml")


def create_challenge_base64_body_eml():
    """Email with base64-encoded body.

    Tests: RFC 2045 §6.8 (base64 Content-Transfer-Encoding)
    Expected: Body decoded from base64 to readable text.
    """
    body_text = (
        "This is a base64-encoded email body.\r\n"
        "\r\n"
        "It contains important project updates:\r\n"
        "- Database migration completed successfully\r\n"
        "- New API endpoints deployed to staging\r\n"
        "- Load testing results show 5x improvement\r\n"
        "\r\n"
        "Please review and confirm.\r\n"
    )
    body_b64 = base64.b64encode(body_text.encode()).decode()
    # Wrap at 76 chars per RFC 2045
    wrapped = "\r\n".join(body_b64[i:i+76] for i in range(0, len(body_b64), 76))

    eml = (
        "From: Eve Thompson <eve@example.com>\r\n"
        "To: ops@example.com\r\n"
        "Subject: Deployment Update — Base64 Encoded\r\n"
        "Date: Fri, 19 Mar 2026 16:00:00 +0000\r\n"
        "Message-ID: <b64body005@example.com>\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "Content-Transfer-Encoding: base64\r\n"
        "\r\n"
        f"{wrapped}\r\n"
    )
    (OUTPUT_DIR / "challenge_base64_body.eml").write_text(eml, newline="")
    print("  Created challenge_base64_body.eml")


def create_challenge_qp_body_eml():
    """Email with quoted-printable encoded body.

    Tests: RFC 2045 §6.7 (quoted-printable Content-Transfer-Encoding)
    Expected: =XX hex escapes and soft line breaks decoded.
    """
    # Contains non-ASCII chars and long lines that need QP encoding
    body_text = (
        "Très bien! The café résumé has been approved.\r\n"
        "\r\n"
        "The naïve approach won't work — we need a more sophisticated strategy "
        "that accounts for the über-complex requirements of the Zürich office.\r\n"
        "\r\n"
        "Price: €1,500 (£1,250)\r\n"
    )
    qp_encoded = quopri.encodestring(body_text.encode("utf-8")).decode("ascii")

    eml = (
        "From: François Müller <francois@example.com>\r\n"
        "To: team@example.com\r\n"
        "Subject: =?utf-8?Q?R=C3=A9sum=C3=A9_Review_=E2=80=94_Caf=C3=A9_Meeting?=\r\n"
        "Date: Sat, 20 Mar 2026 10:30:00 +0100\r\n"
        "Message-ID: <qp006@example.com>\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "Content-Transfer-Encoding: quoted-printable\r\n"
        "\r\n"
        f"{qp_encoded}"
    )
    (OUTPUT_DIR / "challenge_qp_body.eml").write_text(eml, newline="")
    print("  Created challenge_qp_body.eml")


def create_challenge_encoded_headers_eml():
    """Email with RFC 2047 encoded-word headers.

    Tests: RFC 2047 §2 (encoded-words in headers)
    Expected: =?charset?B?...?= and =?charset?Q?...?= decoded in Subject/From.
    """
    # Base64-encoded Japanese subject
    subject_text = "会議の議事録"  # "Meeting minutes"
    subject_b64 = base64.b64encode(subject_text.encode("utf-8")).decode()

    # Q-encoded From name with accents
    from_name = "José García"
    from_q = "=?utf-8?Q?Jos=C3=A9_Garc=C3=ADa?="

    eml = (
        f"From: {from_q} <jose@example.com>\r\n"
        "To: team@example.com\r\n"
        f"Subject: =?utf-8?B?{subject_b64}?=\r\n"
        "Date: Sun, 21 Mar 2026 08:00:00 +0900\r\n"
        "Message-ID: <enc007@example.com>\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "Please find the meeting minutes below.\r\n"
        "\r\n"
        "Agenda:\r\n"
        "1. Project status update\r\n"
        "2. Budget review\r\n"
        "3. Next steps\r\n"
    )
    (OUTPUT_DIR / "challenge_encoded_headers.eml").write_text(eml, newline="")
    print("  Created challenge_encoded_headers.eml")


def create_challenge_mbox():
    """MBOX file with multiple email messages.

    Tests: RFC 4155 (MBOX format)
    Expected: Individual messages separated by "From " lines; each parsed independently.
    """
    msg1 = (
        "From alice@example.com Mon Mar 15 09:30:00 2026\r\n"
        "From: Alice <alice@example.com>\r\n"
        "To: team@example.com\r\n"
        "Subject: Sprint Planning\r\n"
        "Date: Mon, 15 Mar 2026 09:30:00 +0000\r\n"
        "Message-ID: <mbox-msg1@example.com>\r\n"
        "\r\n"
        "Let's plan the next sprint. Key items:\r\n"
        "- User auth refactor\r\n"
        "- Dashboard performance\r\n"
        "- API rate limiting\r\n"
        "\r\n"
    )
    msg2 = (
        "From bob@example.com Mon Mar 15 10:15:00 2026\r\n"
        "From: Bob <bob@example.com>\r\n"
        "To: team@example.com\r\n"
        "Subject: Re: Sprint Planning\r\n"
        "Date: Mon, 15 Mar 2026 10:15:00 +0000\r\n"
        "Message-ID: <mbox-msg2@example.com>\r\n"
        "In-Reply-To: <mbox-msg1@example.com>\r\n"
        "\r\n"
        "I can take the auth refactor. Should be 3 story points.\r\n"
        "\r\n"
    )
    msg3 = (
        "From carol@example.com Mon Mar 15 11:00:00 2026\r\n"
        "From: Carol <carol@example.com>\r\n"
        "To: team@example.com\r\n"
        "Subject: Re: Sprint Planning\r\n"
        "Date: Mon, 15 Mar 2026 11:00:00 +0000\r\n"
        "Message-ID: <mbox-msg3@example.com>\r\n"
        "In-Reply-To: <mbox-msg1@example.com>\r\n"
        "\r\n"
        "I'll handle the dashboard performance tickets.\r\n"
        "Already profiled — main bottleneck is the chart rendering.\r\n"
        "\r\n"
    )
    mbox = msg1 + msg2 + msg3
    (OUTPUT_DIR / "challenge_mbox.mbox").write_text(mbox, newline="")
    print("  Created challenge_mbox.mbox")


def create_challenge_attachment_chain_eml():
    """Email with multiple parseable attachments (CSV, HTML) and one binary (PNG).

    Tests: Attachment chain parsing — text-based attachments decoded and parsed inline.
    Expected: CSV → TableBlock, HTML → parsed blocks, PNG → placeholder.
    """
    boundary = "----=_Part_010_attachchain"

    csv_content = "Region,Revenue,Target\r\nEMEA,125000,110000\r\nAPAC,143000,130000\r\nAmericas,198000,180000\r\n"
    csv_b64 = base64.b64encode(csv_content.encode()).decode()

    html_content = "<html><body><h1>Weekly Summary</h1><p>All targets met this quarter.</p><ul><li>EMEA on track</li><li>APAC exceeded</li></ul></body></html>"
    html_b64 = base64.b64encode(html_content.encode()).decode()

    # Fake PNG (just a small binary blob — not a real image)
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    png_b64 = base64.b64encode(png_bytes).decode()

    eml = (
        "From: Reports Bot <reports@example.com>\r\n"
        "To: team@example.com\r\n"
        "Subject: Q1 Regional Report with Attachments\r\n"
        "Date: Mon, 01 Apr 2026 09:00:00 +0000\r\n"
        "Message-ID: <attachchain010@example.com>\r\n"
        "MIME-Version: 1.0\r\n"
        f"Content-Type: multipart/mixed;\r\n"
        f" boundary=\"{boundary}\"\r\n"
        "\r\n"
        f"--{boundary}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "Hi team,\r\n"
        "\r\n"
        "Please find the Q1 regional reports attached.\r\n"
        "\r\n"
        "Best,\r\n"
        "Reports Bot\r\n"
        f"--{boundary}\r\n"
        "Content-Type: text/csv; name=\"revenue_q1.csv\"\r\n"
        "Content-Disposition: attachment; filename=\"revenue_q1.csv\"\r\n"
        "Content-Transfer-Encoding: base64\r\n"
        "\r\n"
        f"{csv_b64}\r\n"
        f"--{boundary}\r\n"
        "Content-Type: text/html; name=\"summary.html\"\r\n"
        "Content-Disposition: attachment; filename=\"summary.html\"\r\n"
        "Content-Transfer-Encoding: base64\r\n"
        "\r\n"
        f"{html_b64}\r\n"
        f"--{boundary}\r\n"
        "Content-Type: image/png; name=\"chart.png\"\r\n"
        "Content-Disposition: attachment; filename=\"chart.png\"\r\n"
        "Content-Transfer-Encoding: base64\r\n"
        "\r\n"
        f"{png_b64}\r\n"
        f"--{boundary}--\r\n"
    )
    (OUTPUT_DIR / "challenge_attachment_chain.eml").write_text(eml, newline="")
    print("  Created challenge_attachment_chain.eml")


def create_challenge_email_in_email_eml():
    """Email with a message/rfc822 attachment (forwarded email).

    Tests: Recursive email parsing — nested email parsed as SectionBlock.
    Expected: Outer email headers + body, inner email parsed recursively.
    """
    boundary = "----=_Part_011_emailinemail"

    inner_eml = (
        "From: Original Sender <original@example.com>\r\n"
        "To: First Recipient <first@example.com>\r\n"
        "Subject: Original Important Message\r\n"
        "Date: Sun, 30 Mar 2026 08:00:00 +0000\r\n"
        "Message-ID: <original011@example.com>\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "This is the original message that was forwarded.\r\n"
        "It contains important project decisions:\r\n"
        "- Deadline moved to April 15\r\n"
        "- Budget increased by 20%\r\n"
    )
    inner_b64 = base64.b64encode(inner_eml.encode()).decode()

    eml = (
        "From: Forwarder <forwarder@example.com>\r\n"
        "To: team@example.com\r\n"
        "Subject: Fwd: Original Important Message\r\n"
        "Date: Mon, 01 Apr 2026 10:00:00 +0000\r\n"
        "Message-ID: <fwd011@example.com>\r\n"
        "MIME-Version: 1.0\r\n"
        f"Content-Type: multipart/mixed;\r\n"
        f" boundary=\"{boundary}\"\r\n"
        "\r\n"
        f"--{boundary}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "FYI — forwarding this for visibility.\r\n"
        f"--{boundary}\r\n"
        "Content-Type: message/rfc822\r\n"
        "Content-Disposition: attachment; filename=\"forwarded.eml\"\r\n"
        "Content-Transfer-Encoding: base64\r\n"
        "\r\n"
        f"{inner_b64}\r\n"
        f"--{boundary}--\r\n"
    )
    (OUTPUT_DIR / "challenge_email_in_email.eml").write_text(eml, newline="")
    print("  Created challenge_email_in_email.eml")


def create_challenge_threaded_mbox():
    """MBOX with 5 messages forming 2 threads (3+2), interleaved chronologically.

    Tests: Thread reconstruction via Message-ID / In-Reply-To / References.
    Expected: 2 thread groups with correct participants and message ordering.
    """
    # Thread 1: Budget discussion (3 messages)
    msg1 = (
        "From alice@example.com Mon Mar 30 09:00:00 2026\r\n"
        "From: Alice <alice@example.com>\r\n"
        "To: team@example.com\r\n"
        "Subject: Q2 Budget Planning\r\n"
        "Date: Mon, 30 Mar 2026 09:00:00 +0000\r\n"
        "Message-ID: <thread1-msg1@example.com>\r\n"
        "\r\n"
        "Team, let's start planning the Q2 budget.\r\n"
        "Key areas: engineering, marketing, ops.\r\n"
        "\r\n"
    )

    # Thread 2: Launch planning (2 messages) — interleaved
    msg2 = (
        "From dave@example.com Mon Mar 30 09:30:00 2026\r\n"
        "From: Dave <dave@example.com>\r\n"
        "To: team@example.com\r\n"
        "Subject: Product Launch Timeline\r\n"
        "Date: Mon, 30 Mar 2026 09:30:00 +0000\r\n"
        "Message-ID: <thread2-msg1@example.com>\r\n"
        "\r\n"
        "Here's the proposed launch timeline for v2.0.\r\n"
        "Target date: May 15.\r\n"
        "\r\n"
    )

    # Thread 1: Reply from Bob
    msg3 = (
        "From bob@example.com Mon Mar 30 10:00:00 2026\r\n"
        "From: Bob <bob@example.com>\r\n"
        "To: team@example.com\r\n"
        "Subject: Re: Q2 Budget Planning\r\n"
        "Date: Mon, 30 Mar 2026 10:00:00 +0000\r\n"
        "Message-ID: <thread1-msg2@example.com>\r\n"
        "In-Reply-To: <thread1-msg1@example.com>\r\n"
        "References: <thread1-msg1@example.com>\r\n"
        "\r\n"
        "I think we should increase engineering budget by 15%.\r\n"
        "The new hires need equipment and training.\r\n"
        "\r\n"
    )

    # Thread 2: Reply from Eve
    msg4 = (
        "From eve@example.com Mon Mar 30 10:30:00 2026\r\n"
        "From: Eve <eve@example.com>\r\n"
        "To: team@example.com\r\n"
        "Subject: Re: Product Launch Timeline\r\n"
        "Date: Mon, 30 Mar 2026 10:30:00 +0000\r\n"
        "Message-ID: <thread2-msg2@example.com>\r\n"
        "In-Reply-To: <thread2-msg1@example.com>\r\n"
        "References: <thread2-msg1@example.com>\r\n"
        "\r\n"
        "May 15 works. Marketing materials will be ready by May 1.\r\n"
        "\r\n"
    )

    # Thread 1: Reply from Carol
    msg5 = (
        "From carol@example.com Mon Mar 30 11:00:00 2026\r\n"
        "From: Carol <carol@example.com>\r\n"
        "To: team@example.com\r\n"
        "Subject: Re: Q2 Budget Planning\r\n"
        "Date: Mon, 30 Mar 2026 11:00:00 +0000\r\n"
        "Message-ID: <thread1-msg3@example.com>\r\n"
        "In-Reply-To: <thread1-msg2@example.com>\r\n"
        "References: <thread1-msg1@example.com> <thread1-msg2@example.com>\r\n"
        "\r\n"
        "Agreed on engineering. Marketing should stay flat.\r\n"
        "\r\n"
    )

    mbox = msg1 + msg2 + msg3 + msg4 + msg5
    (OUTPUT_DIR / "challenge_threaded.mbox").write_text(mbox, newline="")
    print("  Created challenge_threaded.mbox")


def create_minimal_docx():
    """Create a minimal valid DOCX (ZIP with word/document.xml) in memory.
    Returns base64-encoded bytes.
    """
    content_types = '<?xml version="1.0" encoding="UTF-8"?>\r\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'

    rels = '<?xml version="1.0" encoding="UTF-8"?>\r\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'

    document = '<?xml version="1.0" encoding="UTF-8"?>\r\n<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Q1 Revenue Analysis</w:t></w:r></w:p><w:p><w:r><w:t>Total revenue: $425,000 across three regions.</w:t></w:r></w:p><w:tbl><w:tblGrid><w:gridCol/><w:gridCol/></w:tblGrid><w:tr><w:tc><w:p><w:r><w:t>Region</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Revenue</w:t></w:r></w:p></w:tc></w:tr><w:tr><w:tc><w:p><w:r><w:t>EMEA</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>$125,000</w:t></w:r></w:p></w:tc></w:tr><w:tr><w:tc><w:p><w:r><w:t>APAC</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>$143,000</w:t></w:r></w:p></w:tc></w:tr><w:tr><w:tc><w:p><w:r><w:t>Americas</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>$157,000</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>'

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', content_types)
        zf.writestr('_rels/.rels', rels)
        zf.writestr('word/document.xml', document)

    return base64.b64encode(buf.getvalue()).decode()


def create_challenge_docx_attachment_eml():
    """Email with a DOCX attachment (Office ZIP format).

    Tests: Two-pass Office attachment parsing via --deep flag.
    Expected: Without --deep: attachment-data preserved. With --deep: DOCX parsed to blocks.
    """
    boundary = "----=_Part_013_docxattach"
    docx_b64 = create_minimal_docx()

    # Wrap at 76 chars per RFC 2045
    wrapped = "\r\n".join(docx_b64[i:i+76] for i in range(0, len(docx_b64), 76))

    eml = (
        "From: Reports <reports@example.com>\r\n"
        "To: team@example.com\r\n"
        "Subject: Q1 Revenue Report with DOCX\r\n"
        "Date: Wed, 02 Apr 2026 09:00:00 +0000\r\n"
        "Message-ID: <docxattach013@example.com>\r\n"
        "MIME-Version: 1.0\r\n"
        f"Content-Type: multipart/mixed;\r\n"
        f" boundary=\"{boundary}\"\r\n"
        "\r\n"
        f"--{boundary}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "Hi team,\r\n"
        "\r\n"
        "Please find the Q1 revenue analysis attached as a Word document.\r\n"
        "\r\n"
        "Best,\r\n"
        "Reports\r\n"
        f"--{boundary}\r\n"
        "Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document;\r\n"
        " name=\"q1_revenue.docx\"\r\n"
        "Content-Disposition: attachment; filename=\"q1_revenue.docx\"\r\n"
        "Content-Transfer-Encoding: base64\r\n"
        "\r\n"
        f"{wrapped}\r\n"
        f"--{boundary}--\r\n"
    )
    (OUTPUT_DIR / "challenge_docx_attachment.eml").write_text(eml, newline="")
    print("  Created challenge_docx_attachment.eml")


def create_challenge_quoted_reply_eml():
    """Reply email with quoted text and attribution line.

    Tests: Quote stripping — removal of '> ' prefixed lines and 'On DATE, PERSON wrote:'.
    Expected: Only the new reply content remains after stripping.
    """
    eml = (
        "From: Bob <bob@example.com>\r\n"
        "To: Alice <alice@example.com>\r\n"
        "Subject: Re: Q1 Budget Review Meeting\r\n"
        "Date: Tue, 16 Mar 2026 08:00:00 -0500\r\n"
        "Message-ID: <reply012@example.com>\r\n"
        "In-Reply-To: <msg001@example.com>\r\n"
        "References: <msg001@example.com>\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "Thursday at 2pm works for me. I'll prepare the Q2 projections.\r\n"
        "\r\n"
        "On Mon, 15 Mar 2026 at 09:30, Alice Smith <alice@example.com> wrote:\r\n"
        "> Hi Bob,\r\n"
        ">\r\n"
        "> I wanted to follow up on our Q1 budget review. The key points are:\r\n"
        ">\r\n"
        "> 1. Revenue exceeded projections by 12%\r\n"
        "> 2. Marketing spend was under budget by $15,000\r\n"
        "> 3. Engineering headcount increased by 3 FTEs\r\n"
        ">\r\n"
        "> Can we schedule a meeting for Thursday at 2pm to discuss next steps?\r\n"
        ">\r\n"
        "> Best regards,\r\n"
        "> Alice\r\n"
    )
    (OUTPUT_DIR / "challenge_quoted_reply.eml").write_text(eml, newline="")
    print("  Created challenge_quoted_reply.eml")


if __name__ == "__main__":
    print("Generating email challenge files...")
    create_challenge_basic_eml()
    create_challenge_folded_headers_eml()
    create_challenge_multipart_alt_eml()
    create_challenge_multipart_mixed_eml()
    create_challenge_base64_body_eml()
    create_challenge_qp_body_eml()
    create_challenge_encoded_headers_eml()
    create_challenge_mbox()
    create_challenge_attachment_chain_eml()
    create_challenge_email_in_email_eml()
    create_challenge_threaded_mbox()
    create_challenge_docx_attachment_eml()
    create_challenge_quoted_reply_eml()
    print(f"\nGenerated 13 challenge files in {OUTPUT_DIR}/")
