# Submission checklist

This is the release checklist for **Build with DataHub: The Agent Hackathon**.
It complements the technical runbook; it does not replace the official
[Devpost requirements](https://datahub.devpost.com/) or
[rules](https://datahub.devpost.com/rules).

## Official requirements mapped to repository evidence

| Requirement | Repository evidence | Final owner action |
|---|---|---|
| Working software using DataHub | DataHub OSS/Core, official MCP bridge, Docker Compose, read/analyze/review/write-back workflows | Keep the test URL or local test instructions available through the judging period |
| Public source repository | Complete application, infrastructure, tests, evaluation datasets, and documentation | Confirm `https://github.com/omarfh111/LineageGuard-AI` is public and the default branch is `main` |
| Apache 2.0 license | Root [`LICENSE`](../LICENSE) file | Confirm GitHub detects the license and shows it in the repository header/About area |
| Written project description | Root [`README`](../README.md) and the description template below | Paste a concise, accurate version into Devpost |
| Public demonstration video under three minutes | Storyboard below | Record the real application, upload publicly to YouTube or Vimeo, and add the URL |
| Easy testing access | [`runbook.md`](runbook.md), `.env.example`, Docker Compose, health route, and demo preflight | Provide a hosted URL or explicitly tell judges to use the repository setup; include any required credentials privately in Devpost testing instructions |
| Optional sample outputs | Versioned [`evals/evidence`](../evals/evidence/) and reports; impact/remediation examples | Add one sanitized screenshot or exported report only after verifying it contains no secret or sensitive metadata |

The official submission deadline shown by Devpost is **August 10, 2026 at
5:00 PM EDT**. Recheck the live page before submitting in case the organizer
changes a field or schedule.

## Release gate

Do not label a revision submission-ready until every required row is complete.

| Gate | Command or evidence | Blocking |
|---|---|---:|
| Clean secret scan | Confirm `.env`, API keys, reviewer capability, raw authorization headers, and private traces are absent from Git history and screenshots | Yes |
| Backend suite | `python -m pytest tests -q -p no:cacheprovider` from `backend` | Yes |
| Frontend unit/type/build | `npm run check` from `frontend` | Yes |
| Deterministic browser E2E | `npm run test:e2e` from `frontend` | Yes |
| Deterministic evaluation | `python .\evals\runners\run_deterministic_evals.py --evidence-dir evals/evidence` | Yes |
| Live read-only evidence | Run the reviewed professional suite in isolated sessions and create a new versioned evidence file | Yes for a new release claim |
| DataHub preflight | `.\scripts\demo-preflight.ps1` prints `DEMO READY` | Yes for live demo |
| Optional provider rehearsal | Each provider/model used in the video completes one bounded request | Yes only if that provider appears in the video |
| Optional write proof | One disposable Analysis document reaches `COMPLETED` then `ROLLED_BACK`, with a sanitized audit artifact | Yes only if claiming a new write proof |
| Public access | Repository, video, and hosted/test URL open in a signed-out browser | Yes |
| Documentation links | Markdown links and Mermaid diagrams render on GitHub | Yes |

Never replace an older evaluation evidence file. Generate a new immutable file
so its dataset, source hashes, Git revision, model, date, latency, tokens, and
cost remain attributable.

## Under-three-minute video storyboard

Target **2:40–2:55** to leave upload/player margin.

| Time | Screen | Narration goal |
|---:|---|---|
| 0:00–0:18 | Title + Health | State the schema-change risk and show live DataHub/Qdrant readiness without exposing keys |
| 0:18–0:42 | 3D Cartography | Show the full server-cached DataHub graph, one exact node/URN, and lineage relationships |
| 0:42–1:12 | Assistant | Ask one platform-qualified schema or lineage question; show target resolution, MCP evidence, and claim verification |
| 1:12–1:48 | New analysis | Run a unique nullable `ADD_COLUMN` or reviewed `DROP_COLUMN`; show exact impact paths, risk, and `NOT_EXECUTED` remediation |
| 1:48–2:18 | Governed review | Show Gate 0 and independent provider verdicts from a rehearsed run, or show the versioned proof if provider calls are intentionally skipped live |
| 2:18–2:43 | HITL/audit | Show that read-only finalization is not write authority; show explicit human control and the document-only mutation boundary |
| 2:43–2:55 | Evidence + close | Show the 30-query metrics/report and close on “live DataHub evidence, fail-closed agents, human-owned action” |

Do not load the datapack, build images, index Qdrant, reveal `.env`, or wait for
an unrehearsed external model during the recording. The longer operator flow is
in the [five-minute demonstration](five-minute-demo.md).

## Suggested Devpost description

> LineageGuard AI is an evidence-first team of DataHub agents for governing
> schema changes. It resolves the exact asset through the official DataHub MCP
> Server, verifies schemas and multi-hop lineage, computes a deterministic
> blast radius and remediation dossier, and obtains independent technical
> reviews before a human can publish one scoped Analysis document back to
> DataHub. Qdrant accelerates candidate discovery but never replaces live MCP
> proof; unsupported claims, ambiguous assets, provider failures, duplicate
> approvals, and uncertain writes fail closed. The React application also
> provides a server-cached 3D view of the live metadata graph, bounded memory,
> LangGraph orchestration, optional LangSmith tracing, and versioned
> professional evaluation evidence.

## Submission form facts

Use these values only if they still match the final revision:

- **Project:** LineageGuard AI
- **Challenge:** Agents That Do Real Work
- **DataHub technologies:** DataHub OSS / Core Platform and DataHub MCP Server
- **License:** Apache 2.0
- **Repository:** `https://github.com/omarfh111/LineageGuard-AI`
- **Primary data:** DataHub `showcase-ecommerce` datapack metadata; no warehouse rows are copied into Qdrant
- **Mutation boundary:** one approved DataHub Analysis document; no schema, lineage, dataset, warehouse, dbt, or dashboard mutation
- **Open-source contribution bonus:** do not select or claim unless a real external contribution URL exists

## Final manual checks

1. Revoke and rotate any credential ever pasted into a chat, screenshot, issue,
   terminal capture, or Git commit.
2. Run the release gate on the exact pushed commit.
3. Confirm the README badges, diagrams, and all relative links render on GitHub.
4. Test the setup from a clean clone or provide a hosted build.
5. Open repository, video, and demo links in a signed-out browser.
6. Keep the app and testing access available through the judging period.
7. Submit before the displayed Devpost deadline and retain the confirmation.
