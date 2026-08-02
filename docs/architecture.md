# Architecture

This document describes the implementation that is present in this repository. It distinguishes demonstrated behaviour from optional integrations and does not treat configuration as proof of a successful provider call.

## System context

```mermaid
flowchart TB
    Browser["Browser user"] --> Web["React / Vite frontend"]
    Web --> API["FastAPI backend"]
    API --> SQLite["SQLite: runs, proposals, audit, memory"]
    API --> Qdrant["Qdrant: metadata projections"]
    API --> ReadMCP["DataHub MCP read subprocess<br/>fixed allowlist"]
    ReadMCP --> GMS["DataHub GMS / Core"]
    API --> Gates["Gate 0 + double judge + HITL"]
    Gates -. "enabled + capability + approved" .-> WriteMCP["Isolated DataHub MCP writer<br/>save_document only"]
    WriteMCP -. "Analysis document" .-> GMS
    API -. "optional, user-triggered" .-> Nvidia["NVIDIA Build"]
    API -. "optional, user-triggered" .-> OpenAI["OpenAI"]
    API -. "optional, user-triggered" .-> Groq["Groq"]
    API -. "optional tracing" .-> LangSmith["LangSmith"]
```

The browser talks only to the FastAPI API. It never receives a DataHub token,
a provider key, raw MCP server environment, or a write-capable MCP client. The
normal MCP process has mutation and document tools disabled. The separate
writer process is constructed only after all server and human gates pass and
exposes only `save_document` for the exact proposal.

### Deployment topology

```mermaid
flowchart LR
    subgraph App["LineageGuard Docker Compose"]
        Frontend["frontend :5173"]
        Backend["backend :8000"]
        Vector["Qdrant :6333"]
        Volume1[("SQLite volume")]
        Volume2[("Qdrant volume")]
        Frontend --> Backend
        Backend --> Vector
        Backend --> Volume1
        Vector --> Volume2
    end

    subgraph DataHub["Local DataHub Quickstart"]
        UI["DataHub UI :9002"]
        GMS2["GMS :8080"]
        Search["OpenSearch"]
        DB["MySQL"]
        Kafka["Kafka"]
        UI --> GMS2
        GMS2 --> Search
        GMS2 --> DB
        GMS2 --> Kafka
    end

    Backend -->|"host.docker.internal:8080"| GMS2
```

The two Compose projects are intentionally separate. PostgreSQL, Snowflake,
Power BI, S3, dbt, Looker, and Tableau labels in the showcase graph are
metadata platforms represented by the datapack; LineageGuard does not start
those systems as containers or copy their business rows.

## Main workflows

### Governed impact workflow

```mermaid
flowchart LR
    Request["Validated change request"] --> Read["DataHub schema + lineage reads"]
    Read --> Report["Evidence-backed impact report"]
    Report --> Plan["Deterministic remediation plan"]
    Plan --> Snapshot["Persist server-owned analysis_run_id"]
    Plan -. "optional advisory" .-> Critic["NVIDIA critique"]
    Snapshot --> Gate0{"Gate 0 reconstruction"}
    Gate0 -->|"invalid"| Stop["Blocked: no provider call"]
    Gate0 -->|"valid and requested"| J1["OpenAI factual judge"]
    Gate0 -->|"valid and requested"| J2["Groq technical/safety judge"]
    J1 --> Aggregate["Deterministic aggregation"]
    J2 --> Aggregate
    Aggregate -->|"double threshold PASS"| Proposal["Prepare HITL proposal"]
    Aggregate -->|"otherwise"| Review["Repair or human review"]
    Proposal --> Human{"Human decision"}
    Human -->|"approve + enabled + local capability"| Writer2["CAS claim + isolated MCP writer"]
    Writer2 --> Save["DataHub Analysis document only"]
    Human -->|"reject / revise"| Audit["Persist audit event"]
```

### Agentic RAG workflow

```mermaid
sequenceDiagram
    participant U as User
    participant A as LangGraph agent
    participant Q as Qdrant
    participant M as DataHub MCP
    participant D as DataHub

    U->>A: Question
    A->>A: Plan and normalize search terms
    A->>Q: Retrieve metadata candidates
    A->>M: DataHub search
    M->>D: Read metadata
    D-->>M: Live candidates
    M-->>A: Primary live candidates
    opt primary search did not prove one exact target
        A->>M: Search bounded Qdrant candidate labels
        M-->>A: Exact live URN confirmations only
    end
    A->>A: Resolve target URN or ambiguity
    alt schema or lineage request with one target
        A->>M: list_schema_fields and/or get_lineage
        M->>D: Read live evidence
        D-->>M: Schema / lineage facts
        M-->>A: Evidence IDs bound to target URN
    end
    A->>A: Grounded answer and deterministic verification
    A-->>U: VERIFIED, LIMITED, or ACTION_REQUIRED response
```

## Data classification

| Store / channel | Contents | Does not contain |
|---|---|---|
| DataHub | The authoritative metadata graph | Application credentials or LineageGuard approval records |
| Qdrant | URN, label, type, platform URN, owners | Table rows, SQL, raw GraphQL payloads, credentials, model prompts |
| SQLite | Workflow state, audit, proposal/snapshot, local conversation memory | Provider secrets, DataHub token, private chain-of-thought |
| Browser local storage | Random anonymous chat session identifier | Memory content, reviewer capability, DataHub token, provider keys |
| Browser tab memory | Local reviewer capability while the tab remains open | Provider keys, DataHub token, persisted reviewer secret |
| LangSmith, if enabled | Trace hierarchy and configured run telemetry | Keys; public evidence must be reviewed before export |

## Agent responsibilities and invariants

| Agent / component | Input | Output | Invariant |
|---|---|---|---|
| Planning agent | User question and bounded non-evidence memory | Search terms and tool needs | Normalizes conversational words and cannot call tools |
| Qdrant retriever | Question | Candidate metadata | At most three strong candidates may guide live searches; candidates are never factual evidence |
| Target resolver | Primary and Qdrant-guided exact MCP matches + active verified asset | `RESOLVED`, `AMBIGUOUS`, `NOT_FOUND`, or `NOT_REQUIRED` | Schema/lineage needs a single target; vector rank cannot break an exact-name platform ambiguity |
| MCP tool manager | Locked target and plan | Read-only evidence records | Retries retain the same target; unknown assets never trigger unrelated schema or lineage reads |
| Reasoning agent | Candidate sources and named evidence | Draft answer | Every DataHub assertion is independently cited; Qdrant is context, never proof |
| Verification agent | Draft answer, evidence, target | Per-claim support decisions, verified response, or safe limitation | Every claim needs a live MCP factual anchor; evidence must belong to the resolved target URN |
| Action router | User intent | `NONE`, typed `ANALYZE_IMPACT`, or `HITL_WRITEBACK` | All four schema changes are explicit; conflicting intents are never guessed; the chat cannot perform a mutation |

Conversation memory is bounded by count, characters, and TTL. Expiration
removes both the stored turns and the separately verified active asset in one
purge transaction. Clearing memory also revokes the session's outstanding
chat-to-analysis handoff. CORS permits `DELETE` and the reviewer header only
from the configured local frontend origin.

## 3D catalog cache lifecycle

```mermaid
stateDiagram-v2
    [*] --> RUNNING: backend starts
    RUNNING --> READY: root catalog assets loaded
    READY --> READY: enrich lineage relationships in background
    READY --> STALE: manual refresh or LineageGuard action
    STALE --> RUNNING: refresh begins; old graph remains visible
    RUNNING --> READY: atomically replace complete refreshed graph
    RUNNING --> FAILED: initial DataHub failure
    STALE --> STALE: refresh fails; old graph remains visible
```

The API maintains an in-memory root-URN fingerprint separate from the enriched graph. Scheduled polling does not scan lineage again when the root URN set is unchanged. It requires two equal changed observations before refreshing, preventing transient DataHub search ordering or display metadata changes from causing expensive repeated scans.

## Operational limits

| Limit | Default | Reason |
|---|---:|---|
| Catalog assets | 1,500 | Bounds startup and graph rendering work |
| Catalog edges | 5,000 | Bounds browser and cache memory |
| Catalog poll | 60 seconds | Detects external changes without a webhook |
| RAG assets | 1,500 | Bounds Qdrant ingestion |
| Memory turns | 6 | Keeps contextual carry-over small and auditable |
| Tool retry | 1 bounded retry | Allows recovery without target substitution or loops |
| Judge retries | Environment-controlled | Avoids uncontrolled external cost |

## Failure containment

| Failure | Contained outcome |
|---|---|
| DataHub MCP timeout | Request becomes limited/stale; no target handoff or partial graph replacement |
| Qdrant unavailable | Live MCP may still answer bounded reads; Qdrant never becomes evidence |
| Chat model timeout | Deterministic evidence fallback or safe limitation |
| NVIDIA failure | Advisory error only; deterministic report is unchanged |
| One final judge unavailable | No double PASS; workflow remains human/read-only |
| Duplicate approval | One local CAS claimant; other caller observes existing state |
| Unknown remote create outcome | `WRITEBACK_UNCERTAIN`; automatic retries blocked |
| Compensation uncertainty | Exact document remains bound; new explicit decision required |
| Backend restart | SQLite/Qdrant persist; 3D in-memory cache reloads; browser restores only an immutable read-only analysis UUID |

## Observability

LangGraph emits its own graph trace when LangSmith is enabled. The implementation also names the outer RAG request and optional provider operations so latency and failures can be filtered by component. Public UI traces show only stage names, status, selected target, tool actions, and verification notes; they intentionally do not display private reasoning.
