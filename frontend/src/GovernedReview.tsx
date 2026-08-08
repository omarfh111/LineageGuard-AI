import { useEffect, useState } from "react";

import type { ChangeRequestPayload } from "./analysisFlow";
import { clearAnalysisRun, loadAnalysisRun } from "./recovery";
import {
  providerReady,
  providerReason,
  type RuntimeHealth,
} from "./runtimeHealth";
import "./review-workspace.css";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

type ImpactReport = {
  request: ChangeRequestPayload;
  blast_radius: number;
  confidence: number;
  risk_assessment: { level: string; score: number; explanation?: string[] };
  impacted_assets: Array<{ asset_urn: string; criticality: string; impact_type?: string }>;
  evidence_bundle: { items: unknown[] };
};
type RemediationPlan = {
  migration_steps: Array<{ order: number; action: string; rationale: string }>;
};
type WorkflowExecution = {
  analysis_run_id: string;
  impact_report: ImpactReport;
  remediation_plan: RemediationPlan;
};
type Critique = {
  model: string;
  summary: string;
  confidence: number;
  issues: Array<{ severity: string; finding: string }>;
  recommended_revisions: string[];
};
type Verdict = {
  judge_provider: string;
  judge_model: string;
  verdict: string;
  confidence: number;
  scores: Record<string, number>;
  critical_errors: string[];
  audit_rationale: string[];
};
type StoredJudging = {
  run_id: string;
  result: {
    deterministic_validation: { passed: boolean; errors: string[] };
    openai_verdict: Verdict | null;
    groq_verdict: Verdict | null;
    aggregate_decision: {
      decision: string;
      human_review_required: boolean;
      rationale: string;
    } | null;
  };
};
type Proposal = {
  run_id: string;
  status: string;
  target_asset_urn: string;
  document_content: string;
  allowed_mutations: string[];
  snapshot: Record<string, unknown>;
};

async function request<T>(
  path: string,
  body?: unknown,
  extraHeaders?: Record<string, string>,
): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined
      ? extraHeaders
      : { "Content-Type": "application/json", ...extraHeaders },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({})) as { detail?: string };
    throw new Error(error.detail ?? `API error (${response.status})`);
  }
  return response.json() as Promise<T>;
}

/** Describes the outcome the judges actually reached; it never implies write authority. */
function decisionHeadline(gatePassed: boolean, decision?: string) {
  if (!gatePassed) return "Gate 0 blocked this report";
  if (decision === "FINALIZE_READ_ONLY") return "The report passed both independent reviews";
  if (decision === "NEEDS_REPAIR") return "The judges asked for a repair cycle";
  if (decision === "BLOCKED") return "Both judges were unavailable";
  if (decision === "AWAITING_HUMAN") return "A human decision is required";
  return "Gate 0 blocked this report";
}

function tone(value?: string) {
  if (["PASS", "FINALIZE_READ_ONLY", "COMPLETED"].includes(value ?? "")) return "good";
  if (["FAIL", "BLOCKED", "REJECTED", "FAILED"].includes(value ?? "")) return "bad";
  return "warn";
}

const judgePresentation: Record<string, { name: string; provider: string }> = {
  openai: { name: "Independent Judge 1", provider: "OpenAI" },
  groq: { name: "Independent Judge 2", provider: "Groq" },
};

function presentJudge(provider: string) {
  return judgePresentation[provider] ?? { name: "Independent Judge", provider };
}

export default function GovernedReview({
  health,
  onBack,
  onRevision,
}: {
  health: RuntimeHealth | null;
  onBack: () => void;
  onRevision: (request: ChangeRequestPayload, comment: string) => void;
}) {
  const [execution, setExecution] = useState<WorkflowExecution | null>(null);
  const [critique, setCritique] = useState<Critique | null>(null);
  const [judging, setJudging] = useState<StoredJudging | null>(null);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [reviewerCapability, setReviewerCapability] = useState("");
  const [idempotencyKey, setIdempotencyKey] = useState<string | null>(null);
  const [decisionComment, setDecisionComment] = useState("");
  const [busy, setBusy] = useState<string | null>("restore");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [providerFailures, setProviderFailures] = useState<Set<string>>(() => new Set());
  const [confirmation, setConfirmation] = useState<"APPROVE_REPORT" | "ROLLBACK" | null>(null);
  const [reconciliation, setReconciliation] = useState<"ADOPT_COMPLETED_DOCUMENT" | "CONFIRM_NO_DOCUMENT_CREATED" | null>(null);
  const [reconciliationDocumentUrn, setReconciliationDocumentUrn] = useState("");

  useEffect(() => {
    const runId = loadAnalysisRun(window.sessionStorage);
    if (!runId) {
      setBusy(null);
      return;
    }
    request<WorkflowExecution>(`/api/v1/workflows/analysis/${runId}`)
      .then(setExecution)
      .catch((caught) => {
        clearAnalysisRun(window.sessionStorage);
        setError(caught instanceof Error ? caught.message : "Saved analysis is unavailable.");
      })
      .finally(() => setBusy(null));
  }, []);

  const nvidiaAvailable = providerReady(health, "nvidia_critic") && !providerFailures.has("nvidia_critic");
  const openaiAvailable = providerReady(health, "openai_judge") && !providerFailures.has("openai_judge");
  const groqAvailable = providerReady(health, "groq_judge") && !providerFailures.has("groq_judge");
  const judgesAvailable = openaiAvailable && groqAvailable;

  function markProviderFailure(provider: string) {
    setProviderFailures((current) => new Set(current).add(provider));
  }

  function runtimeReadiness(provider: string) {
    const readiness = health?.providers?.[provider];
    if (!providerFailures.has(provider)) return readiness;
    return {
      available: false,
      model: readiness?.model ?? null,
      reason: "The last live request failed. This action is disabled for the current page session.",
    };
  }

  async function runCritique() {
    if (!execution || !nvidiaAvailable) return;
    setBusy("critique"); setError(null); setNotice(null);
    try {
      const result = await request<{ critique: Critique }>("/api/v1/workflows/critique", {
        impact_report: execution.impact_report,
        remediation_plan: execution.remediation_plan,
      });
      setCritique(result.critique);
      setNotice("Advisory critique completed. It did not alter the report or DataHub.");
    } catch (caught) {
      markProviderFailure("nvidia_critic");
      setError(caught instanceof Error ? caught.message : "NVIDIA critique failed.");
    } finally { setBusy(null); }
  }

  async function runJudges() {
    if (!execution || !judgesAvailable) return;
    setBusy("judges"); setError(null); setNotice(null);
    try {
      const result = await request<{ judging: StoredJudging }>("/api/v1/workflows/judge", {
        analysis_run_id: execution.analysis_run_id,
        repair_cycles: 0,
      });
      setJudging(result.judging);
      if (["ERROR", "TIMEOUT"].includes(result.judging.result.openai_verdict?.verdict ?? "")) markProviderFailure("openai_judge");
      if (["ERROR", "TIMEOUT"].includes(result.judging.result.groq_verdict?.verdict ?? "")) markProviderFailure("groq_judge");
      setNotice("Both independent judges completed against the server-owned report.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Independent review failed.");
    } finally { setBusy(null); }
  }

  async function prepareWriteback() {
    if (!judging || health?.writeback !== "ready") return;
    setBusy("prepare"); setError(null);
    try {
      const key = crypto.randomUUID();
      const result = await request<Proposal>("/api/v1/writebacks/prepare", {
        run_id: judging.run_id,
        idempotency_key: key,
      }, { "X-LineageGuard-Reviewer-Capability": reviewerCapability });
      setIdempotencyKey(key);
      setProposal(result);
      setNotice("HITL proposal prepared. No DataHub write has occurred.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "HITL preparation failed.");
    } finally { setBusy(null); }
  }

  async function decide(decision: "APPROVE_REPORT" | "REQUEST_REVISION" | "REJECT") {
    const comment = decisionComment.trim();
    if (!proposal || !idempotencyKey || comment.length < 3) return;
    setBusy("decision"); setError(null);
    try {
      const result = await request<Proposal>(`/api/v1/writebacks/${proposal.run_id}/approve`, {
        decision,
        comment,
        idempotency_key: idempotencyKey,
      }, { "X-LineageGuard-Reviewer-Capability": reviewerCapability });
      if (decision === "REQUEST_REVISION" && result.status === "REVISION_REQUESTED" && execution) {
        clearAnalysisRun(window.sessionStorage);
        onRevision(execution.impact_report.request, comment);
        return;
      }
      setProposal(result);
      setDecisionComment("");
      setConfirmation(null);
      setNotice(`Reviewer decision recorded: ${result.status}.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Reviewer decision failed.");
    } finally { setBusy(null); }
  }

  async function rollback() {
    if (!proposal || !idempotencyKey) return;
    setBusy("rollback"); setError(null);
    try {
      const result = await request<Proposal>(`/api/v1/writebacks/${proposal.run_id}/rollback`, {
        decision: "APPROVE_ROLLBACK",
        comment: "Compensation explicitly approved in the reviewer interface.",
        idempotency_key: idempotencyKey,
      }, { "X-LineageGuard-Reviewer-Capability": reviewerCapability });
      setProposal(result);
      setConfirmation(null);
      setNotice(`Compensation recorded: ${result.status}.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Compensation failed.");
    } finally { setBusy(null); }
  }

  async function reconcile(action: "ADOPT_COMPLETED_DOCUMENT" | "CONFIRM_NO_DOCUMENT_CREATED") {
    if (!proposal || !idempotencyKey) return;
    const documentUrn = action === "ADOPT_COMPLETED_DOCUMENT" ? reconciliationDocumentUrn.trim() : null;
    if (action === "ADOPT_COMPLETED_DOCUMENT" && !documentUrn) return;
    setBusy("reconcile"); setError(null);
    try {
      const result = await request<Proposal>(`/api/v1/writebacks/${proposal.run_id}/reconcile`, {
        action,
        comment: "Human reconciliation after direct DataHub verification.",
        idempotency_key: idempotencyKey,
        document_urn: documentUrn ?? undefined,
      }, { "X-LineageGuard-Reviewer-Capability": reviewerCapability });
      setProposal(result);
      setReconciliation(null);
      setReconciliationDocumentUrn("");
      setNotice(`Reconciliation recorded: ${result.status}.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Reconciliation failed.");
    } finally { setBusy(null); }
  }

  if (busy === "restore") return <section className="review-empty"><h1>Governed review</h1><p>Restoring the server-owned analysis…</p></section>;
  if (!execution) return <section className="review-empty"><p className="overline">GOVERNED REVIEW</p><h1>No analysis selected</h1><p>Run a read-only impact analysis first. Review authority is never reconstructed from browser data.</p><button className="cta" onClick={onBack}>Start an analysis</button></section>;

  const impact = execution.impact_report;
  const plan = execution.remediation_plan;
  const decision = judging?.result.aggregate_decision;
  return <section className="page-content integration-page governed-review">
    <div className="page-heading"><div><p className="overline">EVIDENCE → REVIEW → HUMAN CONTROL</p><h1>Governed review</h1><p>One focused path from the immutable impact report to optional external review and explicit HITL.</p></div><button className="ghost" onClick={onBack}>Back to analysis</button></div>
    {error && <div className="review-banner error" role="alert">{error}</div>}
    {notice && <div className="review-banner notice">{notice}</div>}
    <section className="review-summary" data-testid="governed-review" data-analysis-run-id={execution.analysis_run_id}>
      <div><span className={`review-badge ${tone(impact.risk_assessment.level)}`}>{impact.risk_assessment.level}</span><h2>{impact.blast_radius} impacted assets</h2><p>{impact.evidence_bundle.items.length} DataHub evidence records · {Math.round(impact.confidence * 100)}% confidence</p></div>
      <code>{execution.analysis_run_id}</code>
    </section>
    <div className="review-grid">
      <section className="review-card"><span>01</span><h2>Impact evidence</h2><p>Target: <code>{impact.request.asset_urn}</code></p><ul>{impact.impacted_assets.slice(0, 5).map((item) => <li key={item.asset_urn}><b>{item.criticality}</b> {item.asset_urn}</li>)}</ul></section>
      <section className="review-card"><span>02</span><h2>Deterministic plan</h2><ol>{plan.migration_steps.map((step) => <li key={step.order}><b>{step.action}</b><p>{step.rationale}</p></li>)}</ol></section>
    </div>
    <section className="provider-row">
      <ProviderAction title="AI Critic · NVIDIA Nemotron" readiness={runtimeReadiness("nvidia_critic")}>
        <button className="ghost" onClick={runCritique} disabled={busy !== null || !nvidiaAvailable} title={nvidiaAvailable ? "Run optional advisory critique" : runtimeReadiness("nvidia_critic")?.reason ?? providerReason(health, "nvidia_critic")}>{busy === "critique" ? "Critiquing…" : nvidiaAvailable ? "Run AI critic" : "AI critic unavailable"}</button>
      </ProviderAction>
      <ProviderAction title="Independent Judges 1 + 2" readiness={judgesAvailable ? runtimeReadiness("openai_judge") : (!openaiAvailable ? runtimeReadiness("openai_judge") : runtimeReadiness("groq_judge"))}>
        <button className="cta" onClick={runJudges} disabled={busy !== null || !judgesAvailable} title={judgesAvailable ? "Run both independent judges" : [!openaiAvailable && providerReason(health, "openai_judge"), !groqAvailable && providerReason(health, "groq_judge")].filter(Boolean).join(" ")}>{busy === "judges" ? "Reviewing…" : judgesAvailable ? "Run independent judges" : "Judges unavailable"}</button>
      </ProviderAction>
    </section>
    {critique && <section className="review-card result">
      <div className="result-heading">
        <div><span>OPTIONAL ADVISORY</span><h2>AI Critic · NVIDIA Nemotron</h2></div>
        <span className="confidence-pill">{Math.round(critique.confidence * 100)}% confidence</span>
      </div>
      <p className="advisory-summary">{critique.summary}</p>
      {critique.issues.map((issue, index) => <p key={`${issue.finding}-${index}`}><b>{issue.severity}:</b> {issue.finding}</p>)}
      <small className="model-note">Model: {critique.model} · Advisory only; this result cannot authorize a write.</small>
    </section>}
    {judging && <section className="review-card result independent-result">
      <div className="decision-header">
        <div><span>INDEPENDENT REVIEW COMPLETE</span><h2>{decisionHeadline(judging.result.deterministic_validation.passed, decision?.decision)}</h2></div>
        <span className={`decision-pill ${decision?.decision === "FINALIZE_READ_ONLY" ? "good" : tone(decision?.decision)}`}>{decision?.human_review_required === false ? "READY FOR HUMAN REVIEW" : decision?.decision ?? "GATE 0 BLOCKED"}</span>
      </div>
      <p className="decision-explanation">{decision?.rationale}</p>
      {!judging.result.deterministic_validation.passed && <p className="review-critical">{judging.result.deterministic_validation.errors.join(" · ")}</p>}
      <div className="review-progress">
        <span className="complete"><b>1</b>Report locked</span>
        <span className={decision?.decision === "FINALIZE_READ_ONLY" ? "complete" : ""}><b>2</b>Judges passed</span>
        <span className={proposal ? "complete" : ""}><b>3</b>Human decision</span>
      </div>
      <div className="judge-grid-simple">{[judging.result.openai_verdict, judging.result.groq_verdict].map((verdict) => verdict && <JudgeCard key={verdict.judge_provider} verdict={verdict} />)}</div>
      {decision?.decision === "FINALIZE_READ_ONLY" && <ReviewerGate health={health} capability={reviewerCapability} setCapability={setReviewerCapability} busy={busy} onPrepare={prepareWriteback} />}
    </section>}
    {proposal && <section className="review-card result"><span>HUMAN-IN-THE-LOOP</span><h2>{proposal.status}</h2><p>Allowed mutation: {proposal.allowed_mutations.join(", ")}</p><details><summary>Review the proposed document and immutable snapshot</summary><pre>{proposal.document_content}</pre><pre>{JSON.stringify(proposal.snapshot, null, 2)}</pre></details>{proposal.status === "PENDING_APPROVAL" && <label>Reviewer rationale<textarea value={decisionComment} onChange={(event) => setDecisionComment(event.target.value)} minLength={3} /></label>}{confirmation && <section className="review-banner notice" role="alert"><b>Final human confirmation required</b><p>{confirmation === "APPROVE_REPORT" ? "This writes only the reviewed DataHub Analysis document. No schema or data mutation is possible." : "This compensates only the Analysis document written by this same run."}</p><div className="review-actions"><button className="cta" onClick={() => confirmation === "APPROVE_REPORT" ? decide("APPROVE_REPORT") : rollback()} disabled={busy !== null}>Confirm controlled action</button><button className="ghost" onClick={() => setConfirmation(null)} disabled={busy !== null}>Cancel</button></div></section>}{reconciliation && <section className="review-banner notice" role="alert"><b>Reconcile uncertain write-back</b><p>{reconciliation === "ADOPT_COMPLETED_DOCUMENT" ? "Enter the exact document URN only after verifying that it belongs to this report and asset in DataHub." : "Confirm only after verifying that no Analysis document was created for this proposal."}</p>{reconciliation === "ADOPT_COMPLETED_DOCUMENT" && <label>Verified DataHub document URN<input value={reconciliationDocumentUrn} onChange={(event) => setReconciliationDocumentUrn(event.target.value)} placeholder="urn:li:document:..." /></label>}<div className="review-actions"><button className="cta" onClick={() => reconcile(reconciliation)} disabled={busy !== null || (reconciliation === "ADOPT_COMPLETED_DOCUMENT" && !reconciliationDocumentUrn.trim())}>Confirm reconciliation</button><button className="ghost" onClick={() => { setReconciliation(null); setReconciliationDocumentUrn(""); }} disabled={busy !== null}>Cancel</button></div></section>}<div className="review-actions"><button className="cta" onClick={() => setConfirmation("APPROVE_REPORT")} disabled={busy !== null || proposal.status !== "PENDING_APPROVAL" || decisionComment.trim().length < 3}>Approve controlled write</button><button className="ghost" onClick={() => decide("REQUEST_REVISION")} disabled={busy !== null || proposal.status !== "PENDING_APPROVAL" || decisionComment.trim().length < 3}>Request revision</button><button className="danger" onClick={() => decide("REJECT")} disabled={busy !== null || proposal.status !== "PENDING_APPROVAL" || decisionComment.trim().length < 3}>Reject</button>{["COMPLETED", "ROLLBACK_UNCERTAIN"].includes(proposal.status) && <button className="danger" onClick={() => setConfirmation("ROLLBACK")} disabled={busy !== null}>Approve compensation</button>}{["WRITEBACK_UNCERTAIN", "FAILED"].includes(proposal.status) && <><button className="ghost" onClick={() => { setConfirmation(null); setReconciliation("ADOPT_COMPLETED_DOCUMENT"); }} disabled={busy !== null}>Adopt verified document</button><button className="danger" onClick={() => { setConfirmation(null); setReconciliation("CONFIRM_NO_DOCUMENT_CREATED"); }} disabled={busy !== null}>Confirm no document and re-authorize</button></>}</div></section>}
  </section>;
}

function ProviderAction({ title, readiness, children }: { title: string; readiness?: { available: boolean; model: string | null; reason: string }; children: React.ReactNode }) {
  return <article className={`provider-action ${readiness?.available ? "available" : "unavailable"}`}><div><b>{title}</b><span>{readiness?.model ?? "Not configured"}</span><small>{readiness?.reason ?? "Checking runtime configuration."}</small></div>{children}</article>;
}

function ReviewerGate({ health, capability, setCapability, busy, onPrepare }: { health: RuntimeHealth | null; capability: string; setCapability: (value: string) => void; busy: string | null; onPrepare: () => void }) {
  if (health?.writeback === "disabled") return <p className="review-banner notice">Write-back is disabled. The verified report remains read-only.</p>;
  if (health?.writeback !== "ready") return <p className="review-banner error">The local reviewer capability is not configured; write routes remain locked.</p>;
  return <div className="reviewer-gate-simple"><label>Local reviewer capability<input type="password" value={capability} onChange={(event) => setCapability(event.target.value)} autoComplete="off" /></label><button className="ghost" onClick={onPrepare} disabled={busy !== null || capability.length < 24}>Prepare HITL proposal</button><small>This value stays in this tab and is never returned by the API.</small></div>;
}

function JudgeCard({ verdict }: { verdict: Verdict }) {
  const presentation = presentJudge(verdict.judge_provider);
  return <article className="judge-card-simple">
    <header>
      <div><span>INDEPENDENT REVIEW</span><h3>{presentation.name}</h3><small>Provider: {presentation.provider} · Model: {verdict.judge_model}</small></div>
      <div className="judge-verdict"><span className={`review-badge ${tone(verdict.verdict)}`}>{verdict.verdict}</span><b>{Math.round(verdict.confidence * 100)}%</b><small>confidence</small></div>
    </header>
    <div className="judge-scores">{Object.entries(verdict.scores).map(([name, score]) => <div key={name}><span>{name.replaceAll("_", " ")}</span><span className="score-track"><i style={{ width: `${Math.max(0, Math.min(5, score)) * 20}%` }} /></span><b>{score}/5</b></div>)}</div>
    {verdict.critical_errors.length > 0 && <p className="review-critical">{verdict.critical_errors.join(" · ")}</p>}
    {verdict.audit_rationale.length > 0 && <details><summary>Auditable rationale</summary><ul>{verdict.audit_rationale.map((line) => <li key={line}>{line}</li>)}</ul></details>}
  </article>;
}
