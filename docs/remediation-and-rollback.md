# Remediation and business rollback

`POST /api/v1/remediations/plan` transforms a validated Phase 2 `ImpactReport` into a deterministic `RemediationPlan`.

The endpoint does not execute SQL, dbt, warehouse migrations, DataHub mutations, or rollback operations. Both the plan and its business rollback use `execution_status: NOT_EXECUTED`.

Each plan includes the required migration order, compatibility assessment, deprecation guidance, downstream tests, owners to notify, deployment and stop conditions, plus a rollback proposal with triggers, preservation, reversal, dependency restoration, tests, owners, and success criteria.

## Three reproducible scenarios

The change requests are in [examples](../examples/):

- `drop-column-orders.json`
- `rename-column-orders.json`
- `change-column-type-orders.json`

Generate an evidence-backed report first, then submit that report unchanged to the planning endpoint:

```powershell
$report = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/analyses/impact `
  -ContentType 'application/json' `
  -InFile .\examples\drop-column-orders.json

$planBody = $report | ConvertTo-Json -Depth 20
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/remediations/plan `
  -ContentType 'application/json' `
  -Body $planBody
```
