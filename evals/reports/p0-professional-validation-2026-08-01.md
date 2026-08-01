# P0 professional validation evidence — 2026-08-01

## Scope and boundaries

This run validates browser E2E coverage, 3D-cache recovery, immutable workflow
reload, and regenerated evaluation evidence. The browser/API scenarios perform
DataHub reads and schema-change analysis only. They do not call write-back.

The benchmark uses a local DataHub `showcase-ecommerce` catalog, persistent
Qdrant metadata, and the configured economical response model. Conversation
memory is disabled for every benchmark case.

## Executed validation

| Layer | Result | Evidence |
|---|---:|---|
| Backend suite | 159 passed, 4 skipped | Full `backend/tests` run outside the restricted Windows temp sandbox |
| Frontend unit/contracts | 16 passed | Includes server-null canonicalization and cache/reload helpers |
| Frontend production build | PASS | TypeScript + Vite; 442 modules transformed |
| Deterministic Chromium E2E | 3 passed | Non-blanking recovery, immutable reload, tampered-pointer rejection |
| Live Chromium E2E | 1 passed | 1,191-asset cache remained visible; live analysis survived reload |
| Live API reload | PASS | Report and plan byte-equivalent after GET by run UUID; status `NOT_EXECUTED` |
| Offline contract dataset | 20/20 | Five cases for each supported change type |
| Live Agentic RAG | 30/30 completed, PASS | 22 manually reviewed retrieval-ground-truth cases |

The live browser test explicitly confirmed that a refresh retained all 1,191
visible nodes while the cache state was `REFRESHING`. It then created a new
read-only analysis through the UI, reloaded the page, restored the same server
run UUID, and displayed that judge and approval authority had been reset.

## Live Agentic RAG metrics

| Metric | Result |
|---|---:|
| Precision@6 | 0.902 |
| Recall@6 | 0.909 |
| MRR@6 | 0.909 |
| NDCG@6 | 0.909 |
| Result diversity@6 | 0.778 |
| Router accuracy | 1.000 |
| MCP tool-selection accuracy | 1.000 |
| Verification accuracy | 1.000 |
| Target-resolution accuracy | 1.000 |
| Verified citation coverage | 1.000 |
| Unsupported-claim block rate | 1.000 |
| Claim-support coverage | 0.963 |
| Unsupported-claim escape rate | 0.000 |
| Fully supported verified-answer rate | 1.000 |
| Mean / p50 / p95 latency | 6,951.8 / 5,885.9 / 9,516.9 ms |
| Tokens / estimated cost | 4,693 / USD 0.0039472 |

All professional thresholds passed. Lower claim-support coverage is expected
because negative and ambiguous cases deliberately extract unsupported candidate
claims and must block them; the escape rate of `0.000` is the safety criterion.

## Versioned provenance

- Live evidence: [`../evidence/lineageguard-professional-agentic-rag-v1-1.1.0-live-agentic-rag-v2-20260801T154438Z-a00c0ba10ca0.json`](../evidence/lineageguard-professional-agentic-rag-v1-1.1.0-live-agentic-rag-v2-20260801T154438Z-a00c0ba10ca0.json)
- Offline evidence: [`../evidence/lineageguard-eval-v1-1.1.0-offline-contract-v2-20260801T154445Z-aab31f9952c5.json`](../evidence/lineageguard-eval-v1-1.1.0-offline-contract-v2-20260801T154445Z-aab31f9952c5.json)
- Live dataset SHA-256: `175bbcd8b54fa0d528dfc3d3dd46d7bbde7685e8fedb866af927446c4751f14a`
- Live source SHA-256: `a00c0ba10ca0548db62951c3a072397ea0ec824b217f58add57a818cc75e83f7`
- Offline dataset SHA-256: `dbfa2e653efa6263f7ede406a3f4768d4109e9ba00aea2e99248fcea8f84801d`
- Offline source SHA-256: `aab31f9952c5a6bb1e1f2ee3e063bf1f2a2d7045687ca54f7ba0469393666884`
- Base Git revision at measurement time: `db2372ac0197931797b4de4ce8502ff2a752d7ca`
- Tracked working-patch SHA-256 at live measurement: `42fa411756466414ac830ec354502f0ec8d214281c2db1e13e7db1d05d1e3fcb`

The evidence manifest marks the working tree dirty because validation occurred
before the final commit. Dataset, source, and patch hashes identify the measured
state without claiming it was already a tagged release.
