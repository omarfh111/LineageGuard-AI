# Problem and resolution log

This log records the most important engineering failures encountered while
building LineageGuard, the implemented correction, the evidence used to
validate it, and the remaining operational boundary. It is intentionally more
specific than a marketing changelog.

## Reliability and data-flow corrections

| Symptom | Root cause | Correction | Validation | Residual boundary |
|---|---|---|---|---|
| Health always showed DataHub and models as `not_configured` | Static bootstrap response | Runtime-derived, non-secret DataHub/Qdrant/write-back/demo/provider readiness | `test_health.py`; `/api/v1/health` contract | Configuration readiness is not a live provider probe |
| Catalog repeatedly ran a full traversal | Volatile graph/enrichment data influenced change detection | Separate stable root fingerprint, two equal changed observations, and bounded rotating exact probes | Cache fingerprint, unchanged-poll, change-probe, and live E2E tests | External changes are eventually detected by polling, not webhooks |
| Graph went to zero or disappeared during refresh | In-progress graph replaced the last complete graph | Preserve previous generation and atomically swap only a complete successful graph | `test_catalog_cache.py`; Playwright non-blanking refresh scenario | Cache is in memory and restarts with the backend |
| Graph layout jumped on every browser poll | Recreated node objects lost force-engine positions | Reconcile unchanged payloads and preserve node coordinates; accept real topology changes | `recovery.test.ts` graph-stability cases | A true topology change may legitimately move nodes |
| Stuck MCP work starved chat and cache | Session startup/tool/teardown lacked one complete deadline; lineage tasks queued too broadly | Per-session MCP deadline, whole-refresh watchdog, chunked concurrency, and total chat deadline | MCP timeout/concurrency/cache watchdog tests | Correct timeout values still depend on local hardware and DataHub load |
| Re-indexing disabled chat | Index state did not distinguish first build from replacement build | Keep active alias queryable and build a validated isolated snapshot | RAG index status tests and acceptance case `RAG-07` | First-ever index must finish before vector retrieval is available |
| Removed DataHub assets remained in Qdrant | In-place upsert could not remove absent records safely | Deterministic point IDs, isolated collection, exact unique-count validation, atomic alias swap, old snapshot cleanup | `test_rag_index.py`; offline stale-candidate cases | Index freshness follows successful explicit ingestion, not every DataHub event |

## RAG, MCP, and agent corrections

| Symptom | Root cause | Correction | Validation | Residual boundary |
|---|---|---|---|---|
| Generic sentences produced poor DataHub search terms | Conversation words were treated as asset terms | Normalize stop words and preserve business identifiers/platform qualifiers in both model and fallback plans | Planner/search-term adversarial tests | Unusual organization-specific aliases may still require an explicit URN |
| `orders` schema used `order_details` evidence | Similar candidate replaced the requested target | Resolve platform + exact name, lock the target URN, filter evidence and model sources by target | Exact Snowflake schema live proof; target-lock tests | Unqualified duplicate names remain intentionally ambiguous |
| Missing asset retry searched real unrelated assets | Similar Qdrant candidates were admitted after `NOT_FOUND` | Treat target-specific `NOT_FOUND` as terminal and prohibit schema/lineage calls | Negative fixture `lineageguard_eval_no_such_asset_7f3c` | A misspelled asset must be corrected by the user |
| Qdrant was described as hybrid but did not materially affect confirmation | Primary search path ignored vector candidates | Allow up to a bounded number of strong candidate labels to guide new MCP searches; accept only exact live URN rediscovery | P0 correctness hybrid proof and stale/weak/ambiguous candidate tests | Qdrant remains candidate context, never evidence |
| Multi-hop impact collapsed to source/target shortcuts | Direct lineage result lacked an independently validated simple path | Call `get_lineage_paths_between`, validate endpoints/hops/acyclicity, and bind each path to evidence | 35 exact paths in the dated live proof; path-tamper tests | Missing exact MCP paths fail closed and may reduce the report |
| Citation presence allowed unsupported prose | Verification operated at response level | Extract public factual claims and require target-compatible live anchors per claim | Claim-support tests and professional unsupported-claim metrics | Natural-language claim extraction is conservative and may produce safe limitations |
| `COMPLETED` badge implied factual approval | Execution state and business outcome shared visual language | Expose `VERIFIED`, `LIMITED`, `ACTION_REQUIRED`, and governed workflow states | Frontend response-state tests and acceptance matrix | Low-level stage traces may still say `COMPLETED` to mean “stage ran” |
| Memory resolved pronouns but contaminated independent tests | Bounded context was reused across scenarios | Keep six-turn product memory, store verified active asset separately, add TTL/clear/isolation, and disable/clear for benchmarks | Memory expiry, deletion, CORS, and cross-session tests | Memory is local SQLite, not user-account identity or evidence |
| Chat change routing chose a proposed column value as the dataset | Asset extraction favored nearby nouns | Prefer nouns explicitly qualified as dataset/table/asset and transfer one server-owned verified handoff | Live routing proof for all four change types | Ambiguous assets still require user selection |
| Choosing an ambiguous `orders` card replayed text but lost the selected asset | The browser reformulated a question instead of binding its prior exact live target | Transmit `selected_asset_urn`, preserve the original intent, lock the URN, and permit fresh MCP reads only for that target | 2026-08-08 local lineage selection: Snowflake `ORDERS` returned `VERIFIED` with lineage evidence | A manually fabricated/invalid URN returns a safe limitation and cannot fall back to another asset |

## Review and write-back corrections

| Symptom | Root cause | Correction | Validation | Residual boundary |
|---|---|---|---|---|
| NVIDIA returned prose or invalid structured critique | OpenAI-compatible models vary in JSON and reasoning behavior | Disable reasoning, stream bounded output, normalize known wrappers, validate with Pydantic, filter evidence IDs, and allow one schema-only repair within the original deadline | Nine focused critic tests; live Nemotron contract rehearsal | Provider/model availability and latency can change without a code release |
| NVIDIA GLM call exceeded the interactive budget | Shared endpoint/model latency exceeded the 90-second contract | Recommend rehearsed `nvidia/nemotron-3-nano-30b-a3b` for the advisory demo; expose timeout as failure | Dated successful 2.92-second contract run; two GLM timeouts recorded | The critic is optional and never grants authority |
| Earlier Qwen NVIDIA names returned HTTP 410 | Provider retired the model endpoints | Remove retired defaults and require account/model availability verification | Provider error classification and troubleshooting procedure | Model catalogs are external and time-varying |
| Groq rejected strict schema or returned unavailable | Structured mode support, quota, and uptime vary | JSON Schema first, JSON-object fallback through the same strict parser, bounded retry, unavailable verdict | Judge parser/aggregation tests | One unavailable judge prevents double PASS |
| Browser could replace the report sent to judges | Report body was client-controlled | Persist immutable server analysis and let judges accept only `analysis_run_id`; Gate 0 reconstructs facts and risk | Snapshot, judging tamper, and workflow reload tests | SQLite implementation is single-node |
| Concurrent approvals risked duplicate documents | Remote API lacks a LineageGuard idempotency token | Durable idempotency/report binding, `BEGIN IMMEDIATE`, CAS operation ownership, and one automatic claimant | Concurrent prepare/approve tests and live proof | Guarantee is at-most-one automatic attempt, not distributed exactly-once delivery |
| Lost write response could be retried blindly | Remote success was unknowable after transport failure | Enter `WRITEBACK_UNCERTAIN`; block retry until exact title/related-asset MCP reconciliation | Ambiguous create and unrelated-document reconciliation tests | A human must inspect and reconcile the remote system |
| Compensation could affect the wrong document or repeat unsafely | Rollback target was not strictly bound | Persist exact created URN, require separate approval, and restrict compensation/retry to that URN | Concurrent/ambiguous compensation tests and `ROLLED_BACK` live proof | Compensation supersedes the Analysis document; it does not erase audit history |
| Reviewer secret in `.env` still produced an invalid-capability UI error | Backend had not been recreated, browser value differed, or global mutation flags were confused with the scoped writer | Require a 24+ character server value, rebuild backend, enter the identical tab-only value, expose safe write-back health | Reviewer capability/CORS/disabled-route tests | The local capability is a demo control, not production identity/RBAC |
| A saved Analysis document was incorrectly reported as uncertain | Post-write verification queried the document as a related-document host instead of its governed asset | Re-read the target asset through MCP and require exact related-document URN/title evidence before `COMPLETED` | New local controlled write reached `COMPLETED`, then `ROLLED_BACK` after separate compensation approval | Document-only write-back remains opt-in and should use a disposable/controlled DataHub environment |
| Native browser confirmations blocked repeatable UI validation | `confirm()` and `prompt()` interrupted browser automation and obscured the action boundary | Replace approval, rollback, and reconciliation dialogs with explicit in-page panels | 2026-08-08 browser HITL path showed confirm → `COMPLETED` → separate confirm → `ROLLED_BACK` | The UI does not replace server-side reviewer capability or explicit human approval |
| Periodic catalog probes showed timeout errors even while a complete graph remained usable | Non-critical background watch errors were exposed like a failed catalog refresh | Keep the healthy graph `READY`, clear the user-facing fatal error, and apply capped exponential backoff to the next watch attempt | Cache timeout/backoff unit test and local browser cache remained usable during enrichment | A prolonged DataHub outage still delays detection of external changes |
| Judge cards could appear uniformly approving during a demo | No visible replayable disagreement example documented the distinct review roles | Add high-criticality identifier-removal and incompatible-type scenarios with explicit factual/safety rejection reasons | 2026-08-08 local PASS/PASS, PASS/FAIL, and FAIL/FAIL browser runs | External provider availability can still yield fail-closed unavailable states |

Only `DATAHUB_WRITEBACK_ENABLED=true` and a strong
`LOCAL_REVIEWER_CAPABILITY` are needed to opt into the governed document proof.
Keep global `DATAHUB_MUTATIONS_ENABLED` and `TOOLS_IS_MUTATION_ENABLED` false;
LineageGuard enables the single document tool only inside the separately
scoped writer subprocess after all gates pass.

## Delivery and documentation corrections

| Symptom | Correction | Evidence |
|---|---|---|
| Linux CI could not resolve `./ux.css` from `App.tsx` | Corrected the tracked stylesheet import/path and retained the Vite build gate | GitHub Actions frontend job |
| UI had duplicate application/navigation concepts | Active entry point uses one six-view shell and one contextual governed-review continuation | Frontend route/navigation tests and manual browser inspection |
| Technical documentation mixed old and current claims | README now distinguishes current code, dated evidence, optional integrations, historical reports, and owner-only submission actions | Documentation map, report hashes, and this log |
| A five-minute live script did not satisfy the Devpost video limit | Added a 2:40–2:55 submission storyboard while retaining the longer operator demo | [Submission checklist](submission-checklist.md) |

## Evidence index

- [P0 professional validation — 2026-08-01](../evals/reports/p0-professional-validation-2026-08-01.md)
- [P0 correctness validation — 2026-08-01](../evals/reports/p0-correctness-live-2026-08-01.md)
- [P0 safety and reliability — 2026-08-01](../evals/reports/p0-safety-reliability-live-2026-08-01.md)
- [Professional acceptance test plan](acceptance-test-plan.md)
- [Secure HITL write-back](hitl-writeback.md)
- [Live write-back proof](live-writeback-proof.md)
- [Troubleshooting](troubleshooting.md)

Historical reports are preserved. A fix verified by unit tests is not presented
as a new live-provider or live-mutation result until a new dated evidence file
is generated.
