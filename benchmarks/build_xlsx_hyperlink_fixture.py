"""Build a small XLSX with independent link metadata and sparse source rows.

The file stays outside the public OfficeDocBench corpus: it is a parser gate,
shared by native and Chromium tests, rather than an unrun competitor case.
"""
from pathlib import Path
from xml.sax.saxutils import escape
import zipfile

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / 'benchmarks/fixtures/xlsx_hyperlinks.xlsx'
S = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
P = 'http://schemas.openxmlformats.org/package/2006/relationships'


def cell(ref, text):
    return f'<c r="{ref}" t="inlineStr"><is><t>{escape(text)}</t></is></c>'


def build():
    rows = '<row r="5">' + ''.join(cell(ref, text) for ref, text in [
        ('A5', 'https://plain.example/'), ('B5', 'Read the guide'),
        ('D5', 'Other tab'), ('E5', 'Resource section'), ('F5', 'Broken relationship'),
    ]) + '<c r="H5"><f>HYPERLINK("https://formula.example/","Formula")</f></c>' + cell('I5', 'Tail') + '</row>'
    rows += '<row r="7">' + ''.join(cell(ref, text) for ref, text in [
        ('A7', 'First range label'), ('C7', 'Last range label'), ('D7', 'Merged label')]) + '</row>'
    rows += '<row r="400">' + cell('B400', 'Distant label') + '</row>'
    links = '''<hyperlinks>
      <hyperlink ref="B5" r:id="rId1" display="This is not the cell label"/>
      <hyperlink ref="C5" r:id="rId3"/>
      <hyperlink ref="D5" location="'Other tab'!B9"/>
      <hyperlink ref="E5" r:id="rId2" location="Part2"/>
      <hyperlink ref="F5" r:id="missing" location="DoNotGuess"/>
      <hyperlink ref="B6" r:id="rId4"/>
      <hyperlink ref="A7:C7" location="NamedDestination"/>
      <hyperlink ref="D7:E7" r:id="rId5"/>
      <hyperlink ref="B400" r:id="rId6"/>
      <hyperlink ref="B200" r:id="rId7"/>
      <hyperlink ref="XFD1048576" location="FarAway"/>
      <hyperlink ref="bad-ref" location="Invalid"/>
    </hyperlinks>'''
    sheet = f'<worksheet xmlns="{S}" xmlns:r="{R}"><sheetData>{rows}</sheetData><mergeCells count="1"><mergeCell ref="D7:E7"/></mergeCells>{links}</worksheet>'
    targets = [
        ('rId1', 'https://guide.example/?x=1&y=2'),
        ('rId2', 'https://resource.example/manual#old'),
        ('rId3', 'mailto:help@example.org'), ('rId4', '../relative.xlsx'),
        ('rId5', 'https://merged.example/'), ('rId6', 'https://distant.example/'),
        ('rId7', 'https://omitted.example/'),
    ]
    rels = f'<Relationships xmlns="{P}">' + ''.join(
        f'<Relationship Id="{key}" Type="{R}/hyperlink" Target="{escape(value, {chr(34): "&quot;"})}" TargetMode="External"/>'
        for key, value in targets) + '</Relationships>'
    other = f'<worksheet xmlns="{S}" xmlns:r="{R}"><sheetData><row>{cell("B9", "Read the guide")}</row></sheetData><hyperlinks><hyperlink ref="B9" r:id="rId1"/></hyperlinks></worksheet>'
    other_rels = f'<Relationships xmlns="{P}"><Relationship Id="rId1" Type="{R}/hyperlink" Target="https://other.example/" TargetMode="External"/></Relationships>'
    replacements = {
        'xl/worksheets/sheet1.xml': sheet,
        'xl/worksheets/_rels/sheet1.xml.rels': rels,
        'xl/worksheets/sheet2.xml': other,
        'xl/worksheets/_rels/sheet2.xml.rels': other_rels,
        'xl/workbook.xml': f'<workbook xmlns="{S}" xmlns:r="{R}"><sheets><sheet name="Contacts" sheetId="1" r:id="rId1"/><sheet name="Other tab" sheetId="2" r:id="rId2"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels': f'<Relationships xmlns="{P}"><Relationship Id="rId1" Type="{R}/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="{R}/worksheet" Target="worksheets/sheet2.xml"/></Relationships>',
    }
    with zipfile.ZipFile(ROOT / 'data/test_files/challenge/challenge_hyperlinks.xlsx') as src:
        contents = {info.filename: src.read(info.filename) for info in src.infolist()}
    contents.update(replacements)
    contents['[Content_Types].xml'] = contents['[Content_Types].xml'].replace(
        b'</Types>', f'<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>'.encode())
    with zipfile.ZipFile(OUTPUT, 'w', compression=zipfile.ZIP_DEFLATED) as dst:
        for name, content in sorted(contents.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 23, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            dst.writestr(info, content)
    print(OUTPUT.relative_to(ROOT))


if __name__ == '__main__':
    build()
