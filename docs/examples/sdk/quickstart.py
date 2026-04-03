from ailang_parse import DocParse

client = DocParse(api_key="dp_your_key_here")

result = client.parse("report.docx")
for block in result.blocks:
    if block.type == "heading":
        print(f"H{block.level}: {block.text}")
    elif block.type == "table":
        print(f"Table: {len(block.rows)} rows")
    elif block.type == "change":
        print(f"{block.change_type} by {block.author}")

# Unstructured migration — one import change:
from ailang_parse import UnstructuredClient
client = UnstructuredClient(server_url="https://docparse.ailang.sunholo.com")
elements = client.general.partition(file="report.docx")