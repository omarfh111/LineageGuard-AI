import { FormEvent, Suspense, lazy, useEffect, useMemo, useState } from "react";
import App from "./App";
import AppleHome from "./AppleHome";
import "./design-preview.css";
import "./preview-reset.css";
import "./design-v2.css";
import "./motion-typography.css";
import "./motion-fixes.css";
import "./navigation-motion.css";
import "./integration.css";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const ForceGraph3D = lazy(() => import("react-force-graph-3d"));

type Page = "Accueil" | "Cartographie" | "Assistant" | "Nouvelle analyse" | "Suivi" | "Santé" | "Workspace";
type Health = { status: string; environment: string; datahub: string; llm_providers: string; qdrant: string; demo_mode: boolean };
type CatalogNode = { urn: string; label: string; entity_type: string; platform_urn?: string | null; owner_urns: string[]; recent_actions: Array<{ timestamp: string; action: string; detail: string }> };
type CatalogEdge = { source_urn: string; target_urn: string; direction: string; hops: number };
type CatalogCache = { status: { state: string; loaded_assets: number; loaded_edges: number; message: string; last_updated_at?: string | null; refresh_reason?: string | null }; graph: { nodes: CatalogNode[]; edges: CatalogEdge[]; truncated: boolean } };
type RagStatus = { state: string; indexed_assets: number; total_assets: number; message: string; query_available: boolean };
type ChatReply = { answer: string; verification_note: string; citations: Array<{ urn: string; label: string; entity_type: string; platform_urn?: string | null; source: string }>; target_resolution?: { status: string; detail: string; targets: Array<{ urn: string; label: string; entity_type: string; platform_urn?: string | null }> } | null; verification?: { passed: boolean } | null; action_proposal: { action: string; reason: string }; agent_trace: Array<{ id: string; label: string; status: string; detail: string }> };
type WorkflowExecution = { impact_report: { blast_radius: number; confidence: number; risk_assessment: { level: string; score: number }; impacted_assets: Array<{ asset_urn: string; criticality: string }>; evidence_bundle: { items: unknown[] } }; remediation_plan: { migration_steps: Array<{ order: number; action: string; rationale: string }> } };
type RunSummary = { run_id: string; decision: string | null; openai_status: string | null; groq_status: string | null };

async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({})) as { detail?: string };
    throw new Error(error.detail ?? `API error (${response.status})`);
  }
  return response.json() as Promise<T>;
}

function chatSessionId() {
  const key = "lineageguard-chat-session";
  const current = window.localStorage.getItem(key);
  if (current) return current;
  const created = crypto.randomUUID().replaceAll("-", "");
  window.localStorage.setItem(key, created);
  return created;
}

const pages: Page[] = ["Accueil", "Cartographie", "Assistant", "Nouvelle analyse", "Suivi", "Santé", "Workspace"];
const pageSlugs: Record<Page, string> = { Accueil: "", Cartographie: "cartographie", Assistant: "assistant", "Nouvelle analyse": "analyse", Suivi: "suivi", Santé: "sante", Workspace: "espace-avance" };
function pageFromHash(): Page { const slug = window.location.hash.replace(/^#\/?/, ""); return pages.find((page) => pageSlugs[page] === slug) ?? "Accueil"; }

export default function DesignPreview() {
  const [page, setPage] = useState<Page>(pageFromHash);
  const [loading, setLoading] = useState(true);
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    const load = () => request<Health>("/api/v1/health").then(setHealth).catch(() => setHealth(null));
    load();
    const timer = window.setInterval(load, 15000);
    const initial = window.setTimeout(() => setLoading(false), 650);
    return () => { window.clearInterval(timer); window.clearTimeout(initial); };
  }, []);

  useEffect(() => { const sync = () => setPage(pageFromHash()); window.addEventListener("hashchange", sync); return () => window.removeEventListener("hashchange", sync); }, []);

  function go(next: Page) { setPage(next); const hash = pageSlugs[next]; window.location.hash = hash ? `/${hash}` : ""; window.scrollTo({ top: 0, behavior: "smooth" }); }
  const isHealthy = health?.status === "ok";

  return <div className="preview-app">
    {loading && <div className="preview-loader"><div className="loader-logo">LG</div><b>LineageGuard</b><span>Preparing your governed workspace</span><i /></div>}
    <header className="site-nav">
      <button className="preview-brand" onClick={() => go("Accueil")}><span>LG</span><b>LineageGuard</b></button>
      <nav>{pages.map((item) => <button key={item} onClick={() => go(item)} className={page === item ? "selected" : ""}><span>{icon(item)}</span>{item === "Workspace" ? "Espace avancé" : item}</button>)}</nav>
      <div className={`nav-health ${isHealthy ? "healthy" : "unavailable"}`}><i /> {isHealthy ? "Platform operational" : "Checking platform"}</div>
    </header>
    <main className="preview-main">
      {page !== "Accueil" && <header className="preview-top"><div className="crumb"><span>Platform</span><b> / {page === "Workspace" ? "Advanced workspace" : page}</b></div><div className="top-actions"><button className="help" title="Use the acceptance plan for professional tests">?</button><div className={`online ${isHealthy ? "healthy" : ""}`}><i /> {isHealthy ? "Live services" : "Service check"}</div></div></header>}
      {page === "Accueil" && <AppleHome go={go} />}
      {page === "Cartographie" && <MapView />}
      {page === "Assistant" && <AssistantView go={go} />}
      {page === "Nouvelle analyse" && <AnalysisView go={go} />}
      {page === "Suivi" && <FollowUp go={go} />}
      {page === "Santé" && <HealthView health={health} />}
      {page === "Workspace" && <section className="workspace-route"><div className="page-heading"><div><p className="overline">GOVERNED OPERATIONS</p><h1>Advanced workspace</h1><p>Full evidence, independent review, audit, and human approval controls.</p></div></div><App /></section>}
    </main>
  </div>;
}

function MapView() {
  const [cache, setCache] = useState<CatalogCache | null>(null);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<CatalogNode | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = () => request<CatalogCache>("/api/v1/datahub/catalog/cache").then((snapshot) => {
      setCache(snapshot);
      setSelected((current) => snapshot.graph.nodes.find((node) => node.urn === current?.urn) ?? current ?? snapshot.graph.nodes[0] ?? null);
    }).catch((caught) => setError(caught instanceof Error ? caught.message : "Catalog unavailable"));
    load();
    const timer = window.setInterval(load, 5000);
    return () => window.clearInterval(timer);
  }, []);

  const nodes = useMemo(() => {
    const term = query.trim().toLowerCase();
    return (cache?.graph.nodes ?? []).filter((node) => !term || `${node.label} ${node.entity_type} ${node.platform_urn ?? ""}`.toLowerCase().includes(term));
  }, [cache, query]);
  const visible = new Set(nodes.map((node) => node.urn));
  const edges = useMemo(() => (cache?.graph.edges ?? []).filter((edge) => visible.has(edge.source_urn) && visible.has(edge.target_urn)), [cache, visible]);
  const graphData = useMemo(() => ({ nodes: nodes.map((node) => ({ ...node, id: node.urn })), links: edges.map((edge) => ({ source: edge.source_urn, target: edge.target_urn, label: `${edge.direction} · ${edge.hops} hop(s)` })) }), [nodes, edges]);

  async function refresh() {
    setBusy(true); setError(null);
    try { await request("/api/v1/datahub/catalog/cache/refresh", {}); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Refresh unavailable"); }
    finally { setBusy(false); }
  }

  return <section className="page-content integration-page">
    <div className="page-heading"><div><p className="overline">LIVE DATAHUB CATALOG</p><h1>Cartography</h1><p>Explore live metadata and observed lineage from the shared server cache.</p></div><button className="ghost" onClick={refresh} disabled={busy}>{busy ? "Refreshing…" : "Refresh from DataHub"}</button></div>
    {error && <p className="integration-error">{error}</p>}
    <div className="map-stats"><span><i className="blue-dot" /> {cache?.status.loaded_assets ?? 0} assets</span><span><i className="purple-dot" /> {cache?.status.loaded_edges ?? 0} relationships</span><span><i className="mint-dot" /> {cache?.status.state ?? "CONNECTING"} · {cache?.status.message ?? "Waiting for the server cache"}</span></div>
    <section className="map-layout live-map-layout"><div className="card map-card"><div className="map-toolbar"><label className="live-search">Search the loaded catalog<input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="orders, dashboard, snowflake…" /></label><span>{nodes.length} shown</span></div><div className="live-map-canvas"><Suspense fallback={<p>Loading 3D renderer…</p>}><ForceGraph3D graphData={graphData} width={900} height={540} backgroundColor="#071126" nodeRelSize={5} nodeColor={(node: object) => colorFor((node as CatalogNode).platform_urn ?? (node as CatalogNode).entity_type)} linkColor={() => "#6e9ec5"} linkOpacity={0.65} nodeLabel={(node: object) => nodeTooltip(node as CatalogNode)} linkLabel={(link: object) => (link as { label: string }).label} onNodeClick={(node: object) => setSelected(node as CatalogNode)} /></Suspense></div></div><aside className="card detail-card">{selected ? <><div className="detail-symbol">◈</div><p className="overline">LIVE SELECTION</p><h2>{selected.label}</h2><span className="data-pill">{selected.entity_type}</span><hr /><div className="detail-line"><span>Platform</span><b>{platformName(selected.platform_urn)}</b></div><div className="detail-line"><span>Owners</span><b>{selected.owner_urns.length}</b></div><div className="detail-line"><span>Relationships</span><b>{edges.filter((edge) => edge.source_urn === selected.urn || edge.target_urn === selected.urn).length}</b></div><code className="urn">{selected.urn}</code>{selected.recent_actions.length > 0 && <div className="recent-actions"><b>Recent LineageGuard actions</b>{selected.recent_actions.map((action) => <small key={`${action.timestamp}-${action.action}`}>{action.action}: {action.detail}</small>)}</div>}</> : <p>Select a node to inspect its DataHub metadata.</p>}</aside></section>
  </section>;
}

function AssistantView({ go }: { go: (page: Page) => void }) {
  const [status, setStatus] = useState<RagStatus | null>(null);
  const [message, setMessage] = useState("");
  const [reply, setReply] = useState<ChatReply | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [memoryEnabled, setMemoryEnabled] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const sessionId = useMemo(chatSessionId, []);

  useEffect(() => {
    const load = () => request<RagStatus>("/api/v1/chat/index/status").then(setStatus).catch((caught) => setError(caught instanceof Error ? caught.message : "Index status unavailable"));
    load();
    const timer = window.setInterval(load, status?.state === "RUNNING" ? 2500 : 10000);
    return () => window.clearInterval(timer);
  }, [status?.state]);

  const ready = status?.query_available === true || status?.state === "COMPLETED";
  async function index() { setBusy("index"); setError(null); try { setStatus(await request<RagStatus>("/api/v1/chat/index/ingest", {})); } catch (caught) { setError(caught instanceof Error ? caught.message : "Indexing unavailable"); } finally { setBusy(null); } }
  async function ask(event: FormEvent) { event.preventDefault(); if (!message.trim()) return; setBusy("query"); setError(null); try { setReply(await request<ChatReply>("/api/v1/chat/query", { message: message.trim(), session_id: sessionId, memory_enabled: memoryEnabled })); } catch (caught) { setError(caught instanceof Error ? caught.message : "Question unavailable"); } finally { setBusy(null); } }
  const outcome = reply?.action_proposal.action !== "NONE" ? "ACTION REQUIRED" : reply?.verification?.passed ? "VERIFIED" : reply ? "LIMITED" : null;

  return <section className="page-content assistant-screen integration-page"><div className="page-heading"><div><p className="overline">AGENTIC RAG + DATAHUB MCP</p><h1>Assistant</h1><p>Answers are verified against live DataHub evidence before they are presented as facts.</p></div><div className={`assistant-status ${ready ? "ready" : ""}`}><i /> {ready ? (status?.state === "RUNNING" ? "Chat ready · indexing" : "Index ready") : status?.state ?? "Index unavailable"}</div></div>
    <div className="assistant-board live-assistant"><div className="assistant-intro"><div className="assistant-mark">✦</div><h2>What do you want to understand?</h2><p>{status?.message ?? "Start controlled metadata indexing to enable the assistant."}</p><div className="suggestions"><button onClick={() => setMessage("Tell me about the orders dataset.")}>Tell me about orders</button><button onClick={() => setMessage("Show the downstream lineage of the orders dataset.")}>Show downstream lineage</button><button onClick={() => setMessage("What is the schema of the Snowflake orders dataset?")}>Inspect a schema</button></div><div className="assistant-controls"><button className="ghost" onClick={index} disabled={busy !== null || status?.state === "RUNNING"}>{status?.state === "RUNNING" ? "Indexing…" : "Index DataHub metadata"}</button><label><input type="checkbox" checked={memoryEnabled} onChange={(event) => setMemoryEnabled(event.target.checked)} /> Conversation memory</label></div></div>
      <form className="message-box live-message" onSubmit={ask}><span>✦</span><input value={message} onChange={(event) => setMessage(event.target.value)} disabled={!ready || busy !== null} placeholder={ready ? "Ask a question about DataHub…" : "Index metadata first"} /><button disabled={!ready || busy !== null}>{busy === "query" ? "…" : "↑"}</button></form>
      {error && <p className="integration-error">{error}</p>}
      {reply && <article className="live-answer"><div className="answer-status"><b>{outcome}</b><span>{reply.verification_note}</span></div>{reply.target_resolution && <div className="target-resolution"><b>DataHub target</b><span>{reply.target_resolution.status}: {reply.target_resolution.detail}</span>{reply.target_resolution.targets.map((target) => <code key={target.urn}>{target.label} · {platformName(target.platform_urn)}<small>{target.urn}</small></code>)}</div>}<p>{reply.answer}</p><div className="evidence-tags">{reply.citations.map((citation) => <code key={`${citation.source}-${citation.urn}`}>{citation.label} · {citation.source === "datahub_mcp_live" ? "MCP verified" : "RAG context"}</code>)}</div>{reply.action_proposal.action !== "NONE" && <div className="action-callout"><b>{reply.action_proposal.action}</b><p>{reply.action_proposal.reason}</p>{reply.action_proposal.action === "ANALYZE_IMPACT" && <button className="cta" onClick={() => go("Nouvelle analyse")}>Prepare read-only analysis →</button>}{reply.action_proposal.action === "HITL_WRITEBACK" && <button className="ghost" onClick={() => go("Workspace")}>Open governed workspace →</button>}</div>}<details><summary>Public verification trace</summary>{reply.agent_trace.map((step) => <p key={`${step.id}-${step.detail}`}><b>{step.label}</b> · {step.status} · {step.detail}</p>)}</details></article>}</div>
  </section>;
}

function AnalysisView({ go }: { go: (page: Page) => void }) {
  const [assetUrn, setAssetUrn] = useState("urn:li:dataset:(urn:li:dataPlatform:dbt,b2fd91.order_entry_db.order_entry.orders,PROD)");
  const [changeType, setChangeType] = useState("ADD_COLUMN");
  const [columnName, setColumnName] = useState("lineageguard_demo_note");
  const [reason, setReason] = useState("Controlled LineageGuard analysis.");
  const [execution, setExecution] = useState<WorkflowExecution | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function analyze(event: FormEvent) { event.preventDefault(); setBusy(true); setError(null); try { setExecution(await request<WorkflowExecution>("/api/v1/workflows/analyze", { asset_urn: assetUrn.trim(), change_type: changeType, column_name: columnName.trim() || undefined, reason: reason.trim(), environment: "PRODUCTION", lineage_depth: 2, column_nullable: changeType === "ADD_COLUMN" })); } catch (caught) { setError(caught instanceof Error ? caught.message : "Analysis unavailable"); } finally { setBusy(false); } }
  const impact = execution?.impact_report;
  return <section className="page-content integration-page"><div className="page-heading"><div><p className="overline">READ-ONLY IMPACT ANALYSIS</p><h1>New analysis</h1><p>Describe a change. LineageGuard reads DataHub and prepares a recommendation; it does not modify data.</p></div><span className="safe-badge">✓ No mutation</span></div><div className="analysis-grid"><form className="card form-card" onSubmit={analyze}><div className="step-number">01</div><h2>Your change</h2><label>DataHub asset URN<input value={assetUrn} onChange={(event) => setAssetUrn(event.target.value)} required /></label><label>Change type<select value={changeType} onChange={(event) => setChangeType(event.target.value)}><option value="ADD_COLUMN">Add a column</option><option value="RENAME_COLUMN">Rename a column</option><option value="CHANGE_COLUMN_TYPE">Change a column type</option><option value="DROP_COLUMN">Drop a column</option></select></label><label>Column name<input value={columnName} onChange={(event) => setColumnName(event.target.value)} required /></label><label>Reason<textarea value={reason} onChange={(event) => setReason(event.target.value)} required /></label><button className="cta wide" disabled={busy}>{busy ? "Reading DataHub…" : "Analyze impact →"}</button>{error && <p className="integration-error">{error}</p>}</form><aside className="analysis-side">{impact ? <section className="demo-result live-impact"><span>{impact.risk_assessment.level} · {impact.risk_assessment.score}/100</span><h3>{impact.blast_radius} assets may be affected</h3><p>{impact.evidence_bundle.items.length} DataHub evidence records support this read-only report.</p><ul>{impact.impacted_assets.slice(0, 4).map((item) => <li key={item.asset_urn}>{item.criticality} · {shortUrn(item.asset_urn)}</li>)}</ul><button className="ghost" onClick={() => go("Workspace")}>Open full review and HITL workflow →</button></section> : <section className="card guide-card"><div className="guide-icon">✦</div><h2>Simple and governed</h2><p>The system evaluates evidence and proposes steps. It never deploys a schema change.</p><div><span>1</span> Describe the change</div><div><span>2</span> Review the impact</div><div><span>3</span> Decide with evidence</div></section>}</aside></div>
  </section>;
}

function FollowUp({ go }: { go: (page: Page) => void }) {
  const [history, setHistory] = useState<RunSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { request<RunSummary[]>("/api/v1/judges/history").then(setHistory).catch((caught) => setError(caught instanceof Error ? caught.message : "History unavailable")); }, []);
  return <section className="page-content integration-page"><div className="page-heading"><div><p className="overline">AUDITABLE FOLLOW-UP</p><h1>Analysis follow-up</h1><p>Review persisted independent-judging outcomes. Detailed proposal and audit controls stay in the governed workspace.</p></div><button className="ghost" onClick={() => go("Workspace")}>Open workspace</button></div><section className="card follow-table"><div className="table-head"><h2>Recent governed reviews</h2><span>{history.length} run(s)</span></div>{error && <p className="integration-error">{error}</p>}{history.length === 0 && !error && <p className="empty-state">No judging run has been recorded yet. Run an impact analysis, then independent judges, from the advanced workspace.</p>}{history.map((item) => <div className="table-row" key={item.run_id}><div className="row-symbol">◌</div><div><b>{item.decision ?? "GATE 0"}</b><span>{item.run_id}</span></div><span className={`status ${item.decision === "FINALIZE_READ_ONLY" ? "done" : "pending"}`}>{item.openai_status ?? "—"} / {item.groq_status ?? "—"}</span><button onClick={() => go("Workspace")}>→</button></div>)}</section></section>;
}

function HealthView({ health }: { health: Health | null }) {
  const items = health ? [["API", health.status], ["DataHub", health.datahub], ["Qdrant", health.qdrant], ["LLM providers", health.llm_providers]] : [["API", "checking"], ["DataHub", "checking"], ["Qdrant", "checking"], ["LLM providers", "checking"]];
  return <section className="page-content health-screen integration-page"><div className="page-heading"><div><p className="overline">LIVE TECHNICAL STATUS</p><h1>Platform health</h1><p>This screen reads the LineageGuard health endpoint; it never displays provider secrets.</p></div><div className={`assistant-status ${health?.status === "ok" ? "ready" : ""}`}><i /> {health?.status === "ok" ? "Operational" : "Checking"}</div></div><section className="health-hero"><div><span className="health-check">{health?.status === "ok" ? "✓" : "…"}</span><h2>{health?.status === "ok" ? "Core services are available" : "Checking service health"}</h2><p>Health reports configuration and connectivity state. It does not claim that optional external providers completed a recent request.</p></div><small>Environment: {health?.environment ?? "unknown"}</small></section><div className="health-grid">{items.map(([name, value]) => <HealthCard key={name} name={name} status={value} />)}</div></section>;
}

function HealthCard({ name, status }: { name: string; status: string }) { const reachable = status === "ok"; const configured = status === "configured"; return <article className="health-card"><i>{reachable || configured ? "✓" : "!"}</i><div><b>{name}</b><span>{reachable ? "Reachable" : configured ? "Configured — validate live reads in Cartography" : "Requires attention or is checking"}</span></div><small><em className={reachable || configured ? "ok" : "warn"} />{status}</small></article>; }
function icon(page: Page) { return ({ Accueil: "⌂", Cartographie: "◌", Assistant: "✦", "Nouvelle analyse": "＋", Suivi: "◷", Santé: "✓", Workspace: "▣" })[page]; }
function platformName(platform?: string | null) { return (platform ?? "unknown").replace("urn:li:dataPlatform:", ""); }
function shortUrn(urn: string) { return urn.length > 52 ? `${urn.slice(0, 23)}…${urn.slice(-25)}` : urn; }
function colorFor(value: string) { const colors = ["#67e8f9", "#c4b5fd", "#86efac", "#fcd34d", "#f9a8d4", "#93c5fd"]; let hash = 0; for (let i = 0; i < value.length; i += 1) hash = (hash * 31 + value.charCodeAt(i)) | 0; return colors[Math.abs(hash) % colors.length]; }
function nodeTooltip(node: CatalogNode) { return `<div><b>${escapeHtml(node.label)}</b><br/>${escapeHtml(node.entity_type)}<br/>${escapeHtml(platformName(node.platform_urn))}<br/><small>${escapeHtml(node.urn)}</small></div>`; }
function escapeHtml(value: string) { return value.replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character] ?? character); }
