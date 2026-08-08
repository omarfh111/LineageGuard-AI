# Judge testing guide

This guide provides a credential-free path through the public deployment.
It is designed for the **Agents That Do Real Work** submission and avoids
requiring a DataHub login, model key, or reviewer secret.

## Start here

Open [https://lineageguard.hackdev.tech](https://lineageguard.hackdev.tech).
The **Health** view should show the current availability of DataHub, Qdrant,
and optional model providers. Availability is not an approval or an evidence
claim: live model requests may vary with the external providers.

## Suggested public checks

| Area | Action | Expected safe outcome |
|---|---|---|
| Cartography | Open **Cartography** and wait for `READY`. Search `orders`; select a node. | A server-cached 3D catalog remains visible while refresh is non-blocking. The selection shows platform, relationship count, and exact identity. |
| Agentic RAG | Ask: `What is the schema of the Snowflake orders dataset? List the field names and types.` | The assistant resolves an exact Snowflake target, retrieves live MCP schema evidence, and returns `VERIFIED` only when claim checks pass. |
| Ambiguity handling | Ask: `Show the downstream lineage of the orders dataset.` | The assistant asks for a platform or exact asset instead of guessing between duplicate `orders` assets. |
| Safe limitation | Ask: `What is the schema of lineageguard_eval_no_such_asset_7f3c?` | The result is a safe limitation; it must not substitute a real unrelated asset or call schema/lineage tools for one. |
| Impact analysis | Open **New analysis** and submit a nullable `ADD_COLUMN` with a unique test name. | The application returns a read-only evidence dossier, multi-hop impact information, remediation, and rollback guidance. It does not change the schema or source data. |
| Review | From a completed report, run the advisory critic and independent judges when their providers are available. | PASS/PASS permits a proposal; PASS/FAIL, FAIL/FAIL, or an unavailable judge stays blocked or requires repair. No result is silently promoted to PASS. |
| Activity | Open **Activity** after an analysis/review. | The state history and rationale are visible for auditing. |

## Governed write-back boundary

The public application deliberately does not expose the local reviewer
capability. The capability is a server-side security boundary, not a public
test password. Without it, a verified report remains read-only.

When the controlled path is enabled in a disposable DataHub environment, a
single approved Analysis document can be written after all of the following:

1. a server-owned immutable analysis snapshot exists;
2. both independent judges pass;
3. the feature flags are enabled;
4. an authorized human enters the local reviewer capability and a rationale;
5. the reviewer explicitly approves the in-page HITL confirmation.

The write is idempotent and is post-write verified through DataHub MCP. It is
limited to an Analysis document; LineageGuard never writes warehouse rows,
schemas, lineage, dbt models, or dashboards. The complete sanitized proof,
including compensation to `ROLLED_BACK`, is documented in
[live-writeback-proof.md](live-writeback-proof.md) and the dated evaluation
reports.

## Troubleshooting

If the public instance is starting, wait for the Health page to settle and
reload once. A provider timeout is reported explicitly and fails closed; it is
not evidence that the DataHub-based deterministic safety controls were bypassed.
For a local reproduction, follow the [runbook](runbook.md).
