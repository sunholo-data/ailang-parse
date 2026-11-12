"""Write data/test_files/challenge/challenge_pdf_highlights_in_objstm.pdf.

The same invented one-page contract and two highlights as
challenge_pdf_highlights.pdf, saved the way Word, LaTeX and Acrobat's "reduce
file size" save a PDF: the catalog, page tree, page and BOTH annotations are
packed into a compressed object stream, and the cross-reference data is a
compressed stream with a PNG predictor. Nothing about the annotations is
visible to a scan of the raw bytes.

Deterministic: running it again writes the same bytes.

    python3 benchmarks/pdf/make_objstm_annotation_fixture.py
"""

from __future__ import annotations

import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent.parent / "data/test_files/challenge/challenge_pdf_highlights_in_objstm.pdf"

CONTENT = (b"BT /F1 12 Tf 72 700 Td (The Seller shall indemnify the Buyer against all claims.) Tj ET\n"
           b"BT /F1 12 Tf 72 670 Td (Payment terms are net thirty days from the invoice date.) Tj ET\n"
           b"BT /F1 12 Tf 72 640 Td (This agreement renews automatically unless cancelled.) Tj ET\n")

# Objects that go inside the object stream, by number.
PACKED = {
    1: b"<< /Type /Catalog /Pages 2 0 R >>",
    2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 /MediaBox [0 0 612 792] >>",
    3: b"<< /Type /Page /Parent 2 0 R /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> /Annots [6 0 R 7 0 R] >>",
    5: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    6: (b"<< /Type /Annot /Subtype /Highlight /Rect [130.02 697.52 209.38 708.62] "
        b"/QuadPoints [130.02 708.62 209.38 708.62 130.02 697.52 209.38 697.52] "
        b"/Contents (This indemnity is far too broad.) /T (Laura) /M (D:20260806100000Z) /C [1 1 0] /P 3 0 R >>"),
    7: (b"<< /Type /Annot /Subtype /Highlight /Rect [176.70 667.52 251.40 678.62] "
        b"/QuadPoints [176.70 678.62 251.40 678.62 176.70 667.52 251.40 667.52] "
        b"/Contents (Thirty days is not what we agreed.) /T (Miguel) /M (D:20260806100000Z) /C [1 1 0] /P 3 0 R >>"),
}
STM_NUM, XREF_NUM, CONTENT_NUM = 8, 9, 4


def png_up(rows: list[bytes]) -> bytes:
    """PNG 'Up' filter (type 2), as cross-reference streams are usually saved."""
    out, prev = b"", bytes(len(rows[0]))
    for row in rows:
        out += b"\x02" + bytes((a - b) % 256 for a, b in zip(row, prev))
        prev = row
    return out


def main() -> None:
    nums = sorted(PACKED)
    bodies, header, pos = b"", b"", 0
    for n in nums:
        header += b"%d %d " % (n, pos)
        bodies += PACKED[n] + b"\n"
        pos += len(PACKED[n]) + 1
    stm_plain = header + bodies
    stm = zlib.compress(stm_plain, 9)

    pdf = b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n"
    off_content = len(pdf)
    pdf += b"%d 0 obj\n<< /Length %d >>\nstream\n" % (CONTENT_NUM, len(CONTENT)) + CONTENT + b"endstream\nendobj\n"
    off_stm = len(pdf)
    pdf += (b"%d 0 obj\n<< /Type /ObjStm /N %d /First %d /Filter /FlateDecode /Length %d >>\nstream\n"
            % (STM_NUM, len(nums), len(header), len(stm))) + stm + b"\nendstream\nendobj\n"
    off_xref = len(pdf)

    def row(kind: int, a: int, b: int) -> bytes:
        return bytes([kind]) + a.to_bytes(3, "big") + bytes([b])

    rows = [row(0, 0, 255)]
    for n in range(1, XREF_NUM + 1):
        if n in PACKED:
            rows.append(row(2, STM_NUM, nums.index(n)))
        elif n == CONTENT_NUM:
            rows.append(row(1, off_content, 0))
        elif n == STM_NUM:
            rows.append(row(1, off_stm, 0))
        else:
            rows.append(row(1, off_xref, 0))
    xref = zlib.compress(png_up(rows), 9)
    pdf += (b"%d 0 obj\n<< /Type /XRef /Size %d /W [1 3 1] /Root 1 0 R /Filter /FlateDecode "
            b"/DecodeParms << /Columns 5 /Predictor 12 >> /Length %d >>\nstream\n"
            % (XREF_NUM, XREF_NUM + 1, len(xref))) + xref + b"\nendstream\nendobj\n"
    pdf += b"startxref\n%d\n%%%%EOF\n" % off_xref
    OUT.write_bytes(pdf)
    print(f"wrote {OUT} ({len(pdf)} bytes)")


if __name__ == "__main__":
    main()
