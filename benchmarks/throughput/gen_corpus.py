"""Build the throughput corpus: a mix shaped like an office archive.

Every word is drawn from a fixed list and every image is random noise, so the
corpus contains no real content and the files cannot be compressed below their
stated size. The seed is fixed: the same command gives the same mix.

  180 files, about 128 MB:
    60 memos    (Word, 2 pages, no images)                ~37 KB
    60 reports  (Word, 12 pages, tables, 2 images)        ~340 KB
    15 big docs (Word, 60 pages, tables, 6 images)        ~2.4 MB
    30 decks    (PowerPoint, 20 slides, notes, 8 images)  ~2.0 MB
    15 sheets   (Excel, 3 sheets x 1,500 rows)            ~200 KB

Usage: python3 gen_corpus.py OUTDIR   (needs python-docx, python-pptx, openpyxl, Pillow)
"""
import io
import os
import random
import sys

from docx import Document
from docx.shared import Inches
from openpyxl import Workbook
from PIL import Image
from pptx import Presentation
from pptx.util import Inches as PptxInches

random.seed(7)
WORDS = ("campaign client brief strategy brand audience launch budget timeline review "
         "deliverable stakeholder workshop proposal insight channel content digital "
         "platform report quarter results performance design concept approval").split()


def para(n):
    return " ".join(random.choice(WORDS) for _ in range(n)).capitalize() + "."


def noise_png(kb):
    side = int((kb * 1024 / 3) ** 0.5)
    img = Image.frombytes("RGB", (side, side), random.randbytes(side * side * 3))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf


def make_docx(path, pages, images, img_kb):
    doc = Document()
    for p in range(pages):
        doc.add_heading(para(4), level=1 + (p % 2))
        for _ in range(5):
            doc.add_paragraph(para(60))
        if p % 3 == 0:
            table = doc.add_table(rows=6, cols=4)
            for row in table.rows:
                for cell in row.cells:
                    cell.text = para(3)
        for _ in range(4):
            doc.add_paragraph(para(8), style="List Bullet")
    for _ in range(images):
        doc.add_picture(noise_png(img_kb), width=Inches(4))
    doc.save(path)


def make_pptx(path, slides, images, img_kb):
    deck = Presentation()
    for s in range(slides):
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = para(4)
        slide.placeholders[1].text = "\n".join(para(10) for _ in range(4))
        slide.notes_slide.notes_text_frame.text = para(30)
        if s < images:
            slide.shapes.add_picture(noise_png(img_kb), PptxInches(5), PptxInches(4), width=PptxInches(3))
    deck.save(path)


def make_xlsx(path, rows):
    wb = Workbook()
    for sheet in range(3):
        ws = wb.active if sheet == 0 else wb.create_sheet()
        for _ in range(rows):
            ws.append([para(2), random.randint(0, 10**6), random.random() * 1000, para(5)])
    wb.save(path)


def main(out):
    os.makedirs(out, exist_ok=True)
    specs = []
    specs += [(make_docx, f"memo_{i}.docx", dict(pages=2, images=0, img_kb=0)) for i in range(60)]
    specs += [(make_docx, f"report_{i}.docx", dict(pages=12, images=2, img_kb=150)) for i in range(60)]
    specs += [(make_docx, f"big_{i}.docx", dict(pages=60, images=6, img_kb=400)) for i in range(15)]
    specs += [(make_pptx, f"deck_{i}.pptx", dict(slides=20, images=8, img_kb=250)) for i in range(30)]
    specs += [(make_xlsx, f"sheet_{i}.xlsx", dict(rows=1500)) for i in range(15)]
    for make, name, kwargs in specs:
        make(os.path.join(out, name), **kwargs)
    total = sum(os.path.getsize(os.path.join(out, f)) for f in os.listdir(out))
    print(f"{len(specs)} files, {total / 1e6:.1f} MB")


if __name__ == "__main__":
    main(sys.argv[1])
