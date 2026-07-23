import { FormEvent, Fragment, lazy, Suspense, useEffect, useMemo, useState } from "react";
import "./styles.css";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const demoAsset = "urn:li:dataset:(urn:li:dataPlatform:dbt,b2fd91.order_entry_db.order_entry.orders,PROD)";
const ForceGraph3D = lazy(() => import("react-force-graph-3d"));

type ChangeType = "ADD_COLUMN" | "RENAME_COLUMN" | "CHANGE_COLUMN_TYPE" | "DROP_COLUMN";
type ApiError = { detail?: string };
type Health = { status: string; environment: string; datahub: "configured" | "not_configured"; llm_providers: "configured" | "partial" | "not_configured"; qdrant: "configured" | "not_configured"; demo_mode: boolean };
type ImpactReport = Record<string, any>;
type RemediationPlan = Record<string, any>;
type Critique = { model: string; summary: string; confidence: number; issues: Array<{ severity: string; finding: string; evidence_ids: string[] }>; recommended_revisions: string[] };
type Verdict = { judge_provider: string; judge_model: string; verdict: string; confidence: number; scores: Record<string, number>; critical_errors: string[]; repair_instructions: string[]; audit_rationale: string[] };
type StoredJudging = { run_id: string; result: { deterministic_validation: { passed: boolean; errors: string[] }; openai_verdict: Verdict | null; groq_verdict: Verdict | null; aggregate_decision: { decision: string; human_review_required: boolean; rationale: string } | null } };
type Proposal = { run_id: string; status: string; target_asset_urn: string; document_content: string; allowed_mutations: string[]; snapshot: Record<string, unknown>; idempotency_key: string };
type RunSummary = { run_id: string; decision: string | null; openai_status: string | null; groq_status: string | null };
type WorkflowGraph = { nodes: Array<{ id: string; label: string; kind: string; status: string; description: string }>; edges: Array<{ source: string; target: string; label?: string | null }>; tracing_enabled: boolean; tracing_project?: string | null };
type CatalogAction = { timestamp: string; action: string; detail: string };
type CatalogNode = { urn: string; label: string; entity_type: string; platform_urn?: string | null; owner_urns: string[]; degree?: number | null; recent_actions: CatalogAction[] };
type CatalogEdge = { source_urn: string; target_urn: string; direction: string; hops: number };
type CatalogGraph = { nodes: CatalogNode[]; edges: CatalogEdge[]; truncated: boolean };
type CatalogCacheStatus = { state: "IDLE" | "RUNNING" | "READY" | "STALE" | "FAILED"; loaded_assets: number; loaded_edges: number; message: string; last_updated_at?: string | null; refresh_reason?: string | null };
type CatalogCacheSnapshot = { status: CatalogCacheStatus; graph: CatalogGraph };
type RagStatus = { state: "IDLE" | "RUNNING" | "COMPLETED" | "FAILED"; indexed_assets: number; total_assets: number; message: string };
type ChatMemory = { session_id?: string | null; enabled: boolean; message_count: number; max_turns: number; last_updated_at?: string | null };
type ChatReply = { answer: string; citations: Array<{ urn: string; label: string; entity_type: string; platform_urn?: string | null; source: string; score?: number | null }>; verification_note: string; verification?: { passed: boolean; checks: string[]; issues: string[] } | null; evidence: Array<{ id: string; kind: string; asset_urn: string; summary: string; facts: string[] }>; action_proposal: { action: "NONE" | "ANALYZE_IMPACT" | "HITL_WRITEBACK"; requires_confirmation: boolean; reason: string; required_fields: string[] }; agent_trace: Array<{ id: string; label: string; status: string; detail: string }>; memory?: ChatMemory | null; model_usage?: { model?: string | null; input_tokens: number; output_tokens: number; total_tokens: number; estimated_cost_usd?: number | null } | null };

async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, { method: body ? "POST" : "GET", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  if (!response.ok) {
    const error = await response.json().catch(() => ({})) as ApiError;
    throw new Error(error.detail ?? `Erreur API (${response.status})`);
  }
  return response.json() as Promise<T>;
}

async function deleteRequest<T>(path: string): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, { method: "DELETE" });
  if (!response.ok) {
    const error = await response.json().catch(() => ({})) as ApiError;
    throw new Error(error.detail ?? `Erreur API (${response.status})`);
  }
  return response.json() as Promise<T>;
}

function getChatSessionId() {
  const key = "lineageguard-chat-session";
  const existing = window.localStorage.getItem(key);
  if (existing) return existing;
  const sessionId = crypto.randomUUID().replaceAll("-", "");
  window.localStorage.setItem(key, sessionId);
  return sessionId;
}

function statusTone(value?: string) {
  if (["PASS", "FINALIZE_READ_ONLY", "COMPLETED"].includes(value ?? "")) return "good";
  if (["FAIL", "BLOCKED", "REJECTED", "FAILED"].includes(value ?? "")) return "bad";
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
  const [history, setHistory] = useState<RunSummary[]>([]);
  const [workflowGraph, setWorkflowGraph] = useState<WorkflowGraph | null>(null);
  const [catalogQuery, setCatalogQuery] = useState("");
  const [catalogGraph, setCatalogGraph] = useState<CatalogGraph | null>(null);
  const [catalogCache, setCatalogCache] = useState<CatalogCacheStatus | null>(null);
  const [catalogOffset, setCatalogOffset] = useState(0);
  const [catalogHasMore, setCatalogHasMore] = useState(false);
  const [selectedCatalogNode, setSelectedCatalogNode] = useState<CatalogNode | null>(null);
  const [catalogTypeFilter, setCatalogTypeFilter] = useState("ALL");
  const [catalogPlatformFilter, setCatalogPlatformFilter] = useState("ALL");
  const [catalogBusy, setCatalogBusy] = useState<string | null>(null);
  const [ragStatus, setRagStatus] = useState<RagStatus | null>(null);
  const [chatInput, setChatInput] = useState("");
  const [chatReply, setChatReply] = useState<ChatReply | null>(null);
  const [chatBusy, setChatBusy] = useState<string | null>(null);
  const [chatSessionId] = useState(getChatSessionId);
  const [chatMemoryEnabled, setChatMemoryEnabled] = useState(true);
  const [chatMemory, setChatMemory] = useState<ChatMemory | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    request<Health>("/api/v1/health").then(setHealth).catch(() => setHealth(null));
    request<RunSummary[]>("/api/v1/judges/history").then(setHistory).catch(() => setHistory([]));
    request<WorkflowGraph>("/api/v1/workflows/graph").then(setWorkflowGraph).catch(() => setWorkflowGraph(null));
    request<RagStatus>("/api/v1/chat/index/status").then(setRagStatus).catch(() => setRagStatus(null));
    request<ChatMemory>(`/api/v1/chat/memory/${chatSessionId}`).then(setChatMemory).catch(() => setChatMemory(null));
    request<CatalogCacheSnapshot>("/api/v1/datahub/catalog/cache").then(applyCatalogCache).catch(() => setCatalogCache(null));
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => request<CatalogCacheSnapshot>("/api/v1/datahub/catalog/cache").then(applyCatalogCache).catch(() => undefined), 5000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (ragStatus?.state !== "RUNNING") return;
    const timer = window.setInterval(() => request<RagStatus>("/api/v1/chat/index/status").then(setRagStatus).catch(() => undefined), 2500);
    return () => window.clearInterval(timer);
  }, [ragStatus?.state]);

  const changeNeedsValue = changeType === "RENAME_COLUMN" || changeType === "CHANGE_COLUMN_TYPE";
  const payload = useMemo(() => ({ asset_urn: assetUrn.trim(), change_type: changeType, column_name: columnName.trim() || undefined, new_value: changeNeedsValue ? newValue.trim() : undefined, reason: reason.trim(), environment: "PRODUCTION", lineage_depth: depth, column_nullable: changeType === "ADD_COLUMN" ? true : undefined, type_change_compatible: changeType === "CHANGE_COLUMN_TYPE" ? false : undefined }), [assetUrn, changeType, columnName, newValue, reason, depth, changeNeedsValue]);
  const catalogTypes = useMemo(() => [...new Set(catalogGraph?.nodes.map((node) => node.entity_type) ?? [])].sort(), [catalogGraph]);
  const catalogPlatforms = useMemo(() => [...new Set((catalogGraph?.nodes.map((node) => node.platform_urn).filter(Boolean) ?? []) as string[])].sort(), [catalogGraph]);
  const visibleCatalogNodes = useMemo(() => (catalogGraph?.nodes ?? []).filter((node) => (catalogTypeFilter === "ALL" || node.entity_type === catalogTypeFilter) && (catalogPlatformFilter === "ALL" || node.platform_urn === catalogPlatformFilter)), [catalogGraph, catalogTypeFilter, catalogPlatformFilter]);

  function resetAfterImpact() { setCritique(null); setJudging(null); setProposal(null); }
  function mergeCatalogGraph(next: CatalogGraph) {
    setCatalogGraph((current) => {
      if (!current) return next;
      const nodes = new Map(current.nodes.map((node) => [node.urn, node]));
      next.nodes.forEach((node) => nodes.set(node.urn, node));
      const edges = new Map(current.edges.map((edge) => [`${edge.source_urn}:${edge.target_urn}:${edge.direction}`, edge]));
      next.edges.forEach((edge) => edges.set(`${edge.source_urn}:${edge.target_urn}:${edge.direction}`, edge));
      return { ...next, nodes: [...nodes.values()], edges: [...edges.values()], truncated: current.truncated || next.truncated };
    });
  }
  function applyCatalogCache(snapshot: CatalogCacheSnapshot) {
    setCatalogCache(snapshot.status);
    setCatalogGraph(snapshot.graph);
    setCatalogHasMore(false);
    setSelectedCatalogNode((current) => snapshot.graph.nodes.find((node) => node.urn === current?.urn) ?? snapshot.graph.nodes[0] ?? null);
  }
  async function refreshHistory() { try { setHistory(await request<RunSummary[]>("/api/v1/judges/history")); } catch { /* non-critical */ } }
  async function runImpact(event: FormEvent) {
    event.preventDefault(); setBusy("impact"); setError(null); setNotice(null);
    try {
      const execution = await request<{ impact_report: ImpactReport; remediation_plan: RemediationPlan; graph: WorkflowGraph }>("/api/v1/workflows/analyze", payload);
      resetAfterImpact(); setImpact(execution.impact_report); setPlan(execution.remediation_plan); setWorkflowGraph(execution.graph);
      setNotice("Impact et plan déterministe générés. Aucun LLM ni changement DataHub n’a été déclenché.");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Analyse impossible"); } finally { setBusy(null); }
  }
  async function runCritique() {
    if (!impact || !plan) return; setBusy("critique"); setError(null);
    try { const result = await request<{ critique: Critique; graph: WorkflowGraph }>("/api/v1/workflows/critique", { impact_report: impact, remediation_plan: plan }); setCritique(result.critique); setWorkflowGraph(result.graph); setNotice("Critique NVIDIA terminée : elle est consultative et ne modifie aucun plan."); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Critique NVIDIA impossible"); } finally { setBusy(null); }
  }
  async function runJudges() {
    if (!impact || !plan) return; setBusy("judges"); setError(null);
    try { const result = await request<{ judging: StoredJudging; graph: WorkflowGraph }>("/api/v1/workflows/judge", { impact_report: impact, remediation_plan: plan, repair_cycles: 0 }); setJudging(result.judging); setWorkflowGraph(result.graph); await refreshHistory(); setNotice("Les juges ont été exécutés indépendamment."); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Revue des juges impossible"); } finally { setBusy(null); }
  }
  async function searchCatalog(event: FormEvent) {
    event.preventDefault(); if (!catalogQuery.trim()) return; setCatalogBusy("catalog-search"); setError(null);
    try { const graph = await request<CatalogGraph>(`/api/v1/datahub/catalog/search?query=${encodeURIComponent(catalogQuery.trim())}`); setCatalogGraph(graph); setSelectedCatalogNode(graph.nodes[0] ?? null); setNotice(`${graph.nodes.length} actif(s) chargés depuis DataHub.`); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Recherche catalogue impossible"); } finally { setCatalogBusy(null); }
  }
  async function expandCatalog(direction: "UPSTREAM" | "DOWNSTREAM") {
    if (!selectedCatalogNode) return; setCatalogBusy(`catalog-${direction}`); setError(null);
    try { const graph = await request<CatalogGraph>(`/api/v1/datahub/catalog/expand?asset_urn=${encodeURIComponent(selectedCatalogNode.urn)}&direction=${direction}&max_hops=2`); mergeCatalogGraph(graph); setNotice(`Lineage ${direction === "DOWNSTREAM" ? "aval" : "amont"} chargé.`); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Expansion de lineage impossible"); } finally { setCatalogBusy(null); }
  }
  async function loadCatalogSnapshot() {
    setCatalogBusy("catalog-snapshot"); setError(null);
    try {
      let offset = 0; let hasMore = true; let firstPage = true;
      const assetUrns = new Set<string>(); const relationKeys = new Set<string>();
      while (hasMore) {
        const graph = await request<CatalogGraph>(`/api/v1/datahub/catalog/snapshot?max_assets=50&max_edges=300&offset=${offset}`);
        graph.nodes.forEach((node) => assetUrns.add(node.urn));
        graph.edges.forEach((edge) => relationKeys.add(`${edge.source_urn}:${edge.target_urn}:${edge.direction}`));
        if (firstPage) { setCatalogGraph(graph); setSelectedCatalogNode(graph.nodes[0] ?? null); firstPage = false; }
        else { mergeCatalogGraph(graph); }
        offset += 50;
        hasMore = graph.truncated && graph.nodes.length > 0;
        setCatalogOffset(offset); setCatalogHasMore(hasMore);
        setNotice(`Carte 3D : ${assetUrns.size} actifs et ${relationKeys.size} relations chargés${hasMore ? "…" : "."}`);
      }
    }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Carte complète impossible"); } finally { setCatalogBusy(null); }
  }
  async function loadMoreCatalog() {
    setCatalogBusy("catalog-more"); setError(null);
    try {
      const graph = await request<CatalogGraph>(`/api/v1/datahub/catalog/snapshot?max_assets=50&max_edges=300&offset=${catalogOffset}`);
      mergeCatalogGraph(graph); setCatalogOffset((value) => value + 50); setCatalogHasMore(graph.truncated);
      setNotice(`${graph.nodes.length} actifs supplémentaires intégrés à la carte 3D.`);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Chargement supplémentaire impossible"); } finally { setCatalogBusy(null); }
  }
  async function refreshServerCatalog() {
    setCatalogBusy("catalog-cache-refresh"); setError(null);
    try {
      const status = await request<CatalogCacheStatus>("/api/v1/datahub/catalog/cache/refresh", {});
      setCatalogCache(status);
      setNotice("Actualisation de la carte 3D demandée au serveur. Le graphe actuel reste utilisable pendant le chargement.");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Actualisation de la carte impossible"); } finally { setCatalogBusy(null); }
  }
  async function startRagIndex() {
    setChatBusy("index"); setError(null);
    try { const status = await request<RagStatus>("/api/v1/chat/index/ingest", {}); setRagStatus(status); setNotice("Indexation RAG lancée en arrière-plan. Les agents restent utilisables."); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Indexation RAG impossible"); } finally { setChatBusy(null); }
  }
  async function askChat(event: FormEvent) {
    event.preventDefault(); if (!chatInput.trim()) return; setChatBusy("query"); setError(null);
    try { const reply = await request<ChatReply>("/api/v1/chat/query", { message: chatInput.trim(), session_id: chatSessionId, memory_enabled: chatMemoryEnabled }); setChatReply(reply); setChatMemory(reply.memory ?? null); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Question impossible"); } finally { setChatBusy(null); }
  }
  async function clearChatMemory() {
    setChatBusy("memory-clear"); setError(null);
    try { const memory = await deleteRequest<ChatMemory>(`/api/v1/chat/memory/${chatSessionId}`); setChatMemory(memory); setChatReply(null); setNotice("Mémoire de cette conversation effacée."); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Effacement de la mémoire impossible"); } finally { setChatBusy(null); }
  }
  async function runChatAnalysis() {
    if (!window.confirm("Lancer l’analyse d’impact en lecture seule avec les champs du formulaire ?")) return;
    setChatBusy("analysis"); setError(null);
    try {
      const execution = await request<{ impact_report: ImpactReport; remediation_plan: RemediationPlan; graph: WorkflowGraph }>("/api/v1/chat/execute-analysis", { change_request: payload, confirmed: true });
      resetAfterImpact(); setImpact(execution.impact_report); setPlan(execution.remediation_plan); setWorkflowGraph(execution.graph); setNotice("Analyse DataHub lancée depuis le chat : aucune écriture n’a été exécutée.");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Analyse depuis le chat impossible"); } finally { setChatBusy(null); }
  }
  async function prepareWriteback() {
    if (!judging) return; setBusy("prepare"); setError(null);
    try { const result = await request<Proposal>("/api/v1/writebacks/prepare", { run_id: judging.run_id, idempotency_key: crypto.randomUUID() }); setProposal(result); setNotice("Proposition HITL enregistrée, sans écriture DataHub."); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Préparation impossible"); } finally { setBusy(null); }
  }
  async function decide(decision: "APPROVE_REPORT" | "REQUEST_REVISION" | "REJECT") {
    if (!proposal || (decision === "APPROVE_REPORT" && !window.confirm("Confirmer la demande d’écriture contrôlée dans DataHub ?"))) return;
    setBusy("approval"); setError(null);
    try { const result = await request<Proposal>(`/api/v1/writebacks/${proposal.run_id}/approve`, { decision, comment: "Décision prise depuis l’interface.", idempotency_key: proposal.idempotency_key }); setProposal(result); setNotice(`Décision enregistrée : ${result.status}.`); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Décision impossible"); } finally { setBusy(null); }
  }

  return <main className="shell">
    <header className="topbar"><div><p className="eyebrow">Build with DataHub · Agents That Do Real Work</p><h1>LineageGuard <span>AI</span></h1></div><div className={`api-state ${health ? "online" : "offline"}`}><i /> API {health ? `${health.status} · ${health.environment}` : "indisponible"}</div></header>
    <section className="guardrail"><strong>Mode sûr</strong><span>DataHub reste en lecture seule ; les juges sont manuels et toute écriture exige le HITL.</span></section>
    {error && <div className="banner error">{error}</div>}{notice && <div className="banner notice">{notice}</div>}
    {workflowGraph && <section className="panel graph-panel"><div className="panel-heading"><div><p className="kicker">LangGraph</p><h2>Workflow dynamique</h2></div><span className={`badge ${workflowGraph.tracing_enabled ? "good" : "neutral"}`}>{workflowGraph.tracing_enabled ? "LangSmith actif" : "tracing désactivé"}</span></div><WorkflowDiagram graph={workflowGraph} /><p className="small">{workflowGraph.tracing_enabled ? `Traces dans ${workflowGraph.tracing_project ?? "le projet configuré"}.` : "Le tracing est opt-in et aucun secret n’est affiché."}</p></section>}
    <CatalogExplorer query={catalogQuery} onQuery={setCatalogQuery} onSearch={searchCatalog} onSnapshot={refreshServerCatalog} onLoadMore={loadMoreCatalog} hasMore={catalogHasMore} busy={catalogBusy} types={catalogTypes} platforms={catalogPlatforms} typeFilter={catalogTypeFilter} platformFilter={catalogPlatformFilter} onType={setCatalogTypeFilter} onPlatform={setCatalogPlatformFilter} graph={catalogGraph} nodes={visibleCatalogNodes} selected={selectedCatalogNode} onSelect={setSelectedCatalogNode} onExpand={expandCatalog} cache={catalogCache} />
    <ChatPanel status={ragStatus} reply={chatReply} input={chatInput} onInput={setChatInput} onIndex={startRagIndex} onAsk={askChat} onAnalyze={runChatAnalysis} busy={chatBusy} memory={chatMemory} memoryEnabled={chatMemoryEnabled} onMemoryEnabled={setChatMemoryEnabled} onClearMemory={clearChatMemory} />
    <div className="layout"><section className="panel request-panel"><div className="panel-heading"><div><p className="kicker">Étape 1</p><h2>Demande de changement</h2></div><span className="readonly">Aucune mutation</span></div><form onSubmit={runImpact}><label>Actif DataHub<input value={assetUrn} onChange={(event) => setAssetUrn(event.target.value)} required /></label><div className="two-col"><label>Type de changement<select value={changeType} onChange={(event) => setChangeType(event.target.value as ChangeType)}><option value="ADD_COLUMN">Ajouter une colonne</option><option value="RENAME_COLUMN">Renommer une colonne</option><option value="CHANGE_COLUMN_TYPE">Changer le type</option><option value="DROP_COLUMN">Supprimer une colonne</option></select></label><label>Profondeur de lineage<select value={depth} onChange={(event) => setDepth(Number(event.target.value))}>{[1, 2, 3, 4, 5].map((value) => <option key={value} value={value}>{value} saut(s)</option>)}</select></label></div><div className="two-col"><label>Colonne<input value={columnName} onChange={(event) => setColumnName(event.target.value)} required={changeType !== "ADD_COLUMN"} /></label>{changeNeedsValue && <label>{changeType === "RENAME_COLUMN" ? "Nouveau nom" : "Nouveau type"}<input value={newValue} onChange={(event) => setNewValue(event.target.value)} required /></label>}</div><label>Justification<textarea value={reason} onChange={(event) => setReason(event.target.value)} required minLength={5} /></label><button className="primary" disabled={busy !== null}>{busy === "impact" ? "Analyse en cours…" : "Analyser l’impact et générer le plan"}</button></form></section><aside className="panel workflow"><p className="kicker">Contrôles</p><h2>Workflow gouverné</h2><div className="control"><span>DataHub MCP</span><b className="chip good">lecture seule</b></div><div className="control"><span>NVIDIA Build</span><b className="chip">consultatif</b></div><div className="control"><span>OpenAI + Groq</span><b className="chip warn">manuel</b></div><div className="control"><span>Write-back</span><b className="chip bad">HITL obligatoire</b></div></aside></div>
    {impact && <section className="panel report"><div className="panel-heading"><div><p className="kicker">Étapes 2–3</p><h2>Rapport d’impact et plan</h2></div><span className={`badge ${statusTone(impact.risk_assessment.level)}`}>{impact.risk_assessment.level} · {impact.risk_assessment.score}/100</span></div><div className="metrics"><div><b>{impact.blast_radius}</b><span>actifs impactés</span></div><div><b>{impact.evidence_bundle.items.length}</b><span>preuves DataHub</span></div><div><b>{Math.round(impact.confidence * 100)}%</b><span>confiance</span></div></div><LineageDiagram source={impact.request.asset_urn} impacts={impact.impacted_assets} /><div className="split"><div><h3>Actifs et lineage</h3><ul className="asset-list">{impact.impacted_assets.slice(0, 8).map((item: any) => <li key={item.asset_urn}><code>{item.asset_urn}</code><span>{item.impact_type} · {item.criticality}</span></li>)}</ul></div><div><h3>Plan de remédiation</h3><ol>{plan?.migration_steps.map((step: any) => <li key={step.order}><b>{step.action}</b><span>{step.rationale}</span></li>)}</ol></div></div><details className="audit-details"><summary>Justification auditable</summary><ul>{impact.risk_assessment.explanation.map((line: string) => <li key={line}>{line}</li>)}</ul></details></section>}
    {plan && <section className="panel action-panel"><div><p className="kicker">Étape 4</p><h2>Critique NVIDIA Build</h2><p>Consultative : aucun changement automatique du plan.</p></div><button className="secondary" onClick={runCritique} disabled={busy !== null}>{busy === "critique" ? "Critique en cours…" : "Lancer la critique NVIDIA"}</button></section>}
    {critique && <section className="panel critique"><div className="panel-heading"><div><p className="kicker">Avis consultatif · {critique.model}</p><h2>Résultat NVIDIA</h2></div><span className="badge neutral">confiance {Math.round(critique.confidence * 100)}%</span></div><p>{critique.summary}</p>{critique.issues.map((issue, index) => <article className="issue" key={`${issue.finding}-${index}`}><b>{issue.severity}</b><p>{issue.finding}</p></article>)}</section>}
    {plan && <section className="panel action-panel"><div><p className="kicker">Étape 5 · action externe</p><h2>Revue finale indépendante</h2><p>OpenAI et Groq reçoivent le même dossier sans voir le verdict de l’autre.</p></div><button className="primary" onClick={runJudges} disabled={busy !== null}>{busy === "judges" ? "Juges en cours…" : "Lancer OpenAI + Groq"}</button></section>}
    {judging && <section className="panel judges"><div className="panel-heading"><div><p className="kicker">Run serveur · {judging.run_id}</p><h2>Double revue</h2></div><span className={`badge ${statusTone(judging.result.aggregate_decision?.decision)}`}>{judging.result.aggregate_decision?.decision ?? "GATE 0"}</span></div>{!judging.result.deterministic_validation.passed && <div className="banner error">Gate 0 bloqué : {judging.result.deterministic_validation.errors.join(" · ")}</div>}<div className="judge-grid">{[judging.result.openai_verdict, judging.result.groq_verdict].map((verdict) => verdict && <JudgeCard key={verdict.judge_provider} verdict={verdict} />)}</div><p className="small"><b>Décision :</b> {judging.result.aggregate_decision?.rationale}</p>{judging.result.aggregate_decision?.decision === "FINALIZE_READ_ONLY" && <button className="secondary" onClick={prepareWriteback} disabled={busy !== null}>Préparer la proposition HITL</button>}</section>}
    {proposal && <section className="panel approval"><div className="panel-heading"><div><p className="kicker">Étape 6 · HITL</p><h2>Proposition de write-back</h2></div><span className={`badge ${statusTone(proposal.status)}`}>{proposal.status}</span></div><p><b>Mutation autorisée :</b> {proposal.allowed_mutations.join(", ")}</p><details><summary>Document et snapshot</summary><pre>{proposal.document_content}</pre><pre>{JSON.stringify(proposal.snapshot, null, 2)}</pre></details><div className="approval-actions"><button className="primary" onClick={() => decide("APPROVE_REPORT")} disabled={busy !== null || proposal.status !== "PENDING_APPROVAL"}>Approuver l’écriture</button><button className="secondary" onClick={() => decide("REQUEST_REVISION")} disabled={busy !== null || proposal.status !== "PENDING_APPROVAL"}>Demander une révision</button><button className="danger" onClick={() => decide("REJECT")} disabled={busy !== null || proposal.status !== "PENDING_APPROVAL"}>Rejeter</button></div></section>}
    <section className="panel history"><p className="kicker">Historique</p><h2>Exécutions récentes</h2>{history.length ? <ul>{history.map((item) => <li key={item.run_id}><code>{item.run_id.slice(0, 8)}</code> · <b className={`badge ${statusTone(item.decision ?? undefined)}`}>{item.decision ?? "GATE 0"}</b> · OpenAI {item.openai_status ?? "—"} · Groq {item.groq_status ?? "—"}</li>)}</ul> : <p className="small">Aucune revue persistée.</p>}</section>
  </main>;
}

function CatalogExplorer({ query, onQuery, onSearch, onSnapshot, onLoadMore, hasMore, busy, types, platforms, typeFilter, platformFilter, onType, onPlatform, graph, nodes, selected, onSelect, onExpand, cache }: { query: string; onQuery: (value: string) => void; onSearch: (event: FormEvent) => void; onSnapshot: () => void; onLoadMore: () => void; hasMore: boolean; busy: string | null; types: string[]; platforms: string[]; typeFilter: string; platformFilter: string; onType: (value: string) => void; onPlatform: (value: string) => void; graph: CatalogGraph | null; nodes: CatalogNode[]; selected: CatalogNode | null; onSelect: (node: CatalogNode) => void; onExpand: (direction: "UPSTREAM" | "DOWNSTREAM") => void; cache: CatalogCacheStatus | null }) {
  const cacheReady = cache?.state === "READY";
  return <section className="panel catalog-panel"><div className="panel-heading"><div><p className="kicker">DataHub MCP · lecture seule</p><h2>Carte 3D du catalogue et du lineage</h2></div><button className="primary" onClick={onSnapshot} disabled={busy !== null}>{busy === "catalog-cache-refresh" ? "Actualisation…" : "Actualiser depuis DataHub"}</button></div><div className="catalog-cache-status"><span className={`badge ${cacheReady ? "good" : cache?.state === "FAILED" ? "bad" : "warn"}`}>{cache?.state ?? "CONNECTING"}</span><span>{cache?.message ?? "Le serveur prépare le cache de la carte 3D."}</span>{cache && <small>{cache.loaded_assets} actifs · {cache.loaded_edges} relations · {cache.last_updated_at ? `mis à jour ${new Date(cache.last_updated_at).toLocaleTimeString()}` : "pas encore prêt"}{cache.refresh_reason ? ` · ${cache.refresh_reason}` : ""}</small>}</div><p className="small">Le serveur commence ce chargement à son démarrage, une seule fois par instance. Le navigateur lit le cache, puis le synchronise toutes les 5 secondes. Les actions LineageGuard déclenchent une actualisation immédiate; les changements externes sont détectés par le polling serveur.</p><form className="catalog-controls" onSubmit={onSearch}><label>Rechercher un actif DataHub<input value={query} onChange={(event) => onQuery(event.target.value)} placeholder="orders, dashboard, dbt…" /></label><button className="secondary" disabled={busy !== null}>{busy === "catalog-search" ? "Recherche…" : "Rechercher"}</button><label>Type<select value={typeFilter} onChange={(event) => onType(event.target.value)}><option value="ALL">Tous</option>{types.map((value) => <option key={value}>{value}</option>)}</select></label><label>Plateforme<select value={platformFilter} onChange={(event) => onPlatform(event.target.value)}><option value="ALL">Toutes</option>{platforms.map((value) => <option key={value}>{value}</option>)}</select></label></form>{graph ? <><CatalogThreeD nodes={nodes} edges={graph.edges} onSelect={onSelect} /><CatalogDiagram nodes={nodes} edges={graph.edges} selected={selected?.urn} onSelect={onSelect} />{hasMore && <div className="catalog-more"><p className="small">D’autres actifs existent dans DataHub. Ajoutez-les à la même carte 3D sans lancer de recherche.</p><button className="secondary" onClick={onLoadMore} disabled={busy !== null}>{busy === "catalog-more" ? "Ajout en cours…" : "Charger 50 actifs supplémentaires"}</button></div>}{selected && <div className="catalog-detail"><div><p className="kicker">Actif sélectionné</p><code>{selected.urn}</code><p className="small">{selected.entity_type} · {selected.platform_urn ?? "plateforme non renseignée"} · {selected.owner_urns.length} owner(s)</p>{selected.recent_actions.length > 0 && <details className="catalog-activity"><summary>Actions LineageGuard récentes ({selected.recent_actions.length})</summary><ul>{selected.recent_actions.map((item) => <li key={`${item.timestamp}-${item.action}`}><b>{item.action}</b><span>{item.detail}</span><small>{new Date(item.timestamp).toLocaleString()}</small></li>)}</ul></details>}</div><div className="catalog-actions"><button className="secondary" onClick={() => onExpand("UPSTREAM")} disabled={busy !== null}>Charger l’amont</button><button className="secondary" onClick={() => onExpand("DOWNSTREAM")} disabled={busy !== null}>Charger l’aval</button></div></div>}</> : <p className="small">Le cache serveur charge le catalogue. La carte apparaîtra automatiquement sans action du navigateur.</p>}</section>;
}

function ChatPanel({ status, reply, input, onInput, onIndex, onAsk, onAnalyze, busy, memory, memoryEnabled, onMemoryEnabled, onClearMemory }: { status: RagStatus | null; reply: ChatReply | null; input: string; onInput: (value: string) => void; onIndex: () => void; onAsk: (event: FormEvent) => void; onAnalyze: () => void; busy: string | null; memory: ChatMemory | null; memoryEnabled: boolean; onMemoryEnabled: (enabled: boolean) => void; onClearMemory: () => void }) {
  const ready = status?.state === "COMPLETED";
  return <section className="panel chat-panel"><div className="panel-heading"><div><p className="kicker">Agentic RAG + MCP</p><h2>Assistant DataHub vérifié</h2></div><span className={`badge ${ready ? "good" : "neutral"}`}>{status?.state ?? "INDISPONIBLE"}</span></div><p className="small">Planification → Qdrant → outils MCP → raisonnement → vérification. Le chat ne peut pas écrire dans DataHub.</p><div className="chat-index"><span>{status?.message ?? "Démarrez l’indexation contrôlée."}{status?.state === "RUNNING" ? ` ${status.indexed_assets} actifs indexés.` : ""}</span><button className="secondary" onClick={onIndex} disabled={busy !== null || status?.state === "RUNNING"}>{busy === "index" || status?.state === "RUNNING" ? "Indexation…" : "Indexer les métadonnées DataHub"}</button></div><div className="chat-memory"><label><input type="checkbox" checked={memoryEnabled} onChange={(event) => onMemoryEnabled(event.target.checked)} disabled={busy !== null} /> Mémoire de conversation</label><span>{memoryEnabled ? `${memory?.message_count ?? 0} tour(s) conservé(s) localement (max. ${memory?.max_turns ?? 0})` : "Désactivée pour la prochaine question"}</span><button className="secondary" onClick={onClearMemory} disabled={busy !== null || !memory?.message_count}>Effacer la mémoire</button></div><p className="small">La mémoire sert seulement à résoudre le contexte entre questions. Chaque affirmation DataHub reste revérifiée par MCP en direct.</p><form className="chat-form" onSubmit={onAsk}><textarea value={input} onChange={(event) => onInput(event.target.value)} placeholder="Ex. Quels dashboards dépendent de orders ?" disabled={!ready || busy !== null} /><button className="primary" disabled={!ready || busy !== null}>{busy === "query" ? "Vérification…" : "Poser la question"}</button></form>{reply && <div className="chat-answer"><p>{reply.answer}</p><p className="small">{reply.verification_note}</p>{reply.model_usage && <p className="small">Usage: {reply.model_usage.model ?? "local"} · {reply.model_usage.total_tokens} tokens · {reply.model_usage.estimated_cost_usd !== null && reply.model_usage.estimated_cost_usd !== undefined ? `$${reply.model_usage.estimated_cost_usd.toFixed(6)}` : "coût non estimé"}</p>}<div className="chat-trace">{reply.agent_trace.map((step) => <article key={step.id}><b>{step.label}</b><small>{step.status}</small><span>{step.detail}</span></article>)}</div><div className="chat-citations">{reply.citations.map((citation) => <code key={`${citation.source}-${citation.urn}`}>{citation.label} · {citation.entity_type} · {citation.source === "datahub_mcp_live" ? "MCP vérifié" : "RAG"}</code>)}</div>{reply.action_proposal.action !== "NONE" && <div className="chat-action"><b>Action proposée : {reply.action_proposal.action}</b><p>{reply.action_proposal.reason}</p>{reply.action_proposal.action === "ANALYZE_IMPACT" && <button className="secondary" onClick={onAnalyze} disabled={busy !== null}>Confirmer l’analyse en lecture seule</button>}{reply.action_proposal.action === "HITL_WRITEBACK" && <p className="small">Le write-back reste disponible uniquement via la proposition HITL existante, après double PASS.</p>}</div>}</div>}</section>;
}

function WorkflowDiagram({ graph }: { graph: WorkflowGraph }) {
  const nodes = new Map(graph.nodes.map((node) => [node.id, node])); const order = ["request", "metadata", "impact", "plan", "critic", "judges", "hitl"];
  return <div className="workflow-diagram" role="img" aria-label="Graphe LangGraph">{order.map((id, index) => { const node = nodes.get(id); const next = nodes.get(order[index + 1]); if (!node) return null; return <Fragment key={id}><article className={`graph-node ${node.status.toLowerCase()}`} title={node.description}><span className="node-kind">{node.kind}</span><b>{node.label}</b><small>{node.status.replace("_", " ")}</small></article>{next && <div className="graph-edge">→</div>}</Fragment>; })}</div>;
}

const graphPalette = ["#4cc9f0", "#f72585", "#fca311", "#80ed99", "#b5179e", "#ffd166", "#90dbf4", "#caffbf"];

function graphColor(group: string) {
  let hash = 0;
  for (let index = 0; index < group.length; index += 1) hash = (hash * 31 + group.charCodeAt(index)) | 0;
  return graphPalette[Math.abs(hash) % graphPalette.length];
}

function CatalogThreeD({ nodes, edges, onSelect }: { nodes: CatalogNode[]; edges: CatalogEdge[]; onSelect: (node: CatalogNode) => void }) {
  const groups = useMemo(() => [...new Set(nodes.map((node) => node.platform_urn ?? node.entity_type))].sort(), [nodes]);
  const graphData = useMemo(() => ({
    nodes: nodes.map((node) => ({ ...node, id: node.urn, group: node.platform_urn ?? node.entity_type })),
    links: edges.map((edge) => ({ source: edge.source_urn, target: edge.target_urn, label: `${edge.direction} · ${edge.hops} saut(s)` })),
  }), [nodes, edges]);
  return <><div className="catalog-legend" aria-label="Légende des couleurs">{groups.map((group) => <span key={group}><i style={{ backgroundColor: graphColor(group) }} />{group.replace("urn:li:dataPlatform:", "")}</span>)}</div><p className="small">Survolez un nœud pour voir ses métadonnées et les actions LineageGuard associées; cliquez pour le sélectionner.</p><div className="catalog-3d" role="img" aria-label="Carte 3D interactive des actifs DataHub et de leurs relations"><Suspense fallback={<p className="small">Chargement du moteur 3D…</p>}><ForceGraph3D graphData={graphData} width={980} height={520} backgroundColor="#081225" nodeLabel={(node: object) => catalogNodeTooltip(node as CatalogNode)} nodeColor={(node: object) => graphColor((node as CatalogNode).platform_urn ?? (node as CatalogNode).entity_type)} nodeRelSize={6} linkColor={() => "#6e9ec5"} linkOpacity={0.72} linkLabel={(link: object) => (link as { label: string }).label} linkDirectionalArrowLength={3} linkDirectionalArrowRelPos={1} showNavInfo onNodeClick={(node: object) => onSelect(node as CatalogNode)} /></Suspense></div></>;
}

function catalogNodeTooltip(node: CatalogNode) {
  const actions = node.recent_actions.length ? `<ul>${node.recent_actions.map((item) => `<li><b>${escapeHtml(item.action)}</b>: ${escapeHtml(item.detail)}<br/><small>${escapeHtml(new Date(item.timestamp).toLocaleString())}</small></li>`).join("")}</ul>` : "<p>No LineageGuard action has been recorded for this node in the current server session.</p>";
  return `<div class="catalog-tooltip"><b>${escapeHtml(node.label)}</b><br/>${escapeHtml(node.entity_type)}<br/>Platform: ${escapeHtml(node.platform_urn ?? "unknown")}<br/>Owners: ${node.owner_urns.length}<br/><small>${escapeHtml(node.urn)}</small><hr/><b>Recent actions</b>${actions}</div>`;
}

function escapeHtml(value: string) {
  return value.replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", "\"": "&quot;" })[character] ?? character);
}

function CatalogDiagram({ nodes, edges, selected, onSelect }: { nodes: CatalogNode[]; edges: CatalogEdge[]; selected?: string; onSelect: (node: CatalogNode) => void }) {
  const visible = new Set(nodes.map((node) => node.urn)); const visibleEdges = edges.filter((edge) => visible.has(edge.source_urn) && visible.has(edge.target_urn));
  return <div className="catalog-diagram"><div className="catalog-nodes">{nodes.map((node) => <button type="button" className={`catalog-node ${selected === node.urn ? "selected" : ""}`} onClick={() => onSelect(node)} key={node.urn}><span>{node.entity_type}</span><b>{node.label}</b><small>{node.platform_urn ?? "sans plateforme"}</small>{node.degree != null && <em>{node.degree} saut(s)</em>}</button>)}</div><div className="catalog-edges">{visibleEdges.length ? visibleEdges.map((edge) => <p key={`${edge.source_urn}-${edge.target_urn}-${edge.direction}`}><code>{shortUrn(edge.source_urn)}</code><span>→ {edge.direction === "DOWNSTREAM" ? "aval" : "amont"} · {edge.hops} saut(s) →</span><code>{shortUrn(edge.target_urn)}</code></p>) : <p className="small">Sélectionnez un nœud et chargez son amont ou son aval.</p>}</div></div>;
}

function LineageDiagram({ source, impacts }: { source: string; impacts: Array<{ asset_urn: string; platform_urn?: string | null; criticality: string }> }) { const displayed = impacts.slice(0, 8); return <section className="lineage-diagram"><div className="lineage-source"><span>source DataHub</span><code>{shortUrn(source)}</code></div><div className="lineage-arrows">→</div><div className="lineage-targets">{displayed.map((item) => <article key={item.asset_urn}><b>{item.criticality}</b><code>{shortUrn(item.asset_urn)}</code><small>{item.platform_urn ?? "plateforme inconnue"}</small></article>)}</div></section>; }
function JudgeCard({ verdict }: { verdict: Verdict }) { return <article className="judge-card"><div><p className="kicker">{verdict.judge_provider}</p><h3>{verdict.judge_model}</h3></div><span className={`badge ${statusTone(verdict.verdict)}`}>{verdict.verdict}</span><div className="score-grid">{Object.entries(verdict.scores).map(([name, score]) => <span key={name}>{name.replace("_", " ")}<b>{score}/5</b></span>)}</div>{verdict.audit_rationale.length > 0 && <details className="audit-details"><summary>Justification auditable</summary><ul>{verdict.audit_rationale.map((line) => <li key={line}>{line}</li>)}</ul></details>}{verdict.critical_errors.length > 0 && <p className="critical">{verdict.critical_errors.join(" · ")}</p>}</article>; }
function shortUrn(urn: string) { return urn.length > 58 ? `${urn.slice(0, 26)}…${urn.slice(-28)}` : urn; }
