"""Synthetic PDFs for the text-layer audit (pdf_text_layer_sparse).

Stdlib only: a minimal PDF writer, so the fixtures can be built anywhere the
checks run (CI, a fresh clone) without fpdf2 or Pillow, and nothing has to be
committed. All text is invented; no page here comes from a real document.

The shapes, each modelled on what the audit has to tell apart:

  scanned        every page is a picture of a page plus an identical stamp
                 line laid over it (the 2026-11-02 incident shape)
  scanned_blank  every page is a picture of a page, no text at all
  partial        four real text pages, then two scanned pages with a stamp
  slides         a slide deck: little text per page, but different on every
                 page, a repeated footer, one full-bleed background picture
  forms          four identical text pages and no pictures (copies of a form)

    python3 benchmarks/pdf/text_layer_fixtures.py OUT_DIR
"""

from __future__ import annotations

import sys
import zlib
from pathlib import Path

LETTER = (612.0, 792.0)
SLIDE = (792.0, 612.0)

STAMP = ("RECEIVED BY THE MUNICIPAL ARCHIVE OF NORTHWOOD - CERTIFIED TRUE COPY "
         "- FILE NO. 2031-554210 - THIS STAMP IS NOT PART OF THE DOCUMENT")


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _scan_pixels(w: int, h: int, seed: int) -> bytes:
    """Greyscale 'scan': white paper with rows of dark blobs where lines of
    text would be. Patterned so it compresses to a few KB."""
    out = bytearray()
    for y in range(h):
        row = bytearray(b"\xff" * w)
        if (y // 6) % 3 != 2 and 30 < y < h - 40:
            for x in range(30, w - 30):
                if ((x + seed * 7 + (y // 18) * 13) // 5) % 4 != 3:
                    row[x] = 0x30
        out += row
    return bytes(out)


class _Pdf:
    def __init__(self) -> None:
        self.objects: list[bytes] = []

    def add(self, body: bytes) -> int:
        self.objects.append(body)
        return len(self.objects)

    def stream(self, dict_body: str, data: bytes) -> int:
        return self.add(f"<< {dict_body} /Length {len(data)} >>\nstream\n".encode() + data + b"\nendstream")

    def write(self, root: int) -> bytes:
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for i, body in enumerate(self.objects, 1):
            offsets.append(len(out))
            out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(self.objects) + 1}\n0000000000 65535 f \n".encode()
        for off in offsets:
            out += f"{off:010d} 00000 n \n".encode()
        out += f"trailer\n<< /Size {len(self.objects) + 1} /Root {root} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
        return bytes(out)


def build_pdf(pages: list[dict]) -> bytes:
    """pages: [{size: (w, h), image: (x, y, w, h) | None, lines: [(x, y, pt, text)]}]."""
    pdf = _Pdf()
    font = pdf.add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    kids = []
    pending = []
    for n, page in enumerate(pages, 1):
        w, h = page["size"]
        ops = []
        xobj = ""
        if page.get("image"):
            ix, iy, iw, ih = page["image"]
            px_w, px_h = max(8, int(iw * 100 / 72)), max(8, int(ih * 100 / 72))  # 100 ppi
            img = pdf.stream(f"/Type /XObject /Subtype /Image /Width {px_w} /Height {px_h} "
                             f"/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode",
                             zlib.compress(_scan_pixels(px_w, px_h, n), 9))
            xobj = f"/XObject << /Im{n} {img} 0 R >>"
            ops.append(f"q {iw:.2f} 0 0 {ih:.2f} {ix:.2f} {iy:.2f} cm /Im{n} Do Q")
        for x, y, pt, text in page.get("lines", []):
            ops.append(f"BT /F1 {pt} Tf {x:.2f} {y:.2f} Td ({_esc(text)}) Tj ET")
        content = pdf.stream("", "\n".join(ops).encode("latin-1"))
        pending.append((w, h, content, xobj))
    pages_id = len(pdf.objects) + len(pending) + 1
    for w, h, content, xobj in pending:
        kids.append(pdf.add(f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {w:.0f} {h:.0f}] "
                            f"/Resources << /Font << /F1 {font} 0 R >> {xobj} >> /Contents {content} 0 R >>".encode()))
    assert pdf.add(f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>".encode()) == pages_id
    root = pdf.add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())
    return pdf.write(root)


# ---------------------------------------------------------------------------
# The fixtures
# ---------------------------------------------------------------------------

_PROSE = [
    "The survey of the eastern parcel was completed in early spring by the county team.",
    "Boundary markers along the river bank were found intact and photographed in place.",
    "A drainage easement runs beneath the northern hedge and must remain accessible.",
    "The previous owner installed a timber outbuilding without recorded permission.",
    "Access to the lane is shared with two neighbouring cottages under an old covenant.",
    "Soil samples showed no contamination near the former orchard or the well head.",
    "Rights of way across the meadow are walked weekly by a local rambling society.",
    "The roof of the main barn needs replacing within the next five winters at most.",
]


def _scan_page(n: int, total: int, stamp: bool = True) -> dict:
    lines = [(36, 24, 7, STAMP), (500, 770, 9, f"Page {n} of {total}")] if stamp else []
    return {"size": LETTER, "image": (0, 0, *LETTER), "lines": lines}


def _text_page(n: int, total: int) -> dict:
    body = [(72, 700 - 18 * i, 11, f"{_PROSE[(n + i) % len(_PROSE)]} Section {n}.{i}.")
            for i in range(10)]
    return {"size": LETTER, "image": None,
            "lines": [(72, 740, 16, f"Chapter {n}: parcel review notes")] + body
                     + [(500, 770, 9, f"Page {n} of {total}")]}


_SLIDES = [
    ("Quarterly roadmap", ["Ship the field app", "Retire the fax intake"]),
    ("Why now", ["Paper backlog doubled", "Two clerks retiring"]),
    ("Pilot results", ["41% faster filing", "Zero lost forms"]),
    ("Risks", ["Vendor lock-in", "Training time"]),
    ("Budget", ["Year one: 120k", "Year two: 45k"]),
    ("Timeline", ["Spring: pilot", "Autumn: rollout"]),
    ("Team", ["Ops lead: Rivera", "Engineering: Okafor"]),
    ("Questions", ["Thank you"]),
]


def _slide_page(n: int, title: str, bullets: list[str], background: bool) -> dict:
    lines = [(60, 520, 32, title)] + [(80, 440 - 40 * i, 20, f"- {b}") for i, b in enumerate(bullets)]
    lines.append((60, 30, 9, f"Northwood Archive - internal - {n}"))
    return {"size": SLIDE, "image": (0, 0, *SLIDE) if background else (650, 480, 100, 100), "lines": lines}


_FORM = [
    "APPLICATION FOR A PARKING PERMIT",
    "Applicant name: ________________________________",
    "Address: _______________________________________",
    "Vehicle registration: __________________________",
    "I declare that the information given is correct.",
    "Signature: ________________   Date: ____________",
]


def fixtures() -> dict[str, bytes]:
    scanned = [_scan_page(n, 6) for n in range(1, 7)]
    blank = [_scan_page(n, 4, stamp=False) for n in range(1, 5)]
    partial = [_text_page(n, 6) for n in range(1, 5)] + [_scan_page(n, 6) for n in (5, 6)]
    slides = [_slide_page(n, t, b, background=(n == 3)) for n, (t, b) in enumerate(_SLIDES, 1)]
    forms = [{"size": LETTER, "image": None,
              "lines": [(72, 720 - 30 * i, 12, t) for i, t in enumerate(_FORM)]} for _ in range(4)]
    return {
        "scanned.pdf": build_pdf(scanned),
        "scanned_blank.pdf": build_pdf(blank),
        "partial.pdf": build_pdf(partial),
        "slides.pdf": build_pdf(slides),
        "forms.pdf": build_pdf(forms),
    }


def write_fixtures(out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, data in fixtures().items():
        p = out_dir / name
        p.write_bytes(data)
        paths[name] = p
    return paths


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: text_layer_fixtures.py OUT_DIR", file=sys.stderr)
        sys.exit(2)
    for name, path in write_fixtures(Path(sys.argv[1])).items():
        print(path)
