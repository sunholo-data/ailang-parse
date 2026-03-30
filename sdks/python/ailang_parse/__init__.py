"""AILANG Parse — Python client for the AILANG Parse document parsing API.

Usage::

    from ailang_parse import DocParse

    client = DocParse(api_key="dp_a1b2c3d4...")
    result = client.parse("report.docx")
    print(result.blocks)

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
    Block, Cell, ParseResult, DocMetadata, Summary,
    HealthResult, FormatsResult,
    KeyInfo, Quota, Usage, UsageInfo,
    Element, ElementMetadata,
    DocParseError, AuthError, QuotaError,
)

__version__ = "0.1.0"
__all__ = [
    "DocParse",
    "UnstructuredClient",
    "Block", "Cell", "ParseResult", "DocMetadata", "Summary",
    "HealthResult", "FormatsResult",
    "KeyInfo", "Quota", "Usage", "UsageInfo",
    "Element", "ElementMetadata",
    "DocParseError", "AuthError", "QuotaError",
]
