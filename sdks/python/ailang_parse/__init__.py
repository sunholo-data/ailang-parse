"""AILANG Parse — Python client for the AILANG Parse document parsing API.

Upload and parse a local file::

    from ailang_parse import DocParse

    client = DocParse(api_key="dp_a1b2c3d4...")
    result = client.parse_file("report.docx")
    print(result.blocks)

Parse a sample or server-side file::

    result = client.parse("sample_docx_basic")

Unstructured migration::

    from ailang_parse import UnstructuredClient
    client = UnstructuredClient(
        server_url="https://api.parse.sunholo.com"
    )
    elements = client.general.partition(file="report.docx")
"""
from .client import DocParse
from .compat import UnstructuredClient
from .types import (
    Block, Cell, Section, ParseResult, DocMetadata, Summary, ResponseMeta,
    HealthResult, FormatsResult,
    KeyInfo, Quota, Usage, UsageInfo,
    Element, ElementMetadata,
    DocParseError, AuthError, QuotaError,
)

__version__ = "0.5.3"
__all__ = [
    "DocParse",
    "UnstructuredClient",
    "Block", "Cell", "Section", "ParseResult", "DocMetadata", "Summary",
    "ResponseMeta",
    "HealthResult", "FormatsResult",
    "KeyInfo", "Quota", "Usage", "UsageInfo",
    "Element", "ElementMetadata",
    "DocParseError", "AuthError", "QuotaError",
]
