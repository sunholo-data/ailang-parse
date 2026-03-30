# OmniDocBench Results: AILANG Parse + Gemini 2.0 Flash

**Date**: 2026-03-11
**Dataset**: OmniDocBench Demo (18 page images)
**Model**: gemini-2.0-flash (via AILANG AI effect)
**Pipeline**: AILANG parseDocumentImage → JSON blocks → markdown adapter

## Summary Scores

| Category | Metric | Score | Direction |
|----------|--------|-------|-----------|
| Text Block | Edit Distance (page avg) | **0.186** | lower = better |
| Table | TEDS | **0.787** | higher = better |
| Table | TEDS (structure only) | **0.848** | higher = better |
| Table | Edit Distance (page avg) | **0.167** | lower = better |
| Reading Order | Edit Distance (page avg) | **0.170** | lower = better |

## Text Block Breakdown

| Attribute | Edit Distance |
|-----------|--------------|
| English | 0.211 |
| Chinese | 0.183 |
| Mixed en/ch | 0.044 |
| Single column | 0.154 |
| Double column | 0.100 |
| Three column | 0.120 |
| PPT2PDF | 0.015 (best) |
| Newspaper | 0.482 (worst) |

## Table TEDS Breakdown

| Attribute | TEDS | TEDS Structure |
|-----------|------|----------------|
| Notes | 0.966 | 1.000 |
| Exam paper | 0.941 | 0.941 |
| Mixed en/ch | 0.956 | 1.000 |
| Book | 0.871 | 0.878 |
| Magazine | 0.847 | 0.854 |
| Research report | 0.730 | 0.800 |
| Academic lit | 0.705 | 0.943 |
| English | 0.632 | 0.715 |
| Colorful textbook | 0.250 | 0.260 (worst) |

## Reading Order Breakdown

| Attribute | Edit Distance |
|-----------|--------------|
| PPT2PDF | 0.000 (perfect) |
| Exam paper | 0.000 (perfect) |
| Notes | 0.000 (perfect) |
| Mixed en/ch | 0.000 (perfect) |
| English | 0.063 |
| Single column | 0.071 |
| Book | 0.167 |
| Colorful textbook | 0.111 |
| Double column | 0.256 |
| Academic lit | 0.219 |
| Newspaper | 0.480 (worst) |

## Notes

- All extraction was done via AILANG's AI effect (no Python workarounds)
- Markdown conversion was done in Python adapter (planned for AILANG migration in v0.3.0)
- Colorful textbook and newspaper layouts are weakest areas — these have complex visual layouts
- Table structure recognition is strong (0.848 TEDS structure) but content accuracy varies by language
