# Reliable five-minute demonstration

This is the judge-facing path. It demonstrates real DataHub reads, hybrid retrieval, deterministic impact analysis, independent review controls, and safe human approval without depending on an unprepared external provider.

This script is for a live walkthrough with questions. It is **not** the
Devpost video script: the official submission video must be under three
minutes. Use the [2:40–2:55 submission storyboard](submission-checklist.md#under-three-minute-video-storyboard)
for the recorded entry.

## Before the clock starts

1. Start DataHub and LineageGuard. Do not restart either stack during the demo.
2. Load the showcase datapack and complete one Qdrant indexing run before the audience arrives.
3. Run:

   ```powershell
   .\scripts\demo-preflight.ps1
   ```

4. Continue only when it prints `DEMO READY`. Optional providers may be `DISABLED`; the UI will disable their buttons and the core read-only path remains valid. `CONFIGURED` is not a live-provider guarantee.
5. Keep `DATAHUB_WRITEBACK_ENABLED=false` for the normal demonstration. Use the isolated write-back proof only when a disposable mutation has been explicitly authorized.

The preflight never reads or prints credentials. Provider readiness means that credentials and a model are configured; only a successful provider request proves runtime availability.

## Timed path

### 0:00–0:35 — Establish trust

- Open **Health**.
- Show API, DataHub, Qdrant, and the per-role provider readiness cards.
- State the invariant: unavailable provider actions are disabled, and configuration is not presented as proof of a successful call.

### 0:35–1:20 — Show the live metadata graph

- Open **Cartography**.
- Show the non-zero asset and relation counts, then hover and select one `orders` node.
- Point out its exact URN, platform, type, and lineage. Do not press refresh: the backend already owns and polls the cache.

### 1:20–2:35 — Ask a professionally scoped question

- Open **Assistant** and ask:

  `What is the schema of the Snowflake orders dataset? List the field names and types.`

- Show the resolved target, live MCP citations, claim coverage, and public agent trace.
- If the answer is `LIMITED`, explain that the verifier failed closed; do not improvise an unsupported answer. Use the direct analysis path for the rest of the demo.

### 2:35–3:40 — Analyze a real change safely

- Open **New analysis**.
- Keep the known showcase `orders` URN or use the verified assistant handoff.
- Choose **Add a column**, use a unique nullable name such as `lineageguard_demo_20260801_1530`, and give a concrete reason.
- Run the analysis and show blast radius, evidence count, risk, and the non-executed remediation plan.
- Continue to **Governed review**. Reloading the page is safe: only the immutable server analysis is restored; judge and approval authority are not.

### 3:40–4:35 — Demonstrate bounded external review

- Show the deterministic evidence and plan first.
- Run NVIDIA only if it is `CONFIGURED` **and** the same model completed a successful rehearsal. It cannot mutate the report.
- Run the independent judges only when both OpenAI and Groq are `CONFIGURED` and rehearsed. If either is disabled, show the disabled action and explain the safe degradation instead of making a failing request.
- A provider timeout, `NEEDS_REPAIR`, or `AWAITING_HUMAN` is a governed outcome, not permission to bypass the gate.

### 4:35–5:00 — Close on human control

- With normal demo settings, show that write-back is disabled and the verified result remains read-only.
- Explain that a real write requires double PASS, the local reviewer capability, an idempotency key, explicit approval, and an auditable compensation path.
- End on the result: LineageGuard performs evidence-backed work while refusing unsupported facts and unauthorized writes.

## Devil's-advocate failure matrix

| Failure before/during demo | Expected behavior | Recovery |
|---|---|---|
| DataHub is unavailable | Preflight fails; do not start the clock | Repair DataHub, then rerun preflight |
| Catalog refresh is running | Existing graph remains visible | Show current graph; do not request another refresh |
| Qdrant index is absent | Preflight fails the RAG path | Index once before the audience arrives |
| Chat provider is unavailable | Assistant may fail closed | Use direct analysis; do not claim a verified chat answer |
| NVIDIA is unavailable | Critique button is disabled | Skip the optional advisory step |
| One final judge is unavailable | Combined judge action is disabled | End with deterministic read-only analysis |
| Provider fails after preflight | Inline error, no authority granted | Explain bounded failure; never retry repeatedly on stage |
| Browser reloads | Immutable analysis restores from the server | Continue to governed review |
| Duplicate demo column | Contract validation blocks analysis | Use a timestamped column name |
| Write-back is disabled | HITL preparation remains unavailable | Correct for normal demo; use the isolated proof separately |

## What not to do live

- Do not load the datapack, rebuild the Qdrant index, or restart Docker on stage.
- Do not expose `.env`, reviewer capabilities, provider keys, or LangSmith secrets.
- Do not enable write-back merely to make the demo look more active.
- Do not present provider configuration, an LLM answer, or a `COMPLETED` HTTP request as factual verification.
