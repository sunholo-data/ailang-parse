"""LiteParse with OCRia-nano-1 for OfficeDocBench.

Requires: everything the LiteParse adapter needs, liteparse >= 2.21, and the
model on the machine: `lit models pull ocria-nano` (about 75 MB, CPU only).

OCRia-nano-1 is LlamaIndex's 8.1M-parameter OCR and layout model. In LiteParse
it adds LayoutNet, a table/layout model that runs on every page, including the
born-digital pages LiteParse renders from Office files; OCR itself runs only
where a page has no usable text layer. Its tables arrive as ``merged_table``
blocks and its page furniture as ``page_header`` / ``page_footer``; the shared
mapping in liteparse_adapter.py handles both.

The model weights are under the OCRia-nano-1 Model License (modified Open
RAIL-M), which permits evaluation and benchmarking.
"""

from __future__ import annotations

from typing import Any

from .liteparse_adapter import LiteParseAdapter


class LiteParseOCRiaAdapter(LiteParseAdapter):
    OCR_BACKEND = "ocria-nano"

    def name(self) -> str:
        return "LiteParse + OCRia-nano-1"

    def model_version(self) -> str:
        from liteparse import models

        for model in models.list():
            if model.name == "ocria-nano" and model.complete:
                return model.version
        raise RuntimeError("OCRia-nano-1 not installed: lit models pull ocria-nano")

    def version(self) -> str:
        try:
            return f"{super().version()}+ocria-nano@{self.model_version()}"
        except Exception:
            return "unknown"

    def provider_config(self) -> dict[str, Any]:
        return {"ocr_backend": self.OCR_BACKEND, "model": self.model_version()}
