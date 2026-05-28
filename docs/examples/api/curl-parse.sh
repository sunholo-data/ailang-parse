# Parse a built-in sample — list all 26 via GET /api/v1/samples
curl -X POST https://docparse.ailang.sunholo.com/api/v1/parse \
  -H "Content-Type: application/json" \
  -d '{"sample_id":"sample_docx_formatting","outputFormat":"markdown","apiKey":"dp_YOUR_KEY"}'
