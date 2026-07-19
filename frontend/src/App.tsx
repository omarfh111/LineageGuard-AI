import { FormEvent, useEffect, useMemo, useState } from "react";
import "./styles.css";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const demoAsset = "urn:li:dataset:(urn:li:dataPlatform:dbt,b2fd91.order_entry_db.order_entry.orders,PROD)";

type Health = { status: string; environment: string };
type ChangeType = "ADD_COLUMN" | "RENAME_COLUMN" | "CHANGE_COLUMN_TYPE" | "DROP_COLUMN";
type ApiError = { detail?: string };
type ImpactReport = Record<string, any>;
type RemediationPlan = Record<string, any>;
type Critique = { model: string; summary: string; confidence: number; issues: Array<{ severity: string; finding: string; evidence_ids: string[] }>; recommended_revisions: string[] };
type Verdict = { judge_provider: string; judge_model: string; verdict: string; confidence: number; scores: Record<string, number>; critical_errors: string[]; non_critical_issues: string[]; repair_instructions: string[]; audit_rationale: string[] };
type StoredJudging = { run_id: string; result: { deterministic_validation: { passed: boolean; errors: string[] }; openai_verdict: Verdict | null; groq_verdict: Verdict | null; aggregate_decision: { decision: string; human_review_required: boolean; rationale: string } | null } };
type Proposal = { run_id: string; status: string; target_asset_urn: string; document_title: string; document_content: string; allowed_mutations: string[]; snapshot: Record<string, unknown>; idempotency_key: string };
type RunSummary = { run_id: string; created_at: string; decision: string | null; openai_status: string | null; groq_status: string | null };

const steps = ["Demande", "Impact", "Plan", "Critique locale", "Revue indépendante", "Validation humaine"];

async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({})) as ApiError;
    throw new Error(error.detail ?? `Erreur API (${response.status})`);
  }
  return response.json() as Promise<T>;
}

function statusTone(value?: string) {
  if (value === "PASS" || value === "FINALIZE_READ_ONLY" || value === "COMPLETED") return "good";
  if (value === "FAIL" || value === "BLOCKED" || value === "REJECTED" || value === "FAILED") return "bad";
  return "warn";
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [assetUrn, setAssetUrn] = useState(demoAsset);
  const [changeType, setChangeType] = useState<ChangeType>("ADD_COLUMN");
  const [columnName, setColumnName] = useState("lineageguard_demo_note");
  const [newValue, setNewValue] = useState("");
  const [reason, setReason] = useState("Validation contrôlée de la démo LineageGuard.");
  const [depth, setDepth] = useState(2);
  const [impact, setImpact] = useState<ImpactReport | null>(null);
  const [plan, setPlan] = useState<RemediationPlan | null>(null);
  const [critique, setCritique] = useState<Critique | null>(null);
  const [judging, setJudging] = useState<StoredJudging | null>(null);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [history, setHistory] = useState<string[]>([]);
  const [persistedHistory, setPersistedHistory] = useState<RunSummary[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    request<Health>("/api/v1/health").then(setHealth).catch(() => setHealth(null));
    request<RunSummary[]>("/api/v1/judges/history").then(setPersistedHistory).catch(() => setPersistedHistory([]));
  }, []);

  async function refreshPersistedHistory() {
    try { setPersistedHistory(await request<RunSummary[]>("/api/v1/judges/history")); } catch { /* History is non-critical to the workflow. */ }
  }

  const activeStep = proposal ? 5 : judging ? 4 : critique ? 3 : plan ? 2 : impact ? 1 : 0;
  const changeNeedsValue = changeType === "RENAME_COLUMN" || changeType === "CHANGE_COLUMN_TYPE";
  const requestPayload = useMemo(() => ({
    asset_urn: assetUrn.trim(), change_type: changeType, column_name: changeType === "ADD_COLUMN" ? columnName.trim() || undefined : columnName.trim(),
    new_value: changeNeedsValue ? newValue.trim() : undefined,
    reason: reason.trim(), environment: "PRODUCTION", lineage_depth: depth,
    column_nullable: changeType === "ADD_COLUMN" ? true : undefined,
    type_change_compatible: changeType === "CHANGE_COLUMN_TYPE" ? false : undefined,
  }), [assetUrn, changeType, columnName, newValue, reason, depth, changeNeedsValue]);

  function resetAfterImpact() { setPlan(null); setCritique(null); setJudging(null); setProposal(null); }
  async function runImpact(event: FormEvent) {
    event.preventDefault(); setBusy("impact"); setError(null); setNotice(null);
    try {
      const report = await request<ImpactReport>("/api/v1/analyses/impact", requestPayload);
      const nextPlan = await request<RemediationPlan>("/api/v1/remediations/plan", report);
      setImpact(report); setPlan(nextPlan); resetAfterImpact(); setImpact(report); setPlan(nextPlan);
      setHistory((items) => [`Analyse ${new Date().toLocaleTimeString("fr-FR")} · ${report.risk_assessment.level}`, ...items].slice(0, 8));
      setNotice("Impact et plan déterministe générés. Aucun LLM ni changement DataHub n’a été déclenché.");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Analyse impossible"); }
    finally { setBusy(null); }
  }
  async function runCritique() {
    if (!impact || !plan) return; setBusy("critique"); setError(null); setNotice(null);
    try {
      const result = await request<Critique>("/api/v1/debates/critique", { impact_report: impact, remediation_plan: plan });
      setCritique(result); setHistory((items) => [`Critique NVIDIA · ${result.model}`, ...items].slice(0, 8));
      setNotice("Critique NVIDIA terminée. Elle est consultative : le plan n’a pas été modifié automatiquement.");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Critique NVIDIA impossible"); }
    finally { setBusy(null); }
  }
  async function runJudges() {
    if (!impact || !plan) return; setBusy("judges"); setError(null); setNotice(null);
    try {
      const result = await request<StoredJudging>("/api/v1/judges/evaluate", { impact_report: impact, remediation_plan: plan, repair_cycles: 0 });
      setJudging(result); setHistory((items) => [`Revue OpenAI + Groq · ${result.result.aggregate_decision?.decision ?? "GATE0"}`, ...items].slice(0, 8));
      await refreshPersistedHistory();
      setNotice("Les juges ont été exécutés indépendamment. Vérifiez leurs verdicts avant toute suite.");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Revue des juges impossible"); }
    finally { setBusy(null); }
  }
  async function prepareWriteback() {
    if (!judging) return; setBusy("prepare"); setError(null);
    try {
      const key = crypto.randomUUID();
      const result = await request<Proposal>("/api/v1/writebacks/prepare", { run_id: judging.run_id, idempotency_key: key });
      setProposal(result); setNotice("Proposition enregistrée avec son snapshot. Elle n’est pas encore écrite dans DataHub.");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Préparation impossible"); }
    finally { setBusy(null); }
  }
  async function humanDecision(decision: "APPROVE_REPORT" | "REQUEST_REVISION" | "REJECT") {
    if (!proposal) return;
    if (decision === "APPROVE_REPORT" && !window.confirm("Confirmer la demande d’écriture contrôlée dans DataHub ?")) return;
    setBusy("approval"); setError(null);
    try {
      const result = await request<Proposal>(`/api/v1/writebacks/${proposal.run_id}/approve`, { decision, comment: "Décision prise depuis l’interface LineageGuard.", idempotency_key: proposal.idempotency_key });
      setProposal(result); setNotice(`Décision enregistrée : ${result.status}.`);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Décision impossible"); }
    finally { setBusy(null); }
  }

  return <main className="shell">
    <header className="topbar">
      <div><p className="eyebrow">Build with DataHub · Agents That Do Real Work</p><h1>LineageGuard <span>AI</span></h1></div>
      <div className={`api-state ${health ? "online" : "offline"}`}><i /> API {health ? `${health.status} · ${health.environment}` : "indisponible"}</div>
    </header>

    <section className="guardrail"><strong>Mode sûr</strong><span>Lecture DataHub, planification déterministe, critique locale puis juges indépendants. L’écriture reste bloquée tant qu’une approbation humaine explicite n’est pas donnée.</span></section>
    {error && <div className="banner error">{error}</div>}{notice && <div className="banner notice">{notice}</div>}

    <nav className="steps" aria-label="Progression du workflow">{steps.map((step, index) => <div className={index <= activeStep ? "step active" : "step"} key={step}><b>{index + 1}</b><span>{step}</span></div>)}</nav>

    <div className="layout">
      <section className="panel request-panel"><div className="panel-heading"><div><p className="kicker">Étape 1</p><h2>Demande de changement</h2></div><span className="readonly">Aucune mutation</span></div>
        <form onSubmit={runImpact}>
          <label>Actif DataHub<input value={assetUrn} onChange={(event) => setAssetUrn(event.target.value)} required /></label>
          <div className="two-col"><label>Type de changement<select value={changeType} onChange={(event) => setChangeType(event.target.value as ChangeType)}><option value="ADD_COLUMN">Ajouter une colonne</option><option value="RENAME_COLUMN">Renommer une colonne</option><option value="CHANGE_COLUMN_TYPE">Changer le type</option><option value="DROP_COLUMN">Supprimer une colonne</option></select></label><label>Profondeur de lineage<select value={depth} onChange={(event) => setDepth(Number(event.target.value))}>{[1,2,3,4,5].map((value) => <option key={value} value={value}>{value} saut{value > 1 ? "s" : ""}</option>)}</select></label></div>
          <div className="two-col"><label>Colonne{changeType === "ADD_COLUMN" ? " (optionnelle)" : ""}<input value={columnName} onChange={(event) => setColumnName(event.target.value)} required={changeType !== "ADD_COLUMN"} /></label>{changeNeedsValue && <label>{changeType === "RENAME_COLUMN" ? "Nouveau nom" : "Nouveau type"}<input value={newValue} onChange={(event) => setNewValue(event.target.value)} required /></label>}</div>
          <label>Justification<textarea value={reason} onChange={(event) => setReason(event.target.value)} required minLength={5} /></label>
          <button className="primary" disabled={busy !== null}>{busy === "impact" ? "Analyse en cours…" : "Analyser l’impact et générer le plan"}</button>
        </form>
      </section>

      <aside className="panel workflow"><p className="kicker">Contrôles</p><h2>Workflow gouverné</h2>
        <div className="control"><span>DataHub MCP</span><b className="chip good">lecture seule</b></div><div className="control"><span>NVIDIA Build</span><b className="chip">consultatif</b></div><div className="control"><span>OpenAI + Groq</span><b className="chip warn">déclenchés manuellement</b></div><div className="control"><span>Write-back</span><b className="chip bad">HITL obligatoire</b></div>
        <p className="small">Les métadonnées sont traitées comme des données non fiables. Les preuves sont conservées avec chaque analyse.</p>
      </aside>
    </div>

    {impact && <section className="panel report"><div className="panel-heading"><div><p className="kicker">Étapes 2–3</p><h2>Rapport d’impact et plan</h2></div><span className={`badge ${statusTone(impact.risk_assessment.level)}`}>{impact.risk_assessment.level} · {impact.risk_assessment.score}/100</span></div>
      <div className="metrics"><div><b>{impact.blast_radius}</b><span>actifs impactés</span></div><div><b>{impact.evidence_bundle.items.length}</b><span>preuves DataHub</span></div><div><b>{Math.round(impact.confidence * 100)}%</b><span>confiance</span></div></div>
      <div className="split"><div><h3>Actifs et lineage</h3><ul className="asset-list">{impact.impacted_assets.slice(0, 8).map((item: any) => <li key={item.asset_urn}><code>{item.asset_urn}</code><span>{item.impact_type} · {item.criticality}</span></li>)}</ul>{impact.impacted_assets.length === 0 && <p className="small">Aucun actif aval trouvé dans la profondeur choisie.</p>}</div><div><h3>Plan de remédiation</h3><ol>{plan?.migration_steps.map((step: any) => <li key={step.order}><b>{step.action}</b><span>{step.rationale}</span></li>)}</ol><p className="small"><b>Rollback :</b> {plan?.rollback_plan?.trigger_conditions?.[0] ?? "Défini dans le plan."}</p></div></div>
      <details className="audit-details"><summary>Justification auditable du risque</summary><ul>{impact.risk_assessment.explanation.map((line: string) => <li key={line}>{line}</li>)}</ul><p className="small"><b>Limites de métadonnées :</b> {impact.missing_metadata.length ? impact.missing_metadata.join(" · ") : "Aucune limite détectée dans ce périmètre."}</p><p className="small"><b>Preuves :</b> {impact.evidence_bundle.items.map((item: any) => item.evidence_id).join(", ")}</p></details>
    </section>}

    {plan && <section className="panel action-panel"><div><p className="kicker">Étape 4</p><h2>Critique NVIDIA Build</h2><p>Un troisième avis utile au débat. Il ne remplace jamais la double revue finale et ne modifie pas le plan seul.</p></div><button className="secondary" onClick={runCritique} disabled={busy !== null}>{busy === "critique" ? "Critique en cours…" : "Lancer la critique NVIDIA"}</button></section>}
    {critique && <section className="panel critique"><div className="panel-heading"><div><p className="kicker">Avis consultatif · {critique.model}</p><h2>Résultat NVIDIA</h2></div><span className="badge neutral">confiance {Math.round(critique.confidence * 100)}%</span></div><p>{critique.summary}</p><div className="issues">{critique.issues.map((issue, index) => <article key={`${issue.finding}-${index}`}><b className={`badge ${statusTone(issue.severity === "CRITICAL" ? "FAIL" : "WARN")}`}>{issue.severity}</b><p>{issue.finding}</p><small>Preuves : {issue.evidence_ids.join(", ") || "non citées"}</small></article>)}</div><p className="small"><b>Révisions suggérées :</b> {critique.recommended_revisions.join(" · ") || "Aucune"}</p></section>}

    {plan && <section className="panel action-panel judges-action"><div><p className="kicker">Étape 5 · action payante éventuelle</p><h2>Revue finale indépendante</h2><p>OpenAI et Groq reçoivent le même dossier séparément et ne voient pas le verdict de l’autre. Aucun accès DataHub en écriture.</p></div><button className="primary" onClick={runJudges} disabled={busy !== null}>{busy === "judges" ? "Juges en cours…" : "Lancer OpenAI + Groq"}</button></section>}
    {judging && <section className="panel judges"><div className="panel-heading"><div><p className="kicker">Run serveur · {judging.run_id}</p><h2>Double revue</h2></div><span className={`badge ${statusTone(judging.result.aggregate_decision?.decision)}`}>{judging.result.aggregate_decision?.decision ?? "GATE 0"}</span></div>
      {!judging.result.deterministic_validation.passed && <div className="banner error">Gate 0 bloqué : {judging.result.deterministic_validation.errors.join(" · ")}</div>}
      <div className="judge-grid">{[judging.result.openai_verdict, judging.result.groq_verdict].map((verdict) => verdict && <JudgeCard key={verdict.judge_provider} verdict={verdict} />)}</div>
      <p className="small"><b>Décision :</b> {judging.result.aggregate_decision?.rationale ?? "Validation déterministe non réussie."}</p>
      <details className="audit-details"><summary>Justification auditable de la revue</summary><p><b>Gate 0 :</b> {judging.result.deterministic_validation.passed ? "preuves et invariants contrôlés avant les juges" : judging.result.deterministic_validation.errors.join(" · ")}</p><p>Les justifications ci-dessus sont des résumés factuels produits par les juges. Les chaînes de pensée privées ne sont ni affichées ni stockées.</p></details>
      {judging.result.aggregate_decision?.decision === "FINALIZE_READ_ONLY" && <button className="secondary" onClick={prepareWriteback} disabled={busy !== null}>{busy === "prepare" ? "Préparation…" : "Préparer la proposition HITL"}</button>}
    </section>}

    {proposal && <section className="panel approval"><div className="panel-heading"><div><p className="kicker">Étape 6 · approbation humaine requise</p><h2>Proposition de write-back</h2></div><span className={`badge ${statusTone(proposal.status)}`}>{proposal.status}</span></div><p><b>Cible :</b> <code>{proposal.target_asset_urn}</code></p><p><b>Mutation autorisée :</b> {proposal.allowed_mutations.join(", ")}</p><details><summary>Voir le document et le snapshot</summary><pre>{proposal.document_content}</pre><pre>{JSON.stringify(proposal.snapshot, null, 2)}</pre></details><div className="approval-actions"><button className="primary" onClick={() => humanDecision("APPROVE_REPORT")} disabled={busy !== null || proposal.status !== "PENDING_APPROVAL"}>Approuver l’écriture</button><button className="secondary" onClick={() => humanDecision("REQUEST_REVISION")} disabled={busy !== null || proposal.status !== "PENDING_APPROVAL"}>Demander une révision</button><button className="danger" onClick={() => humanDecision("REJECT")} disabled={busy !== null || proposal.status !== "PENDING_APPROVAL"}>Rejeter</button></div></section>}

    <section className="panel history"><p className="kicker">Historique et évaluations</p><h2>Exécutions récentes</h2>{persistedHistory.length ? <ul>{persistedHistory.map((item) => <li key={item.run_id}><code>{item.run_id.slice(0, 8)}</code> · <b className={`badge ${statusTone(item.decision ?? undefined)}`}>{item.decision ?? "GATE 0"}</b> · OpenAI {item.openai_status ?? "—"} · Groq {item.groq_status ?? "—"}</li>)}</ul> : <p className="small">Aucune revue persistée pour le moment.</p>} {history.length > 0 && <p className="small">Session : {history[0]}</p>}</section>
  </main>;
}

function JudgeCard({ verdict }: { verdict: Verdict }) {
  return <article className="judge-card"><div><p className="kicker">{verdict.judge_provider}</p><h3>{verdict.judge_model}</h3></div><span className={`badge ${statusTone(verdict.verdict)}`}>{verdict.verdict}</span><div className="score-grid">{Object.entries(verdict.scores).map(([name, score]) => <span key={name}>{name.replace("_", " ")}<b>{score}/5</b></span>)}</div>{verdict.audit_rationale.length > 0 && <details className="audit-details"><summary>Justification auditable</summary><ul>{verdict.audit_rationale.map((line) => <li key={line}>{line}</li>)}</ul></details>}{verdict.critical_errors.length > 0 && <p className="critical"><b>Erreurs critiques :</b> {verdict.critical_errors.join(" · ")}</p>}{verdict.repair_instructions.length > 0 && <p className="small"><b>Réparation :</b> {verdict.repair_instructions.join(" · ")}</p>}<p className="small">Confiance {Math.round(verdict.confidence * 100)}%</p></article>;
}
