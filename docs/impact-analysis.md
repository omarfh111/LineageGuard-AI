# Deterministic impact analysis

`POST /api/v1/analyses/impact` accepts a validated `ChangeRequest`, reads the schema and downstream lineage through the DataHub MCP bridge, and returns an evidence-backed `ImpactReport`.

It performs no mutation, does not call an LLM, and does not produce a remediation plan.

## Risk calculation

The score follows the weights in the project specification:

```text
30% change severity + 30% blast radius + 20% asset criticality
+ 10% cross-platform impact + 10% metadata uncertainty
```

The severity values are fixed: nullable add `10`, required add `35`, rename `60`, type change with unknown or caller-declared compatibility `50`, explicitly incompatible type change `75`, and drop `90`. A caller-declared compatibility flag never becomes a compatibility conclusion in the remediation plan without downstream contract evidence.

For this MVP, blast radius is `10 × unique downstream assets`, capped at `100`; cross-platform impact adds `25` per platform beyond the first; and uncertainty is the percentage of impacted assets missing an owner or platform. Criticality is inferred from DataHub tags (`critical`, `gold`, or `authoritative`), otherwise it is `MEDIUM`. These deterministic mappings are documented here because the specification supplies the weights but not their normalization.

## Run the sample

With DataHub and the LineageGuard backend running:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/analyses/impact `
  -ContentType 'application/json' `
  -InFile .\examples\drop-column-orders.json
```

Every entry in `impacted_assets` includes an `evidence_ids` reference into `evidence_bundle.items`.

Before scoring, the analyzer validates the requested change against the live
schema: duplicate adds, case-only renames, rename collisions, unchanged types,
and type changes without a current DataHub type are rejected. Direct lineage
uses the observed source/target edge. Every result with `degree > 1` is expanded
through `get_lineage_paths_between`; only an exact, simple, hop-consistent path
is admitted to the report and Gate 0 reconstructs the same binding before any
judge runs.
