#!/usr/bin/env bash
# Regenerate the example files shown on docs/pdf-to-word.html.
#
# Source: our own proposal template PDF (docs/templates/output/ailang-proposal.pdf).
# Output: docs/assets/pdf-to-word/ — the generated .docx files, their LibreOffice
# renders (embedded in the page), page screenshots, and the parse JSON the
# page's structure view loads.
#
# Needs: this repo's bin/docparse, LibreOffice (soffice) and poppler.
# Run from anywhere:  bash docs/scripts/build-pdf-to-word-assets.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$REPO/docs/assets/pdf-to-word"
TPL="$REPO/docs/templates/output"
SRC="$TPL/ailang-proposal.pdf"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$OUT"

# Example reference documents (classic, modern, minimal), built in AILANG.
(cd "$REPO/docs" && AILANG_NO_TRACE=1 ailang run --quiet --entry main --caps IO,FS \
  scripts/pdf_to_word_templates.ail)
EXAMPLES="$OUT/templates"
cd "$WORK"

convert() {  # name, extra docparse args...
  local name="$1"; shift
  "$REPO/bin/docparse" "$SRC" --pdf-backend poppler --convert "$OUT/proposal-$name.docx" \
    --output-dir "$WORK/$name" "$@" > "$WORK/$name.log" 2>&1
  grep -q "Generated DOCX" "$WORK/$name.log" || { cat "$WORK/$name.log" >&2; exit 1; }
}
# No --table-style: docparse binds tables to the template's table style by default.
convert ailang-style  --reference-doc "$TPL/references/ailang-reference.docx"
convert holosun-style --reference-doc "$TPL/references/holosun-reference.docx"
convert sunholo-style --reference-doc "$TPL/references/sunholo-reference.docx"
convert classic-style --reference-doc "$EXAMPLES/classic-reference.docx"
convert modern-style  --reference-doc "$EXAMPLES/modern-reference.docx"
convert minimal-style --reference-doc "$EXAMPLES/minimal-reference.docx"
convert no-template

# Parse output for the structure view, without the local path in "filename".
python3 - "$WORK/ailang-style/ailang-proposal.pdf.json" "$OUT/proposal.blocks.json" <<'EOF'
import json, sys
d = json.load(open(sys.argv[1]))
d["document"]["filename"] = "ailang-proposal.pdf"
json.dump(d, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
EOF

# Renders for the side-by-side embed, plus a copy of the source PDF.
(cd "$OUT" && soffice --headless --convert-to pdf proposal-*.docx > /dev/null 2>&1)
cp "$SRC" "$OUT/source.pdf"

# Open the embeds without the bookmarks sidebar. LibreOffice writes
# /PageMode /UseOutlines, which makes browser viewers open their sidebar and
# squeezes the side-by-side panes. Same-length replacement keeps every byte
# offset in the xref table valid.
python3 - "$OUT"/source.pdf "$OUT"/proposal-*.pdf <<'EOF'
import sys
old, new = b"/PageMode/UseOutlines", b"/PageMode/UseNone    "
for path in sys.argv[1:]:
    data = open(path, "rb").read()
    if old in data:
        open(path, "wb").write(data.replace(old, new))
EOF

# Page screenshots.
shot() { pdftoppm -r 90 -jpeg -jpegopt quality=82 -f "$2" -l "$2" -singlefile "$1" "$3"; }
shot "$OUT/source.pdf" 1 "$OUT/source-p1"
shot "$OUT/source.pdf" 3 "$OUT/source-p3"
shot "$OUT/proposal-ailang-style.pdf" 1 "$OUT/ailang-style-p1"
shot "$OUT/proposal-ailang-style.pdf" 3 "$OUT/ailang-style-p3"
shot "$OUT/proposal-holosun-style.pdf" 3 "$OUT/holosun-style-p3"
shot "$OUT/proposal-no-template.pdf" 1 "$OUT/no-template-p1"
rm -f "$OUT/holosun-style-p1.jpg"   # not used by the page

# Gallery: the page that starts "Scope and delivery" in every look, so the
# thumbnails compare like with like whatever the template's pagination.
for name in ailang-style classic-style modern-style minimal-style no-template; do
  f="$OUT/proposal-$name.pdf"
  pages="$(pdfinfo "$f" | awk '/^Pages:/ {print $2}')"
  page=1
  for ((i = 1; i <= pages; i++)); do
    # By the H2 under it: some templates set H1 in small caps or capitals.
    if pdftotext -f "$i" -l "$i" "$f" - | grep -qi "what we will deliver"; then page=$i; break; fi
  done
  pdftoppm -r 60 -jpeg -jpegopt quality=80 -f "$page" -l "$page" -singlefile "$f" "$OUT/gallery-$name"
done

if grep -rqs -e "/Users/" -e "/private/" -e "/home/" "$OUT"; then
  echo "A local path leaked into $OUT" >&2
  exit 1
fi
echo "Rebuilt $(ls "$OUT" | wc -l | tr -d ' ') files in docs/assets/pdf-to-word/"
