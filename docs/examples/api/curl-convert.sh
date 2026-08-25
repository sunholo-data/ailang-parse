# Generate a DOCX from Markdown via the hosted API.
# The document comes back inside the JSON, not as a binary body.
curl -s -X POST https://docparse.ailang.sunholo.com/api/v1/convert \
  -F "filepath=@report.md" \
  -F "target=docx" \
  -F "apiKey=$DOCPARSE_API_KEY" > response.json

# `encoding` is load-bearing: "base64" for the six ZIP container targets
# (docx, pptx, xlsx, odt, odp, ods) and "utf8" for the three text targets
# (html, md, qmd). Branch on the field, never on the target.
python3 - <<'PY'
import base64, json
r = json.load(open("response.json"))
# Unwrap the serve-api envelope, same as /api/v1/parse
if isinstance(r.get("result"), str):
    r = json.loads(r["result"])
data = (base64.b64decode(r["content"]) if r["encoding"] == "base64"
        else r["content"].encode("utf-8"))
open(r["filename"], "wb").write(data)
print(f'{r["filename"]}  {r["content_type"]}  {r["size_bytes"]} bytes')
PY

# Other input modes — a sample ID, or a URL the server fetches itself
curl -s -X POST https://docparse.ailang.sunholo.com/api/v1/convert \
  -H "Content-Type: application/json" \
  -d '{"filepath":"sample_docx_tables","target":"html","apiKey":"'"$DOCPARSE_API_KEY"'"}'

curl -s -X POST https://docparse.ailang.sunholo.com/api/v1/convert \
  -H "Content-Type: application/json" \
  -d '{"sourceUrl":"https://example.com/notes.md","target":"pptx","apiKey":"'"$DOCPARSE_API_KEY"'"}'
