"""Source-derived worksheet hyperlink gate, shared with Chromium.

Non-URL labels, sheet-local relationship IDs, internal destinations, relative
URIs, blank cells, ranges, sparse source rows and bounded truncation. The
retained row mapping below is explicit fixture intent, not parser output.
"""
from __future__ import annotations

import argparse
from collections import Counter
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / 'benchmarks/fixtures/xlsx_hyperlinks.xlsx'
S = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
# Output rows -> source rows. Leading blanks are omitted; the long gap is a
# separator with no source coordinate. Hyperlinks must not expand that gap.
LAYOUT = [('Contacts', 1, [5, 6, 7, None, 400], 9), ('Other tab', 2, [9], 2)]


def coord(ref):
    match = re.fullmatch(r'([A-Z]+)([1-9][0-9]*)', ref)
    if not match:
        return None
    col = 0
    for char in match[1]:
        col = col * 26 + ord(char) - 64
    row = int(match[2])
    return (row, col) if row <= 1048576 and col <= 16384 else None


def rectangle(ref):
    parts = ref.split(':')
    a, b = coord(parts[0]), coord(parts[-1])
    return (a, b) if len(parts) <= 2 and a and b else None


def expectations():
    links = []
    with zipfile.ZipFile(SOURCE) as z:
        for name, part, rows, width in LAYOUT:
            sheet = ET.fromstring(z.read(f'xl/worksheets/sheet{part}.xml'))
            rels = {n.get('Id'): n for n in ET.fromstring(z.read(f'xl/worksheets/_rels/sheet{part}.xml.rels'))}
            texts = {coord(n.get('r')): ''.join(n.itertext()) if n.get('t') == 'inlineStr' else ''
                     for n in sheet.findall(f'{S}sheetData/{S}row/{S}c')}
            merged = [rectangle(n.get('ref')) for n in sheet.findall(f'{S}mergeCells/{S}mergeCell')]
            targets = {}
            for link in sheet.findall(f'{S}hyperlinks/{S}hyperlink'):
                area = rectangle(link.get('ref', ''))
                if not area:
                    continue
                rid, location = link.get(R + 'id'), link.get('location', '')
                rel = rels.get(rid)
                if rid:
                    if rel is None or not rel.get('Type', '').endswith('/hyperlink'):
                        continue
                    href = rel.get('Target', '')
                    if location:
                        href = href.split('#')[0] + '#' + location
                else:
                    href = '#' + location if location else ''
                for ri, source_row in enumerate(rows, 1):
                    for ci in range(1, width + 1):
                        if source_row is None or not href:
                            continue
                        point = (source_row, ci)
                        if not (area[0][0] <= source_row <= area[1][0] and area[0][1] <= ci <= area[1][1]):
                            continue
                        if any(a[0] <= source_row <= b[0] and a[1] <= ci <= b[1] and a != point
                               for a, b in merged):
                            continue
                        targets[(ri, ci)] = {'sheet': name, 'row': ri, 'col': ci,
                                             'text': texts.get(point, ''), 'href': href}
            links.extend(targets.values())
    return {'links': sorted(links, key=lambda x: (x['sheet'], x['row'], x['col'])),
            'shapes': [[name, len(rows), width] for name, _, rows, width in LAYOUT],
            'warnings': ['hyperlink F5 has no resolvable target',
                         'invalid cell reference: bad-ref', 'hyperlink D7:E7: kept 1 of 2',
                         'hyperlink B200: kept 0 of 1', 'hyperlink XFD1048576: kept 0 of 1',
                         '1 formula cell(s) have no cached value', 'rows 8-399 are empty']}


def actual(blocks):
    links, shapes = [], []
    for sheet in (b for b in blocks if b.get('kind') == 'sheet'):
        for table in (b for b in sheet['blocks'] if b['type'] == 'table'):
            rows = ([table['headers']] if table.get('headers') else []) + table['rows']
            shapes.append([sheet['name'], len(rows), max(map(len, rows), default=0)])
            for ri, row in enumerate(rows, 1):
                for ci, cell in enumerate(row, 1):
                    if isinstance(cell, dict):
                        for run in cell.get('runs', []):
                            if run.get('href'):
                                links.append({'sheet': sheet['name'], 'row': ri, 'col': ci,
                                              'text': run['text'], 'href': run['href']})
    return sorted(links, key=lambda x: (x['sheet'], x['row'], x['col'])), shapes


def parse(source, out, convert=False):
    cmd = [str(ROOT / 'bin/docparse'), str(source)]
    if convert:
        cmd += ['--convert', str(out / 'links.html')]
    run = subprocess.run(cmd, cwd=ROOT, env={**os.environ, 'DOCPARSE_OUTPUT_DIR': str(out), 'AILANG_NO_TRACE': '1'},
                         capture_output=True, text=True, timeout=120)
    if run.returncode:
        raise RuntimeError(run.stderr + run.stdout[-2000:])
    return json.loads((out / (source.name + '.json')).read_text())


class Anchors(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.links.extend(value for key, value in attrs if key == 'href')


def check(result):
    want = expectations()
    links, shapes = actual(result['document']['blocks'])
    assert links == want['links'], f'cell links differ: got {links}, expected {want["links"]}'
    assert shapes == want['shapes'], f'links changed retained shape: {shapes}'
    warnings = result['warnings']
    assert len(warnings) == len(want['warnings']), warnings
    for text in want['warnings']:
        assert any(text in warning for warning in warnings), (text, warnings)


def variant(out, sheet):
    file = out / 'bounds.xlsx'
    with zipfile.ZipFile(SOURCE) as src, zipfile.ZipFile(file, 'w', zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            dst.writestr(info, sheet.encode() if info.filename == 'xl/worksheets/sheet1.xml' else src.read(info.filename))
    return parse(file, out)


def check_bounds(out):
    # A full-sheet range is metadata; it must not materialise a huge grid.
    sheet = f'<worksheet xmlns="{S[1:-1]}"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>One</t></is></c></row></sheetData><hyperlinks><hyperlink ref="A1:XFD1048576" location="All"/></hyperlinks></worksheet>'
    doc = variant(out, sheet)
    links, shapes = actual(doc['document']['blocks'])
    assert shapes[0] == ['Contacts', 1, 1] and links[0]['href'] == '#All'
    assert any('kept 1 of 17179869184' in w for w in doc['warnings'])
    # Both metadata caps report omission, including the first record over it.
    for count, link, message in [
        (5001, '<hyperlink ref="invalid" location="Bad"/>', '5000-record limit'),
        (101, '<hyperlink ref="A1:B1" location="Range"/>', '100-range limit'),
    ]:
        doc = variant(out, sheet.replace('<hyperlink ref="A1:XFD1048576" location="All"/>', link * count))
        assert any(message in w for w in doc['warnings']), message
    # Row truncation must never reattach a discarded row's target to another.
    rows = ''.join(f'<row r="{i}"><c r="A{i}" t="inlineStr"><is><t>r{i}</t></is></c></row>' for i in range(1, 5002))
    doc = variant(out, f'<worksheet xmlns="{S[1:-1]}"><sheetData>{rows}</sheetData><hyperlinks><hyperlink ref="A5001" location="Beyond"/></hyperlinks></worksheet>')
    links, shapes = actual(doc['document']['blocks'])
    assert shapes[0] == ['Contacts', 5000, 1] and all(l['sheet'] != 'Contacts' for l in links)
    assert any('hyperlink A5001: kept 0 of 1' in w for w in doc['warnings'])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--expect-json', action='store_true')
    ap.add_argument('--actual-file', type=Path)
    args = ap.parse_args()
    if args.expect_json:
        print(json.dumps(expectations()))
        return
    if args.actual_file:
        check(json.loads(args.actual_file.read_text()))
        return
    with tempfile.TemporaryDirectory(prefix='xlsx-links-') as temp:
        out = Path(temp)
        result = parse(SOURCE, out, convert=True)
        check(result)
        html = Anchors()
        html.feed((out / 'links.html').read_text())
        assert Counter(html.links) == Counter(link['href'] for link in expectations()['links'])
        check_bounds(out)
    print('OK XLSX: 11 source-derived cell targets, HTML targets, sparse rows, ranges and metadata/row limits')


if __name__ == '__main__':
    main()
