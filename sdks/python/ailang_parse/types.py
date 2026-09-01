"""AILANG Parse types — Block ADT, ParseResult, metadata, errors."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union


# ── Errors ──

class DocParseError(Exception):
    """Base error for all AILANG Parse API errors.

    All attributes default to falsy values so callers can read them
    unconditionally (``err.request_id``, ``err.replayable``) without
    type-narrowing first.
    """
    def __init__(self, message: str, status_code: int = 0, suggested_fix: str = "",
                 details: Optional[Dict[str, Any]] = None, request_id: str = "",
                 replayable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.suggested_fix = suggested_fix
        self.details = details
        self.request_id = request_id
        self.replayable = replayable


class AuthError(DocParseError):
    """Invalid or missing API key."""
    def __init__(self, message: str = "Invalid or missing API key", *args, **kwargs):
        # Support legacy positional `AuthError(msg, 401)` while letting kwargs
        # like request_id= flow through.
        if args:
            kwargs.setdefault("status_code", args[0])
        kwargs.setdefault("status_code", 401)
        super().__init__(message, **kwargs)


class QuotaError(DocParseError):
    """Quota exceeded (daily or monthly requests)."""
    def __init__(self, message: str = "Quota exceeded", *,
                 tier: str = "", used: int = 0, limit: int = 0, **kwargs):
        kwargs.setdefault("status_code", 429)
        super().__init__(message, **kwargs)
        self.tier = tier
        self.used = used
        self.limit = limit


# ── Retry policy ──

@dataclass
class RetryPolicy:
    """Retry configuration for transient failures.

    The default policy does not retry — opt in by setting ``max_retries``.
    Pass to :class:`DocParse` as the ``retry=`` argument::

        client = DocParse(retry=RetryPolicy(max_retries=3,
                                            respect_replayable=True))

    Attributes:
        max_retries: Maximum number of retries (0 = no retry).
        retryable_statuses: HTTP statuses that always trigger a retry.
        respect_replayable: When True, also retry any 5xx response that
            carries ``X-AilangParse-Replayable: true``. Useful for 500s
            the server explicitly marks as safe to re-attempt.
        backoff_base: Exponential backoff base in seconds. Delay before
            retry N is ``min(backoff_base * 2**N, backoff_max)``.
        backoff_max: Upper bound on the per-retry delay, in seconds.
    """
    max_retries: int = 0
    retryable_statuses: "frozenset[int]" = field(
        default_factory=lambda: frozenset({502, 503, 504})
    )
    respect_replayable: bool = True
    backoff_base: float = 1.0
    backoff_max: float = 30.0

    def should_retry(self, status_code: int, replayable: bool) -> bool:
        if self.max_retries <= 0:
            return False
        if status_code in self.retryable_statuses:
            return True
        if self.respect_replayable and 500 <= status_code < 600 and replayable:
            return True
        return False

    def delay_for(self, attempt: int) -> float:
        return min(self.backoff_base * (2 ** attempt), self.backoff_max)


# ── Cell (for tables) ──

@dataclass
class InlineRun:
    """A run of text with uniform character formatting inside a paragraph.

    Populated for text/heading blocks (``runs``) and list items (``item_runs``)
    by the DOCX, HTML, PPTX and ODT parsers. Empty when the source carried no
    inline formatting, so a plain paragraph costs nothing.

    ``text`` and the block's ``text`` are allowed to differ: HTML keeps Markdown
    markers in ``text`` for readability while ``runs`` carries the same
    formatting structurally. ``text`` is for reading, runs are for rendering.
    """
    text: str = ""
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    code: bool = False
    #: Link target, "" when the run is not a link.
    href: str = ""
    vert_align: str = ""

    @classmethod
    def from_raw(cls, raw: Any) -> "InlineRun":
        if not isinstance(raw, dict):
            return cls(text=str(raw))
        return cls(
            text=raw.get("text", ""),
            bold=raw.get("bold", False),
            italic=raw.get("italic", False),
            underline=raw.get("underline", False),
            strike=raw.get("strike", False),
            code=raw.get("code", False),
            href=raw.get("href", ""),
            vert_align=raw.get("vertAlign", ""),
        )


@dataclass
class Cell:
    text: str = ""
    col_span: int = 1
    merged: bool = False
    # "" | "left" | "center" | "right". Declared column alignment; empty means
    # unspecified, which is not the same as left.
    align: str = ""

    @classmethod
    def from_raw(cls, raw: Any) -> "Cell":
        if isinstance(raw, str):
            return cls(text=raw)
        if isinstance(raw, dict):
            return cls(
                text=raw.get("text", ""),
                col_span=raw.get("colSpan", 1),
                merged=raw.get("merged", False),
                align=raw.get("align", ""),
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
    # Inline character formatting. `runs` applies to text/heading blocks;
    # `item_runs` is parallel to `items` — same length, or empty.
    runs: List[InlineRun] = field(default_factory=list)
    item_runs: List[List[InlineRun]] = field(default_factory=list)
    # Nesting depth per list item, parallel to `items`; empty for a flat list.
    item_levels: List[int] = field(default_factory=list)
    # ImageBlock / AudioBlock / VideoBlock
    description: str = ""
    transcription: str = ""
    mime: str = ""
    data_length: int = 0
    # SectionBlock. `name` is the container's own identity — a sheet name, a
    # slide title, a chapter — which used to be packed into `kind` as
    # "sheet:Q1" and could not be read back out reliably. Empty for sections
    # that have no name of their own (header, footer, textbox, comment).
    kind: str = ""
    name: str = ""
    children: List["Block"] = field(default_factory=list)
    # CommentBlock. anchor_text is the span of document text this comment
    # annotates. When anchored is False the anchor could not be resolved and
    # anchor_text is empty — the comment has no known target, and callers must
    # not infer one from surrounding blocks.
    id: str = ""
    anchor_text: str = ""
    anchor_kind: str = ""  # "range" | "point" | "cell" | "slide" | "none"
    anchored: bool = False
    anchor_block_index: int = -1
    parent_id: str = ""  # set on threaded replies
    resolved: bool = False

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
        b.name = d.get("name", "")
        b.ordered = d.get("ordered", False)
        b.items = d.get("items", [])
        b.id = d.get("id", "")
        b.anchor_text = d.get("anchorText", "")
        b.anchor_kind = d.get("anchorKind", "")
        b.anchored = d.get("anchored", False)
        b.anchor_block_index = d.get("anchorBlockIndex", -1)
        b.parent_id = d.get("parentId", "")
        b.resolved = d.get("resolved", False)

        b.runs = [InlineRun.from_raw(r) for r in d.get("runs", [])]
        b.item_levels = d.get("itemLevels", [])
        b.item_runs = [[InlineRun.from_raw(r) for r in item]
                       for item in d.get("itemRuns", [])]

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


# ── Section (for markdown+metadata) ──

@dataclass
class Section:
    """A heading-delimited section of a document.

    Returned when ``output_format="markdown+metadata"``.  Each section
    contains the heading text, its level (1–6, or 0 for preamble content
    before the first heading), and the rendered markdown for that section.
    """
    heading: str = ""
    level: int = 0
    markdown: str = ""

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Section":
        return cls(
            heading=d.get("heading", ""),
            level=d.get("level", 0),
            markdown=d.get("markdown", ""),
        )


# ── Response metadata (HTTP headers) ──

@dataclass
class ConvertResult:
    """A converted document from ``POST /api/v1/convert``.

    ``content`` is always decoded bytes regardless of how the wire encoded it —
    base64 for the container targets, UTF-8 for html/md/qmd. Branching on
    ``encoding`` is the SDK's job, not the caller's.
    """
    content: bytes = b""
    filename: str = ""
    content_type: str = ""
    target: str = ""
    source_format: str = ""
    source_subtype: str = ""
    size_bytes: int = 0
    status: str = ""
    request_id: str = ""
    reference_doc_applied: bool = False
    template_parts_carried: int = 0
    response_meta: Optional["ResponseMeta"] = None

    @property
    def text(self) -> str:
        """The document as text. Only meaningful for html/md/qmd targets."""
        return self.content.decode("utf-8")

    def save(self, path: str = "") -> str:
        """Write the document to disk, defaulting to the server's filename."""
        target_path = path or self.filename
        with open(target_path, "wb") as f:
            f.write(self.content)
        return target_path

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ConvertResult":
        import base64
        raw = d.get("content", "")
        encoding = d.get("encoding", "base64")
        # encoding is load-bearing: the three text targets come back as readable
        # UTF-8, everything else as base64. Never infer it from the target.
        content = base64.b64decode(raw) if encoding == "base64" else raw.encode("utf-8")
        return cls(
            content=content,
            filename=d.get("filename", ""),
            content_type=d.get("content_type", ""),
            target=d.get("target", ""),
            source_format=d.get("source_format", ""),
            source_subtype=d.get("source_subtype", ""),
            size_bytes=d.get("size_bytes", len(content)),
            status=d.get("status", ""),
            request_id=d.get("request_id", ""),
            reference_doc_applied=d.get("reference_doc_applied", False),
            template_parts_carried=d.get("template_parts_carried", 0),
        )


@dataclass
class ResponseMeta:
    """Metadata extracted from the API response HTTP headers.

    Populated on :class:`ParseResult` after every parse call.  Contains
    the request ID, the caller's tier, and remaining quota counters.
    """
    request_id: str = ""
    tier: str = ""
    quota_remaining_day: int = -1
    quota_remaining_month: int = -1
    quota_remaining_ai: int = -1
    format: str = ""
    replayable: bool = False

    @classmethod
    def from_headers(cls, headers: Dict[str, str]) -> "ResponseMeta":
        # Case-insensitive lookup — HTTP libraries normalize casing differently
        lc = {k.lower(): v for k, v in headers.items()}
        def _get(key: str) -> str:
            return lc.get(key.lower(), "")
        def _int(key: str) -> int:
            v = _get(key)
            try:
                return int(v)
            except (ValueError, TypeError):
                return -1
        return cls(
            request_id=_get("X-Request-Id"),
            tier=_get("X-DocParse-Tier"),
            quota_remaining_day=_int("X-DocParse-Quota-Remaining-Day"),
            quota_remaining_month=_int("X-DocParse-Quota-Remaining-Month"),
            quota_remaining_ai=_int("X-DocParse-Quota-Remaining-Ai"),
            format=_get("X-AilangParse-Format"),
            replayable=_get("X-AilangParse-Replayable").lower() == "true",
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
    #: Raw rendered output for ``output_format="markdown"`` / ``"html"``.
    #: Empty string for the default ``"blocks"`` output, which populates
    #: :attr:`blocks` instead.
    text: str = ""
    #: Full rendered markdown body for ``output_format="markdown+metadata"``.
    markdown: str = ""
    #: Heading-sliced sections for ``output_format="markdown+metadata"``.
    sections: List[Section] = field(default_factory=list)
    #: A2UI adjacency-list nodes for ``output_format="a2ui"``.
    nodes: List[Any] = field(default_factory=list)
    #: HTTP response metadata (request ID, tier, quota remaining).
    response_meta: Optional[ResponseMeta] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ParseResult":
        return cls(
            status=d.get("status", ""),
            filename=d.get("filename", ""),
            format=d.get("format", ""),
            blocks=[Block.from_dict(b) for b in d.get("blocks", [])],
            metadata=DocMetadata.from_dict(d.get("metadata", {})),
            summary=Summary.from_dict(d.get("summary", {})),
            text=d.get("text", ""),
            markdown=d.get("markdown", ""),
            sections=[Section.from_dict(s) for s in d.get("sections", [])],
        )

    def flatten(self, policy: Optional["FlattenPolicy"] = None) -> List["Chunk"]:
        """Flatten the block tree into RAG-ready chunks.

        See :class:`FlattenPolicy` for the available knobs.  With no
        argument the default policy (``DEFAULT_FLATTEN_POLICY``) is used.

        Returns a list of :class:`Chunk` objects whose ``metadata`` is
        JSON-friendly — feed straight into Vertex/Pinecone/Chroma without
        re-mapping.
        """
        return _flatten_blocks(self.blocks, policy or DEFAULT_FLATTEN_POLICY)


# ── Flatten: Block ADT → RAG chunks ──

@dataclass
class ChunkMetadata:
    """JSON-friendly metadata attached to each :class:`Chunk`.

    The fixed fields cover the common RAG-ingestion case. Consumers who
    need to attach custom tags (per-tenant IDs, confidence scores,
    domain-specific fields) populate :attr:`extras` — preferably with
    JSON-serializable values, since they typically end up in
    Pinecone / Vertex / Chroma metadata unchanged.
    """
    block_type: str = ""
    section_path: List[str] = field(default_factory=list)
    block_index: int = 0
    table_id: Optional[str] = None
    row_index: Optional[int] = None
    change_author: Optional[str] = None
    change_type: Optional[str] = None
    image_mime: Optional[str] = None
    heading_level: Optional[int] = None
    extras: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "block_type": self.block_type,
            "section_path": list(self.section_path),
            "block_index": self.block_index,
        }
        for key in ("table_id", "row_index", "change_author", "change_type",
                    "image_mime", "heading_level"):
            v = getattr(self, key)
            if v is not None:
                out[key] = v
        if self.extras:
            out["extras"] = dict(self.extras)
        return out


@dataclass
class Chunk:
    text: str = ""
    metadata: ChunkMetadata = field(default_factory=ChunkMetadata)

    def to_dict(self) -> Dict[str, Any]:
        return {"text": self.text, "metadata": self.metadata.to_dict()}


_CELL_ESCAPE_MODES = ("preserve", "escape", "space")


@dataclass
class FlattenPolicy:
    """Policy governing :meth:`ParseResult.flatten`.

    Attributes:
        max_chunk_chars: Soft upper bound on chunk size in characters.
            Text blocks longer than this are split on whitespace boundaries.
        embed_images: Emit a chunk for each ``ImageBlock``. When the image
            has no AI caption, the chunk text is a machine-readable
            placeholder (``"[image: <mime>, <bytes> bytes]"``) and
            ``metadata.extras["image_has_description"]`` is ``False``.
            Most RAG pipelines disable this.
        embed_changes: Emit a chunk for each ``ChangeBlock`` with author
            metadata.  Most pipelines disable this; threaded review tools
            enable it.
        embed_comments: Emit a chunk for each ``CommentBlock`` (parser-side
            support gated on the docparse v0.19.0+ comment work — this
            knob ships forward-compat).
        on_table: ``"row"`` (default — one chunk per row with header
            context), ``"whole"`` (one chunk for the entire table), or
            a callable ``(Block, ChunkMetadata) -> List[Chunk]`` that
            takes full control.
        on_table_cell_newlines: How to handle ``\\n`` inside a table cell
            when joining with ``" | "``. ``"preserve"`` (default) keeps
            them as-is, ``"escape"`` replaces them with a literal
            ``"\\\\n"`` (round-trippable), ``"space"`` collapses to
            ``" "`` (lossy, retrieval-friendly).
        on_table_cell_pipes: Same three modes for literal ``|`` inside a
            cell. ``"escape"`` produces ``"\\\\|"``.
        section_path: Track heading ancestry on each emitted chunk.
    """
    max_chunk_chars: int = 2000
    embed_images: bool = False
    embed_changes: bool = False
    embed_comments: bool = False
    on_table: Union[str, Callable[["Block", "ChunkMetadata"], List["Chunk"]]] = "row"
    on_table_cell_newlines: str = "preserve"
    on_table_cell_pipes: str = "preserve"
    section_path: bool = True

    def __post_init__(self) -> None:
        if self.on_table_cell_newlines not in _CELL_ESCAPE_MODES:
            raise ValueError(
                f"on_table_cell_newlines must be one of {_CELL_ESCAPE_MODES}, "
                f"got {self.on_table_cell_newlines!r}"
            )
        if self.on_table_cell_pipes not in _CELL_ESCAPE_MODES:
            raise ValueError(
                f"on_table_cell_pipes must be one of {_CELL_ESCAPE_MODES}, "
                f"got {self.on_table_cell_pipes!r}"
            )


DEFAULT_FLATTEN_POLICY = FlattenPolicy()


def _escape_cell(text: str, newlines: str, pipes: str) -> str:
    """Apply the policy's cell-escape modes to a single cell's text."""
    if newlines == "escape":
        text = text.replace("\n", "\\n")
    elif newlines == "space":
        text = text.replace("\n", " ")
    if pipes == "escape":
        text = text.replace("|", "\\|")
    elif pipes == "space":
        text = text.replace("|", " ")
    return text


def _split_long_text(text: str, max_chars: int) -> List[str]:
    """Split on whitespace boundaries when text exceeds max_chars."""
    if len(text) <= max_chars or max_chars <= 0:
        return [text]
    out: List[str] = []
    remaining = text
    while len(remaining) > max_chars:
        cut = remaining.rfind(" ", 0, max_chars)
        if cut <= 0:
            cut = max_chars
        out.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        out.append(remaining)
    return [s for s in out if s]


def _flatten_blocks(blocks: List["Block"], policy: FlattenPolicy,
                    section_path: Optional[List[str]] = None,
                    counter: Optional[List[int]] = None) -> List[Chunk]:
    """Internal: recursive flatten over a list of blocks."""
    section_path = section_path or []
    counter = counter if counter is not None else [0]
    out: List[Chunk] = []

    for b in blocks:
        idx = counter[0]
        counter[0] += 1
        bt = b.type or ""

        if bt == "text" or bt == "TextBlock":
            for piece in _split_long_text(b.text, policy.max_chunk_chars):
                if not piece:
                    continue
                out.append(Chunk(
                    text=piece,
                    metadata=ChunkMetadata(
                        block_type="text",
                        section_path=list(section_path) if policy.section_path else [],
                        block_index=idx,
                    ),
                ))
        elif bt == "heading" or bt == "HeadingBlock":
            out.append(Chunk(
                text=b.text,
                metadata=ChunkMetadata(
                    block_type="heading",
                    section_path=list(section_path) if policy.section_path else [],
                    block_index=idx,
                    heading_level=b.level or None,
                ),
            ))
        elif bt == "table" or bt == "TableBlock":
            md = ChunkMetadata(
                block_type="table",
                section_path=list(section_path) if policy.section_path else [],
                block_index=idx,
                table_id=f"table-{idx}",
            )
            if callable(policy.on_table):
                out.extend(policy.on_table(b, md))
            else:
                nl = policy.on_table_cell_newlines
                pi = policy.on_table_cell_pipes
                if policy.on_table == "whole":
                    rows_text = [
                        " | ".join(_escape_cell(c.text, nl, pi)
                                   for c in (b.headers or [])),
                        *[" | ".join(_escape_cell(c.text, nl, pi) for c in row)
                          for row in b.rows],
                    ]
                    out.append(Chunk(text="\n".join(rows_text), metadata=md))
                else:  # "row"
                    headers = [_escape_cell(c.text, nl, pi)
                               for c in (b.headers or [])]
                    header_line = " | ".join(headers) if headers else ""
                    for ri, row in enumerate(b.rows):
                        cells = [_escape_cell(c.text, nl, pi) for c in row]
                        if header_line:
                            text = header_line + "\n" + " | ".join(cells)
                        else:
                            text = " | ".join(cells)
                        out.append(Chunk(
                            text=text,
                            metadata=ChunkMetadata(
                                block_type="table_row",
                                section_path=list(section_path) if policy.section_path else [],
                                block_index=idx,
                                table_id=md.table_id,
                                row_index=ri,
                            ),
                        ))
        elif bt == "list" or bt == "ListBlock":
            text = "\n".join(f"- {item}" for item in b.items)
            for piece in _split_long_text(text, policy.max_chunk_chars):
                if not piece:
                    continue
                out.append(Chunk(
                    text=piece,
                    metadata=ChunkMetadata(
                        block_type="list",
                        section_path=list(section_path) if policy.section_path else [],
                        block_index=idx,
                    ),
                ))
        elif bt == "image" or bt == "ImageBlock":
            if policy.embed_images:
                has_desc = bool(b.description)
                text = (b.description or b.transcription
                        or f"[image: {b.mime or 'unknown'}, {b.data_length} bytes]")
                md_img = ChunkMetadata(
                    block_type="image",
                    section_path=list(section_path) if policy.section_path else [],
                    block_index=idx,
                    image_mime=b.mime or None,
                )
                md_img.extras["image_data_length"] = b.data_length
                md_img.extras["image_has_description"] = has_desc
                out.append(Chunk(text=text, metadata=md_img))
        elif bt == "change" or bt == "ChangeBlock":
            if policy.embed_changes and b.text:
                out.append(Chunk(
                    text=b.text,
                    metadata=ChunkMetadata(
                        block_type="change",
                        section_path=list(section_path) if policy.section_path else [],
                        block_index=idx,
                        change_author=b.author or None,
                        change_type=b.change_type or None,
                    ),
                ))
        elif bt == "comment" or bt == "CommentBlock":
            if policy.embed_comments and b.text:
                md_c = ChunkMetadata(
                    block_type="comment",
                    section_path=list(section_path) if policy.section_path else [],
                    block_index=idx,
                    change_author=b.author or None,
                )
                md_c.extras["resolved"] = b.resolved
                if b.date:
                    md_c.extras["date"] = b.date
                out.append(Chunk(text=b.text, metadata=md_c))
        elif bt == "section" or bt == "SectionBlock":
            # Recurse with section_path extended by the section's "kind"
            # or by an inferred heading from children.
            label = b.name or b.kind or _section_label(b)
            new_path = section_path + [label] if (policy.section_path and label) \
                else section_path
            out.extend(_flatten_blocks(b.children, policy, new_path, counter))
        else:
            # Unknown block — emit its text if present, drop otherwise.
            if b.text:
                out.append(Chunk(
                    text=b.text,
                    metadata=ChunkMetadata(
                        block_type=bt or "unknown",
                        section_path=list(section_path) if policy.section_path else [],
                        block_index=idx,
                    ),
                ))
    return out


def _section_label(b: "Block") -> str:
    """Best-effort label for a SectionBlock: the first heading child's text.

    Only reached when the section carries neither a name nor a kind.
    """
    for child in b.children:
        if (child.type in ("heading", "HeadingBlock")) and child.text:
            return child.text
    return ""


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

    @staticmethod
    def _normalize(fmt: str) -> str:
        return fmt.lower().lstrip(".")

    def supports(self, fmt: str, operation: str = "parse") -> bool:
        """Check whether ``fmt`` is supported for the given operation.

        Both case-insensitive and tolerant of a leading ``.``::

            f.supports("docx")              # True
            f.supports(".DOCX")             # True
            f.supports("pdf", "generate")   # depends on server
        """
        target = self._normalize(fmt)
        haystack = self.generate if operation == "generate" else self.parse
        return any(self._normalize(x) == target for x in haystack)

    def is_deterministic(self, fmt: str) -> bool:
        """True iff ``fmt`` is parseable without an AI backend.

        A format is deterministic when it is in :attr:`parse` and *not*
        in :attr:`ai_required`. Useful for routing decisions in wrappers
        that want to avoid burning AI quota for Office files.
        """
        if not self.supports(fmt, "parse"):
            return False
        target = self._normalize(fmt)
        return not any(self._normalize(x) == target for x in self.ai_required)


# ── Key management types ──

@dataclass
class Quota:
    requests_per_day: int = 0
    requests_per_month: int = 0
    ai_limit_per_request: int = 0
    fs_limit_per_request: int = 0

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Quota":
        return cls(
            requests_per_day=int(d.get("requestsPerDay", 0)),
            requests_per_month=int(d.get("requestsPerMonth", 0)),
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
    requests_this_month: int = 0
    total_requests: int = 0

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Usage":
        return cls(
            requests_today=int(d.get("requestsToday", 0)),
            requests_this_month=int(d.get("requestsThisMonth", 0)),
            total_requests=int(d.get("totalRequests", 0)),
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
