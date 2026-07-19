# Référence API

Base URL locale : `http://localhost:8000`. L'interface OpenAPI interactive est disponible sur <http://localhost:8000/docs>.

## Lecture DataHub

| Route | Paramètres | Résultat |
|---|---|---|
| `GET /api/v1/datahub/search` | `query` | Résultat brut de l'outil MCP `search` |
| `GET /api/v1/datahub/schema` | `asset_urn` | Schéma via `list_schema_fields` |
| `GET /api/v1/datahub/lineage` | `asset_urn`, `direction`, `max_hops` (1–5) | Lineage borné via `get_lineage` |

Exemple :

```powershell
Invoke-RestMethod 'http://localhost:8000/api/v1/datahub/search?query=orders'
```

Ces routes ne peuvent appeler que les outils MCP de lecture placés dans l'allowlist. Les outils de mutation restent désactivés.

## Rapport et plan déterministes

### Impact

`POST /api/v1/analyses/impact`

Entrée minimale :

```json
{
  "asset_urn": "urn:li:dataset:(urn:li:dataPlatform:dbt,b2fd91.order_entry_db.order_entry.orders,PROD)",
  "change_type": "ADD_COLUMN",
  "column_name": "lineageguard_demo_note",
  "reason": "Démonstration contrôlée du workflow.",
  "environment": "PRODUCTION",
  "lineage_depth": 2,
  "column_nullable": true
}
```

`change_type` accepte `ADD_COLUMN`, `RENAME_COLUMN`, `CHANGE_COLUMN_TYPE` et `DROP_COLUMN`. Les changements rename/type exigent aussi `new_value` ; les changements autres qu'add exigent `column_name`.

```powershell
$report = Invoke-RestMethod -Method Post `
  -Uri 'http://localhost:8000/api/v1/analyses/impact' `
  -ContentType 'application/json' `
  -InFile .\examples\drop-column-orders.json
```

La réponse contient `evidence_bundle`, `impacted_assets`, `risk_assessment`, `missing_metadata` et `confidence`. `impact_type=POTENTIAL_SCHEMA_IMPACT` signale une dépendance démontrée, pas une rupture de schéma déjà prouvée.

### Plan

`POST /api/v1/remediations/plan` reçoit le rapport inchangé :

```powershell
$plan = Invoke-RestMethod -Method Post `
  -Uri 'http://localhost:8000/api/v1/remediations/plan' `
  -ContentType 'application/json' `
  -Body ($report | ConvertTo-Json -Depth 30)
```

Les champs `execution_status` des plans et rollbacks restent `NOT_EXECUTED`. Une compatibilité non démontrée par contrat/consommateur est renvoyée comme `null`, jamais comme un `true` artificiel.

## Critique et juges

### Critique NVIDIA

`POST /api/v1/debates/critique` reçoit :

```json
{ "impact_report": { "...": "rapport" }, "remediation_plan": { "...": "plan" } }
```

La réponse contient `provider`, `model`, `summary`, `issues`, `recommended_revisions` et `confidence`. C'est un avis ; aucune modification du plan n'est effectuée.

### Double revue

`POST /api/v1/judges/evaluate` reçoit le même paquet avec `repair_cycles` :

```powershell
$judgingRequest = @{
  impact_report = $report
  remediation_plan = $plan
  repair_cycles = 0
} | ConvertTo-Json -Depth 30

$judging = Invoke-RestMethod -Method Post `
  -Uri 'http://localhost:8000/api/v1/judges/evaluate' `
  -ContentType 'application/json' `
  -Body $judgingRequest
```

La réponse contient un `run_id` serveur et :

- `deterministic_validation` (Gate 0) ;
- `openai_verdict` et `groq_verdict` ;
- scores, erreurs, réparation, `audit_rationale` et confiance ;
- `aggregate_decision`.

`GET /api/v1/judges/history?limit=12` affiche des résumés persistants, pas les prompts ni les secrets.

## HITL write-back

Les routes suivantes restent protégées par le statut de la revue et les contrôles d'idempotence.

| Route | Corps | Règle |
|---|---|---|
| `POST /api/v1/writebacks/prepare` | `run_id`, `idempotency_key` | Requiert double PASS |
| `GET /api/v1/writebacks/{run_id}` | — | Lit proposition/snapshot |
| `GET /api/v1/writebacks/{run_id}/audit` | — | Lit audit ordonné |
| `POST /api/v1/writebacks/{run_id}/approve` | `decision`, `comment`, `idempotency_key` | Décision humaine |
| `POST /api/v1/writebacks/{run_id}/rollback` | `decision=APPROVE_ROLLBACK`, commentaire, clé | Seulement après write-back terminé |

Exemple de préparation :

```powershell
$proposal = Invoke-RestMethod -Method Post `
  -Uri 'http://localhost:8000/api/v1/writebacks/prepare' `
  -ContentType 'application/json' `
  -Body (@{ run_id = $judging.run_id; idempotency_key = [guid]::NewGuid().ToString() } | ConvertTo-Json)
```

Une approbation avec `DATAHUB_WRITEBACK_ENABLED=false` échoue volontairement avant toute mutation. C'est le comportement sécurisé attendu.
