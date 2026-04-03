# Design: Ollama Model-Aware Prompting for PDF Extraction

**Status**: Planned
**Priority**: High
**Target**: v0.2.0
**Related**: v0.1.0 PDF benchmark results

## Problem

AILANG's PDF extraction pipeline (`direct_ai_parser.ail`) sends identical multimodal requests to all AI models regardless of capability. The request format includes:

1. Base64-encoded PDF data
2. A complex prompt with 5 "CRITICAL RULES"
3. A detailed JSON schema for output format
4. Request to return a JSON array of typed blocks

This works well for large cloud models (Gemini 2.0 Flash scores 92%) but fails completely for local Ollama models:

| Model | Score | Issue |
|-------|-------|-------|
| gemini-2.0-flash | 92% | Works perfectly |
| granite3.2-vision | 0% | Timeouts (120s) — model too slow for full prompt |
| PaddleOCR-VL:0.9b | 2.8% | Returns text but can't produce structured JSON |
| gemma3:12b | 0% | Parse failures — wrong model type |

### Root Causes

1. **Small models can't follow complex instructions** — A 0.9B parameter model can't reliably produce structured JSON arrays with specific field names
2. **Model-specific prompting required** — PaddleOCR-VL expects simple prompts like `"OCR:"`, `"Table Recognition:"`, or `"Formula Recognition:"` (per its documentation)
3. **Timeout issues** — granite3.2-vision (2.4GB) is too slow processing full base64 PDFs with long system prompts within the 120s AILANG timeout
4. **AILANG's AI effect is model-agnostic** — By design, `callJsonSimple(request)` treats all models identically

## Proposed Solutions

### Option A: Two-Stage Pipeline (Recommended)

Split PDF extraction into two stages:

```
Stage 1: Raw OCR (any model, simple prompt)
  Input:  PDF base64 + "Extract all text from this document"
  Output: Plain text string

Stage 2: Structuring (capable model OR heuristics)
  Input:  Plain text from Stage 1
  Output: Structured Block[] array
```

**Advantages:**
- Works with any OCR model (PaddleOCR-VL, granite-vision, etc.)
- Stage 2 can be local heuristics (regex-based heading detection, table detection) — no AI needed
- Decouples OCR quality from JSON formatting ability
- Falls back gracefully: even bad OCR produces searchable text

**Implementation in AILANG:**
```ailang
-- Stage 1: Simple OCR prompt
func ocrExtract(base64Data: string, filepath: string) -> string ! {AI} {
  let request = encode(jo([
    kv("mode", js("multimodal")),
    kv("mimeType", js(pdfMimeType())),
    kv("data", js(base64Data)),
    kv("fileName", js(filepath)),
    kv("prompt", js("Extract all text from this document. Return only the text content."))
  ]));
  call(request)
}

-- Stage 2: Heuristic structuring (pure, no AI needed)
pure func structureText(rawText: string) -> [Block] {
  -- Split into paragraphs, detect headings by formatting, detect tables by alignment
  ...
}
```

### Option B: Model-Aware Prompt Selection

Detect the model provider and use appropriate prompts:

```ailang
func getPrompt(modelName: string) -> string {
  if contains(modelName, "PaddleOCR") then "OCR:"
  else if contains(modelName, "granite") then "Extract text from this document."
  else fullStructuredPrompt()  -- Current complex prompt for capable models
}
```

**Disadvantage:** Requires knowing the model name at prompt time. AILANG's AI effect currently doesn't expose which model is being used to the caller.

### Option C: AILANG Feature Request — Model Capabilities

Request AILANG add model capability metadata to the AI effect:

```ailang
-- Proposed AILANG API
let caps = aiModelCapabilities()  -- Returns {structured_output: bool, vision: bool, ...}
if caps.structured_output
  then callJsonSimple(complexRequest)
  else call(simpleRequest)
```

**Disadvantage:** Requires AILANG language change; longer timeline.

## Recommendation

**Option A (Two-Stage Pipeline)** is the best near-term approach:
- Implementable entirely in AILANG today
- No language changes needed
- Gracefully handles all model tiers
- Heuristic structuring is fast and deterministic
- Cloud models can still use the direct structured path as an optimization

## Implementation Plan

1. Add `ocrExtract()` function to `direct_ai_parser.ail` — simple prompt, returns raw text
2. Add `structureText()` pure function — regex-based heading/table/list detection
3. Add `parsePdfTwoStage()` entry point that chains Stage 1 → Stage 2
4. Keep existing `parsePdf()` as the "capable model" fast path
5. In `main.ail`, choose pipeline based on model name or a `--simple` flag
6. Re-run benchmarks with Ollama models to validate improvement
7. Send AILANG feedback about Option C for future consideration

## Success Criteria

- granite3.2-vision scores >50% on PDF benchmark
- PaddleOCR-VL scores >40% on PDF benchmark
- gemini-2.0-flash maintains >90% (no regression)
- Two-stage adds <5s overhead compared to direct path

## Open Questions

1. Should we detect model tier automatically or require a flag (`--simple`)?
2. How much structuring quality can we get from pure heuristics vs. a second AI call?
3. Should the heuristic structurer be an AILANG module or a Python post-processor?
