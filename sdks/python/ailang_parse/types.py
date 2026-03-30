"""AILANG Parse types — Block ADT, ParseResult, metadata, errors."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union


# ── Errors ──

class DocParseError(Exception):
    """Base error for all AILANG Parse API errors."""
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


class AuthError(DocParseError):
    """Invalid or missing API key."""
    pass


class QuotaError(DocParseError):
    """Quota exceeded (daily requests or monthly pages)."""
    def __init__(self, message: str, tier: str = "", used: int = 0, limit: int = 0):
        super().__init__(message, 429)
        self.tier = tier
        self.used = used
        self.limit = limit


# ── Cell (for tables) ──

@dataclass
class Cell:
    text: str = ""
    col_span: int = 1
    merged: bool = False

    @classmethod
    def from_raw(cls, raw: Any) -> "Cell":
        if isinstance(raw, str):
            return cls(text=raw)
        if isinstance(raw, dict):
            return cls(
                text=raw.get("text", ""),
                col_span=raw.get("colSpan", 1),
                merged=raw.get("merged", False),
            )
        return cls(text=str(raw))


# ── Block variants ──

@dataclass
class Block:
    type: str = ""
    # TextBlock / HeadingBlock / ChangeBlock
    text: str = ""
    level: int = 0
    style: str = ""
    # ChangeBlock
    change_type: str = ""
    author: str = ""
    date: str = ""
    # TableBlock
    headers: List[Cell] = field(default_factory=list)
    rows: List[List[Cell]] = field(default_factory=list)
    # ListBlock
    items: List[str] = field(default_factory=list)
    ordered: bool = False
    # ImageBlock / AudioBlock / VideoBlock
    description: str = ""
    transcription: str = ""
    mime: str = ""
    data_length: int = 0
    # SectionBlock
    kind: str = ""
    children: List["Block"] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Block":
        block_type = d.get("type", "")
        b = cls(type=block_type)

        b.text = d.get("text", "")
        b.level = d.get("level", 0)
        b.style = d.get("style", "")
        b.change_type = d.get("changeType", "")
        b.author = d.get("author", "")
        b.date = d.get("date", "")
        b.description = d.get("description", "")
        b.transcription = d.get("transcription", "")
        b.mime = d.get("mime", "")
        b.data_length = d.get("dataLength", 0)
        b.kind = d.get("kind", "")
        b.ordered = d.get("ordered", False)
        b.items = d.get("items", [])

        # Table
        b.headers = [Cell.from_raw(c) for c in d.get("headers", [])]
        b.rows = [[Cell.from_raw(c) for c in row] for row in d.get("rows", [])]

        # Section (recursive)
        b.children = [Block.from_dict(child) for child in d.get("blocks", [])]

        return b


# ── Metadata ──

@dataclass
class DocMetadata:
    title: str = ""
    author: str = ""
    created: str = ""
    modified: str = ""
    page_count: int = 0

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DocMetadata":
        return cls(
            title=d.get("title", ""),
            author=d.get("author", ""),
            created=d.get("created", ""),
            modified=d.get("modified", ""),
            page_count=d.get("pageCount", 0),
        )


@dataclass
class Summary:
    total_blocks: int = 0
    headings: int = 0
    tables: int = 0
    images: int = 0
    changes: int = 0

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Summary":
        return cls(
            total_blocks=d.get("totalBlocks", 0),
            headings=d.get("headings", 0),
            tables=d.get("tables", 0),
            images=d.get("images", 0),
            changes=d.get("changes", 0),
        )


# ── Parse result ──

@dataclass
class ParseResult:
    status: str = ""
    filename: str = ""
    format: str = ""
    blocks: List[Block] = field(default_factory=list)
    metadata: DocMetadata = field(default_factory=DocMetadata)
    summary: Summary = field(default_factory=Summary)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ParseResult":
        return cls(
            status=d.get("status", ""),
            filename=d.get("filename", ""),
            format=d.get("format", ""),
            blocks=[Block.from_dict(b) for b in d.get("blocks", [])],
            metadata=DocMetadata.from_dict(d.get("metadata", {})),
            summary=Summary.from_dict(d.get("summary", {})),
        )


# ── Health / Formats ──

@dataclass
class HealthResult:
    status: str = ""
    version: str = ""
    service: str = ""
    formats_parse: int = 0
    formats_generate: int = 0

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "HealthResult":
        return cls(
            status=d.get("status", ""),
            version=d.get("version", ""),
            service=d.get("service", ""),
            formats_parse=int(d.get("formats_parse", 0)),
            formats_generate=int(d.get("formats_generate", 0)),
        )


@dataclass
class FormatsResult:
    parse: List[str] = field(default_factory=list)
    generate: List[str] = field(default_factory=list)
    ai_required: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FormatsResult":
        return cls(
            parse=d.get("parse", []),
            generate=d.get("generate", []),
            ai_required=d.get("ai_required", []),
        )


# ── Key management types ──

@dataclass
class Quota:
    requests_per_day: int = 0
    pages_per_month: int = 0
    ai_limit_per_request: int = 0
    fs_limit_per_request: int = 0

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Quota":
        return cls(
            requests_per_day=int(d.get("requestsPerDay", 0)),
            pages_per_month=int(d.get("pagesPerMonth", 0)),
            ai_limit_per_request=int(d.get("aiLimitPerRequest", 0)),
            fs_limit_per_request=int(d.get("fsLimitPerRequest", 0)),
        )


@dataclass
class KeyInfo:
    status: str = ""
    key: str = ""
    key_id: str = ""
    label: str = ""
    tier: str = ""
    created: str = ""
    quota: Quota = field(default_factory=Quota)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "KeyInfo":
        return cls(
            status=d.get("status", ""),
            key=d.get("key", ""),
            key_id=d.get("keyId", ""),
            label=d.get("label", ""),
            tier=d.get("tier", ""),
            created=d.get("created", ""),
            quota=Quota.from_dict(d.get("quota", {})),
        )


@dataclass
class Usage:
    requests_today: int = 0
    pages_this_month: int = 0
    total_requests: int = 0
    total_pages: int = 0

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Usage":
        return cls(
            requests_today=int(d.get("requestsToday", 0)),
            pages_this_month=int(d.get("pagesThisMonth", 0)),
            total_requests=int(d.get("totalRequests", 0)),
            total_pages=int(d.get("totalPages", 0)),
        )


@dataclass
class UsageInfo:
    status: str = ""
    key_id: str = ""
    tier: str = ""
    usage: Usage = field(default_factory=Usage)
    quota: Quota = field(default_factory=Quota)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "UsageInfo":
        return cls(
            status=d.get("status", ""),
            key_id=d.get("keyId", ""),
            tier=d.get("tier", ""),
            usage=Usage.from_dict(d.get("usage", {})),
            quota=Quota.from_dict(d.get("quota", {})),
        )


# ── Unstructured compatibility ──

@dataclass
class ElementMetadata:
    filename: str = ""
    filetype: str = ""
    category_depth: int = 0
    image_mime_type: str = ""
    text_as_html: str = ""

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ElementMetadata":
        return cls(
            filename=d.get("filename", ""),
            filetype=d.get("filetype", ""),
            category_depth=d.get("category_depth", 0),
            image_mime_type=d.get("image_mime_type", ""),
            text_as_html=d.get("text_as_html", ""),
        )


@dataclass
class Element:
    type: str = ""
    element_id: str = ""
    text: str = ""
    metadata: ElementMetadata = field(default_factory=ElementMetadata)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Element":
        return cls(
            type=d.get("type", ""),
            element_id=d.get("element_id", ""),
            text=d.get("text", ""),
            metadata=ElementMetadata.from_dict(d.get("metadata", {})),
        )
