import "./assistant-answer.css";

export type ChatReply = {
  answer: string;
  verification_note: string;
  citations: Array<{
    urn: string;
    label: string;
    entity_type: string;
    platform_urn?: string | null;
    source: string;
  }>;
  target_resolution?: {
    status: "NOT_REQUIRED" | "RESOLVED" | "AMBIGUOUS" | "NOT_FOUND";
    detail: string;
    targets: Array<{
      urn: string;
      label: string;
      entity_type: string;
      platform_urn?: string | null;
    }>;
  } | null;
  verification?: {
    passed: boolean;
    factual_claim_count: number;
    supported_claim_count: number;
    claim_coverage: number;
  } | null;
  action_proposal: {
    action: "NONE" | "ANALYZE_IMPACT" | "HITL_WRITEBACK";
    reason: string;
  };
  analysis_handoff_id?: string | null;
  analysis_handoff_expires_at?: string | null;
  agent_trace: Array<{ id: string; label: string; status: string; detail: string }>;
};

export type SchemaField = { name: string; dataType: string };

const SCHEMA_FIELD_PATTERN = /^-?\s*column=([^,]+),\s*type=(.+?)(?:\s+\[E-[^\]]+\])?\.?$/i;

/** Convert the agent's evidence-preserving schema rows into a scan-friendly table. */
export function parseSchemaFields(answer: string): SchemaField[] {
  return answer
    .split(/\r?\n/)
    .map((line) => line.trim().match(SCHEMA_FIELD_PATTERN))
    .filter((match): match is RegExpMatchArray => match !== null)
    .map((match) => ({ name: match[1].trim(), dataType: match[2].trim() }));
}

function platformName(platform?: string | null) {
  return (platform ?? "unknown").replace("urn:li:dataPlatform:", "");
}

function friendlyOutcome(outcome: string) {
  if (outcome === "VERIFIED") return "Verified answer";
  if (outcome === "ACTION REQUIRED") return "Action needs confirmation";
  return "Limited answer";
}

function answerWithoutSchemaRows(answer: string) {
  return answer
    .split(/\r?\n/)
    .filter((line) => !SCHEMA_FIELD_PATTERN.test(line.trim()))
    .map((line) => line.replace(/^[-•]\s*/, "").replace(/\s+\[E-[^\]]+\]\.?$/, "."))
    .filter(Boolean)
    .join("\n");
}

function uniqueCitations(citations: ChatReply["citations"]) {
  const seen = new Set<string>();
  return citations.filter((citation) => {
    const key = `${citation.source}:${citation.urn}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export default function AssistantAnswer({
  reply,
  outcome,
  canAnalyze,
  onAnalyze,
  onOpenReview,
}: {
  reply: ChatReply;
  outcome: string;
  canAnalyze: boolean;
  onAnalyze: () => void;
  onOpenReview: () => void;
}) {
  const fields = parseSchemaFields(reply.answer);
  const readableAnswer = answerWithoutSchemaRows(reply.answer);
  const target = reply.target_resolution?.targets[0];
  const citations = uniqueCitations(reply.citations);
  const coverage = reply.verification
    ? Math.round(reply.verification.claim_coverage * 100)
    : null;

  return <article className="live-answer">
    <header className="answer-hero">
      <span className={`answer-outcome ${outcome === "LIMITED" ? "limited" : ""}`}>{friendlyOutcome(outcome)}</span>
      <div>
        <h2>{fields.length > 0 && target ? `${target.label} schema` : "DataHub answer"}</h2>
        <p>{outcome === "VERIFIED" ? "Checked against live DataHub MCP evidence." : reply.verification_note}</p>
      </div>
    </header>

    {target && <section className="resolved-asset">
      <div>
        <span>Verified DataHub asset</span>
        <h3>{target.label}</h3>
        <p>{platformName(target.platform_urn)} · {target.entity_type.toLowerCase()}</p>
      </div>
      <details>
        <summary>Technical identity</summary>
        <code>{target.urn}</code>
      </details>
    </section>}

    <section className="answer-content">
      {readableAnswer && <p>{readableAnswer}</p>}
      {fields.length > 0 && <div className="schema-section">
        <div className="section-title"><h3>Schema fields</h3><span>{fields.length} fields</span></div>
        <div className="schema-table" role="table" aria-label="Verified DataHub schema fields">
          <div className="schema-row schema-head" role="row"><span role="columnheader">Field</span><span role="columnheader">Data type</span></div>
          {fields.map((field) => <div className="schema-row" role="row" key={`${field.name}-${field.dataType}`}><code role="cell">{field.name}</code><span role="cell">{field.dataType}</span></div>)}
        </div>
      </div>}
    </section>

    {reply.verification && <section className="evidence-check">
      <div className="coverage-ring" aria-label={`${coverage}% factual claim coverage`}>{coverage}%</div>
      <div><b>Evidence check passed</b><span>{reply.verification.supported_claim_count} of {reply.verification.factual_claim_count} factual claims are supported.</span></div>
    </section>}

    {citations.length > 0 && <details className="evidence-details">
      <summary>View evidence sources ({citations.length})</summary>
      <div className="evidence-tags">{citations.map((citation) => <code key={`${citation.source}-${citation.urn}`}>{citation.label} · {citation.source === "datahub_mcp_live" ? "MCP verified" : "RAG context"}</code>)}</div>
    </details>}

    {reply.action_proposal.action !== "NONE" && <section className="action-callout">
      <b>{reply.action_proposal.action === "ANALYZE_IMPACT" ? "Impact analysis recommended" : "Human approval required"}</b>
      <p>{reply.action_proposal.reason}</p>
      {reply.action_proposal.action === "ANALYZE_IMPACT" && <>
        <button className="cta" onClick={onAnalyze} disabled={!canAnalyze}>Use verified target in analysis →</button>
        {!canAnalyze && <small>A live, unambiguous DataHub target is required before analysis.</small>}
      </>}
      {reply.action_proposal.action === "HITL_WRITEBACK" && <button className="ghost" onClick={onOpenReview}>Open governed review →</button>}
    </section>}

    <details className="verification-trace">
      <summary>How this answer was verified</summary>
      {reply.agent_trace.map((step) => <p key={`${step.id}-${step.detail}`}><b>{step.label}</b><span>{step.status}</span><small>{step.detail}</small></p>)}
    </details>
  </article>;
}
