#!/usr/bin/env bash
# Regenerate the example files shown on docs/pdf-to-powerpoint.html.
#
# Source: our own example deck, docs/assets/pdf-to-powerpoint/source/deck.html,
# printed to PDF with headless Chrome (the way decks reach people: exported).
# Output: docs/assets/pdf-to-powerpoint/ — the source PDF, the generated decks
# in four looks, their LibreOffice renders (embedded in the page), slide
# screenshots, gallery thumbnails, the example templates and the parse JSON the
# page's structure view loads.
#
# Needs: this repo's bin/docparse, AILANG, Google Chrome (or CHROME=...),
# LibreOffice (soffice) and poppler.
#   bash docs/scripts/build-pdf-to-powerpoint-assets.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$REPO/docs/assets/pdf-to-powerpoint"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$OUT"

# 1. The source deck as a PDF.
"$CHROME" --headless=new --disable-gpu --no-pdf-header-footer \
  --print-to-pdf="$OUT/source.pdf" "file://$OUT/source/deck.html" > /dev/null 2>&1
[ -s "$OUT/source.pdf" ] || { echo "Chrome did not print the deck" >&2; exit 1; }

# 2. Example templates, built in AILANG from a deck AILANG Parse generates.
printf '# Title\n\nBody text.\n' > "$WORK/base.md"
"$REPO/bin/docparse" "$WORK/base.md" --convert "$WORK/base.pptx" --output-dir "$WORK/base" > /dev/null 2>&1
(cd "$REPO/docs" && PPTX_BASE="$WORK/base.pptx" AILANG_NO_TRACE=1 ailang run --quiet --entry main \
  --caps IO,FS,Env scripts/pdf_to_powerpoint_templates.ail)
TPL="$OUT/templates"

# 3. The PDF back to slides, in four looks. No --pdf-backend: converting to
#    slides reads the PDF with poppler's slide mode.
convert() {  # look, extra docparse args...
  local look="$1"; shift
  "$REPO/bin/docparse" "$OUT/source.pdf" --convert "$OUT/deck-$look.pptx" \
    --output-dir "$WORK/$look" "$@" > "$WORK/$look.log" 2>&1
  grep -q "Generated PPTX" "$WORK/$look.log" || { cat "$WORK/$look.log" >&2; exit 1; }
}
convert plain
convert midnight --reference-doc "$TPL/midnight-reference.pptx"
convert paper    --reference-doc "$TPL/paper-reference.pptx"
convert bold     --reference-doc "$TPL/bold-reference.pptx"

# 4. What the read produced, for the structure view.
python3 - "$WORK/plain/source.pdf.json" "$OUT/deck.blocks.json" <<'EOF'
import json, sys
d = json.load(open(sys.argv[1]))
d["document"]["filename"] = "source.pdf"
json.dump(d, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
EOF

# 5. Renders for the side-by-side embed, opened without the bookmarks sidebar
#    (same-length PageMode rewrite, as for the PDF to Word page).
(cd "$OUT" && soffice --headless --convert-to pdf deck-*.pptx > /dev/null 2>&1)
python3 - "$OUT"/source.pdf "$OUT"/deck-*.pdf <<'EOF'
import sys
old, new = b"/PageMode/UseOutlines", b"/PageMode/UseNone    "
for path in sys.argv[1:]:
    data = open(path, "rb").read()
    if old in data:
        open(path, "wb").write(data.replace(old, new))
EOF

# 6. Screenshots: the source and the plain deck slide by slide (diagram and
#    table pairs on the page), and a gallery thumbnail per look (the table slide).
shot() { pdftoppm -r "$4" -jpeg -jpegopt quality=82 -f "$2" -l "$2" -singlefile "$1" "$3"; }
for n in 1 2 3 4 5; do
  shot "$OUT/source.pdf" "$n" "$OUT/source-s$n" 60
  shot "$OUT/deck-plain.pdf" "$n" "$OUT/plain-s$n" 60
done
for look in plain midnight paper bold; do
  shot "$OUT/deck-$look.pdf" 3 "$OUT/gallery-$look" 50
done

if grep -rqs -e "/Users/" -e "/private/" -e "/home/" "$OUT" --exclude=deck.html; then
  echo "A local path leaked into $OUT" >&2
  exit 1
fi
echo "Rebuilt $(ls "$OUT" | wc -l | tr -d ' ') entries in docs/assets/pdf-to-powerpoint/"
