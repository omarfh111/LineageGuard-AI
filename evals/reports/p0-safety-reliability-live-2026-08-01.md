# P0 safety and reliability — live validation (2026-08-01)

## Scope

This run validates bounded conversation-memory expiry, browser memory deletion,
typed chat routing, fail-closed write-back behavior, and the local reviewer
capability. No DataHub mutation was authorized or attempted.

## Automated validation

| Check | Result |
|---|---:|
| Backend suite | 157 passed, 4 opt-in live tests skipped |
| Frontend unit tests | 11 passed |
| TypeScript + Vite production build | PASS |
| Focused adversarial backend tests | PASS |

Adversarial coverage includes expired turns plus active asset, SQLite shared
memory connections, hostile CORS origin, missing/weak/wrong reviewer
capability, disabled write routes, conflicting schema-change verbs, and a
DataHub document mutation that must not be misclassified as a column change.

## Live container/API evidence

| Check | Observed result | Verdict |
|---|---|---|
| Docker services | backend, frontend, Qdrant healthy | PASS |
| Qdrant snapshot | 1,190 / 1,190 assets; query available | PASS |
| Memory DELETE preflight | `200`; local origin; `DELETE` allowed | PASS |
| Reviewer header preflight | custom capability header allowlisted | PASS |
| Memory deletion | empty six-turn session status returned | PASS |
| Current write-back configuration | `reviewer_unconfigured`; POST rejected `503` before proposal lookup | PASS (fail closed) |
| `ADD_COLUMN` chat route | typed action, one resolved target, verified handoff | PASS |
| `RENAME_COLUMN` chat route | typed action, one resolved target, verified handoff | PASS |
| `CHANGE_COLUMN_TYPE` chat route | typed action, one resolved target, verified handoff | PASS |
| `DROP_COLUMN` chat route | typed action, one resolved target, verified handoff | PASS |

The first live routing attempt exposed an asset-extraction defect: rename and
type requests could treat the proposed new column value as the dataset search
term. The implementation was patched to prefer the noun explicitly qualified
as a dataset/table/asset, regression-tested, rebuilt, and rerun. The table above
contains the successful post-fix results.

## Residual operational rule

Keep write-back disabled for normal use. For the separate disposable mutation
proof, configure a random `LOCAL_REVIEWER_CAPABILITY` of at least 24 characters,
rebuild the backend, enter the value manually in the local UI, and retain the
existing double-PASS plus explicit human-approval procedure.
