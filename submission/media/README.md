# Devpost media manifest

This folder contains the final **15-item** Devpost gallery. Every asset is
below the 5 MB upload limit. The cards and GIF are 3:2; the raw product
captures retain their original browser framing so the interface remains
legible. Upload them in the order below.

| Order | File | Caption for Devpost |
|---:|---|---|
| 1 | `06-lineageguard-cover.png` | LineageGuard AI protects data decisions with live metadata, lineage, independent review, and human control. |
| 2 | `07-agentic-rag-mcp-architecture.png` | The Agentic RAG + MCP architecture: retrieval and governed tools converge on verified reasoning. |
| 3 | `08-home-overview.jpg` | Product overview: evidence-first DataHub agents, bounded catalog, and professional validation metrics. |
| 4 | `01-catalog-3d-ready.jpg` | Live 3D cartography of the DataHub catalog, colored by platform with lineage relationships. |
| 5 | `10-cartography-explorer-card.jpg` | Catalog exploration card: the shared cache keeps the 3D map responsive. |
| 6 | `02-agentic-rag-verified.jpg` | A verified Agentic RAG response with its exact Snowflake target and MCP schema evidence. |
| 7 | `11-verified-assistant-card.jpg` | Qdrant retrieval is always rechecked against live DataHub evidence before facts are presented. |
| 8 | `09-change-analysis-intake.jpg` | Typed, read-only change intake for an impact assessment. |
| 9 | `04-impact-analysis-read-only.jpg` | Deterministic impact dossier: risk, blast radius, remediation, and rollback plan before any mutation. |
| 10 | `13-impact-analysis-card.jpg` | Impact analysis explainer card. |
| 11 | `03-independent-judge-states.jpg` | Activity history displays PASS/PASS, PASS/FAIL, and FAIL/FAIL review outcomes. |
| 12 | `05-independent-judge-disagreement.jpg` | Independent reviewers can disagree; the reason is surfaced rather than silently auto-approved. |
| 13 | `12-independent-review-card.jpg` | Independent review explainer card. |
| 14 | `14-governed-writeback-card.jpg` | The controlled HITL path allows only a reviewed Analysis document, never a schema or data mutation. |
| 15 | `15-lineageguard-feature-tour.gif` | Animated five-step tour: home, cartography, verified assistant, independent review, and HITL. |

## Regeneration

`scripts/render_submission_media.py` creates cards 10–14 and the GIF from
the checked-in source captures. It never alters the source captures. Run:

```powershell
python scripts/render_submission_media.py
```

Generated visual concepts (`06` and `07`) complement the authentic product
captures; they do not represent an unimplemented interface or capability.
