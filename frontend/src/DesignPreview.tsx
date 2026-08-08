import { FormEvent, Suspense, lazy, useEffect, useMemo, useRef, useState } from "react";
import AppleHome from "./AppleHome";
import GovernedReview from "./GovernedReview";
import type { FieldData } from "./lineage-field";
import "./design-preview.css";
import "./preview-reset.css";
import "./design-v2.css";
import "./motion-typography.css";
import "./motion-fixes.css";
import "./navigation-motion.css";
import "./integration.css";
// The premium dark theme overrides every sheet above; keep it last.
import "./premium.css";
import {
  buildChangeRequest,
  createChatHandoff,
  draftFromRequest,
  isHandoffUsable,
  requestFingerprint,
  validateDraft,
  type AnalysisDraft,
  type ChangeRequestPayload,
  type ChangeType,
  type ChatAnalysisHandoff,
  type VerifiedTarget,
} from "./analysisFlow";
import {
  catalogTopologySignature,
  clearAnalysisRun,
  loadAnalysisRun,
  recoverCatalogGraph,
  saveAnalysisRun,
  stabilizeCatalogGraphData,
  type StableCatalogGraphData,
} from "./recovery";
import { platformCss, platformKey } from "./platformPalette";
import type { RuntimeHealth } from "./runtimeHealth";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
// Three.js stays in its own chunk so the shell still paints without it.
const LineageField = lazy(() => import("./LineageField"));

type Page = "Accueil" | "Cartographie" | "Assistant" | "Nouvelle analyse" | "Suivi" | "Santé" | "Review";
type CatalogNode = { urn: string; label: string; entity_type: string; platform_urn?: string | null; owner_urns: string[]; recent_actions: Array<{ timestamp: string; action: string; detail: string }> };
type CatalogEdge = { source_urn: string; target_urn: string; direction: string; hops: number };
type CatalogCache = { status: { state: string; loaded_assets: number; loaded_edges: number; message: string; last_updated_at?: string | null; last_checked_at?: string | null; refresh_reason?: string | null; refresh_in_progress: boolean; consecutive_failures: number; last_error?: string | null; detected_change?: string | null; generation: number }; graph: { nodes: CatalogNode[]; edges: CatalogEdge[]; truncated: boolean } };
type RagStatus = { state: string; indexed_assets: number; total_assets: number; message: string; query_available: boolean };
type ChatReply = { answer: string; verification_note: string; citations: Array<{ urn: string; label: string; entity_type: string; platform_urn?: string | null; source: string }>; target_resolution?: { status: "NOT_REQUIRED" | "RESOLVED" | "AMBIGUOUS" | "NOT_FOUND"; detail: string; targets: Array<{ urn: string; label: string; entity_type: string; platform_urn?: string | null }> } | null; verification?: { passed: boolean; factual_claim_count: number; supported_claim_count: number; claim_coverage: number } | null; action_proposal: { action: "NONE" | "ANALYZE_IMPACT" | "HITL_WRITEBACK"; reason: string }; analysis_handoff_id?: string | null; analysis_handoff_expires_at?: string | null; evidence?: Array<{ id: string; kind: string; asset_urn: string; summary: string; facts: string[] }>; agent_trace: Array<{ id: string; label: string; status: string; detail: string }> };
type ChatTurn = { id: string; question: string; reply: ChatReply };
type WorkflowExecution = { analysis_run_id: string; impact_report: { request: ChangeRequestPayload; blast_radius: number; confidence: number; risk_assessment: { level: string; score: number }; impacted_assets: Array<{ asset_urn: string; criticality: string }>; evidence_bundle: { items: unknown[] } }; remediation_plan: { migration_steps: Array<{ order: number; action: string; rationale: string }> } };
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

const navigationPages: Page[] = ["Accueil", "Cartographie", "Assistant", "Nouvelle analyse", "Suivi", "Santé"];
const allPages: Page[] = [...navigationPages, "Review"];
const pageSlugs: Record<Page, string> = { Accueil: "", Cartographie: "cartographie", Assistant: "assistant", "Nouvelle analyse": "analyse", Suivi: "suivi", Santé: "sante", Review: "review" };
function pageFromHash(): Page { const slug = window.location.hash.replace(/^#\/?/, ""); return allPages.find((page) => pageSlugs[page] === slug) ?? "Accueil"; }

export default function DesignPreview() {
  const [page, setPage] = useState<Page>(pageFromHash);
  const [loading, setLoading] = useState(true);
  const [health, setHealth] = useState<RuntimeHealth | null>(null);
  const [analysisHandoff, setAnalysisHandoff] = useState<ChatAnalysisHandoff | null>(null);
  const [catalogTarget, setCatalogTarget] = useState<VerifiedTarget | null>(null);
  const [revision, setRevision] = useState<{ request: ChangeRequestPayload; comment: string } | null>(null);

  useEffect(() => {
    const load = () => request<RuntimeHealth>("/api/v1/health").then(setHealth).catch(() => setHealth(null));
    load();
    const timer = window.setInterval(load, 15000);
    const initial = window.setTimeout(() => setLoading(false), 650);
    return () => { window.clearInterval(timer); window.clearTimeout(initial); };
  }, []);

  useEffect(() => { const sync = () => setPage(pageFromHash()); window.addEventListener("hashchange", sync); return () => window.removeEventListener("hashchange", sync); }, []);

  function go(next: Page) { setPage(next); const hash = pageSlugs[next]; window.location.hash = hash ? `/${hash}` : ""; window.scrollTo({ top: 0, behavior: "smooth" }); }
  const isHealthy = health?.status === "ok";

  return <div className="preview-app">
    {loading && <div className="preview-loader"><div className="loader-logo"><img src="/lineageguard-logo.png" alt="" /></div><b>LineageGuard</b><span>Preparing your governed workspace</span><i /></div>}
    <header className="site-nav">
      <button className="preview-brand" onClick={() => go("Accueil")}><img src="/lineageguard-logo.png" alt="" /><b>LineageGuard</b></button>
      <nav>{navigationPages.map((item) => <button key={item} onClick={() => go(item)} className={page === item ? "selected" : ""}><span>{icon(item)}</span>{pageLabel(item)}</button>)}</nav>
      <div className={`nav-health ${isHealthy ? "healthy" : "unavailable"}`}><i /> {isHealthy ? "Platform operational" : "Checking platform"}</div>
    </header>
    <main className="preview-main">
      {page === "Accueil" && <AppleHome go={go} />}
      {page === "Cartographie" && <MapView onAnalyzeSelected={(target) => { setCatalogTarget(target); setAnalysisHandoff(null); go("Nouvelle analyse"); }} />}
      {page === "Assistant" && <AssistantView go={go} onAnalysisHandoff={(handoff) => { setAnalysisHandoff(handoff); setCatalogTarget(null); go("Nouvelle analyse"); }} />}
      {page === "Nouvelle analyse" && <AnalysisView go={go} handoff={analysisHandoff} catalogTarget={catalogTarget} revision={revision} onClearHandoff={() => setAnalysisHandoff(null)} onClearCatalogTarget={() => setCatalogTarget(null)} onClearRevision={() => setRevision(null)} />}
      {page === "Suivi" && <FollowUp go={go} />}
      {page === "Santé" && <HealthView health={health} />}
      {page === "Review" && <GovernedReview health={health} onBack={() => go("Nouvelle analyse")} onRevision={(request, comment) => { setRevision({ request, comment }); go("Nouvelle analyse"); }} />}
    </main>
    <footer className="site-footer">
      <span>LineageGuard AI · Apache-2.0 · read-only by default</span>
      <span>DataHub OSS + official MCP server · LangGraph · Qdrant</span>
    </footer>
  </div>;
}

function MapView({ onAnalyzeSelected }: { onAnalyzeSelected: (target: VerifiedTarget) => void }) {
  const [cache, setCache] = useState<CatalogCache | null>(null);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<CatalogNode | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const stableGraph = useRef<StableCatalogGraphData<CatalogNode, CatalogEdge> | null>(null);
  const stableField = useRef<{ signature: string; data: FieldData } | null>(null);

  useEffect(() => {
    const load = () => request<CatalogCache>("/api/v1/datahub/catalog/cache").then((snapshot) => {
      setCache((current) => {
        const graph = recoverCatalogGraph(current?.graph ?? null, snapshot.graph) as CatalogCache["graph"];
        // Keep an existing selection alive across polls, but never auto-select:
        // the aside states plainly that nothing is selected until a node is clicked.
        setSelected((selectedNode) => (selectedNode ? graph.nodes.find((node) => node.urn === selectedNode.urn) ?? selectedNode : null));
        return {
          ...snapshot,
          status: {
            ...snapshot.status,
            loaded_assets: graph.nodes.length,
            loaded_edges: graph.edges.length,
          },
          graph,
        };
      });
    }).catch((caught) => setError(caught instanceof Error ? caught.message : "Catalog unavailable"));
    load();
    const timer = window.setInterval(load, 5000);
    return () => window.clearInterval(timer);
  }, []);

  const nodes = useMemo(() => {
    const terms = query.toLowerCase().split(/[\s,]+/).filter(Boolean);
    return (cache?.graph.nodes ?? []).filter((node) => {
      if (terms.length === 0) return true;
      const searchable = `${node.label} ${node.entity_type} ${node.platform_urn ?? ""}`.toLowerCase();
      return terms.every((term) => searchable.includes(term));
    });
  }, [cache, query]);
  const visible = useMemo(() => new Set(nodes.map((node) => node.urn)), [nodes]);
  const edges = useMemo(() => (cache?.graph.edges ?? []).filter((edge) => visible.has(edge.source_urn) && visible.has(edge.target_urn)), [cache, visible]);
  const graphData = useMemo(() => {
    const stabilized = stabilizeCatalogGraphData(stableGraph.current, nodes, edges);
    stableGraph.current = stabilized;
    return stabilized.data;
  }, [nodes, edges]);
  // The lineage field receives the complete cached graph and dims non-matching
  // nodes itself, so text search never rebuilds the constellation. The payload
  // keeps its identity while the topology is unchanged, so a five-second poll
  // cannot re-run the field's layout pass.
  const fieldData = useMemo<FieldData>(() => {
    const cachedNodes = cache?.graph.nodes ?? [];
    const cachedEdges = cache?.graph.edges ?? [];
    const signature = catalogTopologySignature(cachedNodes, cachedEdges);
    if (stableField.current?.signature === signature) return stableField.current.data;
    const next: FieldData = {
      nodes: cachedNodes.map((node) => ({
        urn: node.urn,
        label: node.label,
        platform: node.platform_urn ?? undefined,
        entityType: node.entity_type,
        owners: node.owner_urns.length,
      })),
      edges: cachedEdges.map((edge) => ({ source: edge.source_urn, target: edge.target_urn })),
    };
    stableField.current = { signature, data: next };
    return next;
  }, [cache?.graph]);
  // Legend entries are the platforms actually present, coloured by the exact
  // mapping the renderer uses for its nodes.
  const legend = useMemo(() => {
    const counts = new Map<string, number>();
    for (const node of cache?.graph.nodes ?? []) {
      const key = platformKey(node.platform_urn);
      if (key !== "unknown") counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return [...counts.entries()]
      .sort((left, right) => right[1] - left[1])
      .slice(0, 6)
      .map(([key]) => ({ key, color: platformCss(key) }));
  }, [cache?.graph]);

  async function refresh() {
    setBusy(true); setError(null);
    try {
      const refreshStatus = await request<CatalogCache["status"]>("/api/v1/datahub/catalog/cache/refresh", {});
      setCache((current) => current ? {
        ...current,
        status: {
          ...refreshStatus,
          loaded_assets: current.graph.nodes.length,
          loaded_edges: current.graph.edges.length,
        },
      } : current);
    }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Refresh unavailable"); }
    finally { setBusy(false); }
  }

  const relationships = selected
    ? edges.filter((edge) => edge.source_urn === selected.urn || edge.target_urn === selected.urn).length
    : null;
  const analysisTarget = selected
    ? compatibleAnalysisTarget(selected, cache?.graph.nodes ?? [])
    : null;
  const clock = (value?: string | null) => (value ? new Date(value).toLocaleTimeString() : "pending");

  return <section className="page-content map-page integration-page">
    <div className="page-heading">
      <div>
        <p className="overline">LIVE DATAHUB CATALOG</p>
        <h1>Cartography</h1>
        <p>Explore live metadata and observed lineage from the shared server cache. The overview keeps all assets visible while selected lineage is highlighted.</p>
      </div>
      <button className="ghost" onClick={refresh} disabled={busy}>{busy ? "Refreshing…" : "Refresh from DataHub"}</button>
    </div>
    {error && <p className="integration-error">{error}</p>}
    <div className="map-stats" data-testid="catalog-cache-status">
      <span><i className="blue-dot" /> {cache?.status.loaded_assets ?? 0} assets</span>
      <span><i className="purple-dot" /> {cache?.status.loaded_edges ?? 0} relationships</span>
      <span className="stat-live" data-testid="catalog-cache-state"><i className="mint-dot" /> {cache?.status.refresh_in_progress ? "REFRESHING" : cache?.status.state ?? "CONNECTING"} · {cache?.status.message ?? "Waiting for the server cache"}</span>
    </div>
    <section className="map-layout live-map-layout" data-testid="catalog-graph" data-node-count={nodes.length} data-edge-count={edges.length}>
      <div className="card map-card">
        <div className="map-toolbar">
          <input aria-label="Search the loaded catalog" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="orders, dashboard, snowflake…" />
          <div className="platform-legend">{legend.map((item) => <span key={item.key}><i style={{ background: item.color }} /> {item.key}</span>)}</div>
        </div>
        <div className="live-map-canvas">
          <Suspense fallback={<p>Loading 3D renderer…</p>}><LineageField mode="interactive" data={fieldData} query={query} selectedUrn={selected?.urn ?? null} onSelect={(node) => setSelected(node ? (cache?.graph.nodes ?? []).find((item) => item.urn === node.urn) ?? null : null)} /></Suspense>
        </div>
        <div className="map-footbar">
          <span>{nodes.length} shown · generation {cache?.status.generation ?? 0} · last refresh {clock(cache?.status.last_updated_at)} · last change check {clock(cache?.status.last_checked_at)}{cache?.status.detected_change ? ` · detected ${cache.status.detected_change}` : ""}{cache?.status.last_error ? ` · ${cache.status.last_error}` : ""}</span>
          <span>drag · scroll · click</span>
        </div>
      </div>
      <aside className="card detail-card">
        <p className="overline">LIVE SELECTION</p>
        <h2>{selected ? selected.label : "Nothing selected"}</h2>
        <span className="data-pill">{selected ? selected.entity_type : "NO SELECTION"}</span>
        <hr />
        <div className="detail-line"><span>Platform</span><b>{selected ? platformName(selected.platform_urn) : "—"}</b></div>
        <div className="detail-line"><span>Owners</span><b>{selected ? selected.owner_urns.length : "—"}</b></div>
        <div className="detail-line"><span>Relationships</span><b>{relationships ?? "—"}</b></div>
        <code className="urn">{selected ? selected.urn : "Click a node in the graph to inspect its DataHub metadata."}</code>
        {analysisTarget && <button className="cta wide analyze-selected" onClick={() => onAnalyzeSelected(analysisTarget)}>{selected?.entity_type.toUpperCase() === "SCHEMAFIELD" ? "Analyze parent dataset →" : "Analyze this dataset →"}</button>}
        {selected && !analysisTarget && <small className="analysis-target-hint">Impact analysis is available for datasets and their schema fields.</small>}
        {selected && selected.recent_actions.length > 0 && <div className="recent-actions"><b>Recent LineageGuard actions</b>{selected.recent_actions.map((action) => <small key={`${action.timestamp}-${action.action}`}>{action.action}: {action.detail}</small>)}</div>}
      </aside>
    </section>
  </section>;
}

function compatibleAnalysisTarget(selected: CatalogNode, catalog: CatalogNode[]): VerifiedTarget | null {
  if (selected.entity_type.toUpperCase() === "DATASET") {
    return { urn: selected.urn, label: selected.label, entity_type: selected.entity_type, platform_urn: selected.platform_urn };
  }
  if (selected.entity_type.toUpperCase() !== "SCHEMAFIELD") return null;
  const parentUrn = schemaFieldParentDatasetUrn(selected.urn);
  if (!parentUrn) return null;
  const parent = catalog.find((node) => node.urn === parentUrn);
  return parent
    ? { urn: parent.urn, label: parent.label, entity_type: parent.entity_type, platform_urn: parent.platform_urn }
    : { urn: parentUrn, label: "Parent dataset", entity_type: "DATASET", platform_urn: selected.platform_urn };
}

/** Extract the dataset portion of a DataHub schema-field URN without guessing a name. */
function schemaFieldParentDatasetUrn(urn: string): string | null {
  const prefix = "urn:li:schemaField:(urn:li:dataset:(";
  if (!urn.startsWith(prefix) || !urn.endsWith(")")) return null;
  const datasetOpen = prefix.length - 1;
  let depth = 0;
  for (let index = datasetOpen; index < urn.length; index += 1) {
    if (urn[index] === "(") depth += 1;
    if (urn[index] === ")") depth -= 1;
    if (depth === 0) return urn.slice("urn:li:schemaField:(".length, index + 1);
  }
  return null;
}

function AssistantView({ go, onAnalysisHandoff }: { go: (page: Page) => void; onAnalysisHandoff: (handoff: ChatAnalysisHandoff) => void }) {
  const [status, setStatus] = useState<RagStatus | null>(null);
  const [message, setMessage] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [memoryEnabled, setMemoryEnabled] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const sessionId = useMemo(chatSessionId, []);
  const chatViewport = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const load = () => request<RagStatus>("/api/v1/chat/index/status").then(setStatus).catch((caught) => setError(caught instanceof Error ? caught.message : "Index status unavailable"));
    load();
    const timer = window.setInterval(load, status?.state === "RUNNING" ? 2500 : 10000);
    return () => window.clearInterval(timer);
  }, [status?.state]);

  const ready = status?.query_available === true || status?.state === "COMPLETED";
  useEffect(() => {
    const viewport = chatViewport.current;
    if (!viewport) return;
    window.requestAnimationFrame(() => viewport.scrollTo({ top: viewport.scrollHeight, behavior: "smooth" }));
  }, [turns.length, busy]);
  async function index() { setBusy("index"); setError(null); try { setStatus(await request<RagStatus>("/api/v1/chat/index/ingest", {})); } catch (caught) { setError(caught instanceof Error ? caught.message : "Indexing unavailable"); } finally { setBusy(null); } }
  async function askQuestion(question: string) {
    if (!question) return;
    setBusy("query"); setError(null);
    try {
      const reply = await request<ChatReply>("/api/v1/chat/query", { message: question, session_id: sessionId, memory_enabled: memoryEnabled });
      setTurns((current) => [...current, { id: crypto.randomUUID(), question, reply }].slice(-6));
      setMessage("");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Question unavailable"); } finally { setBusy(null); }
  }
  async function ask(event: FormEvent) {
    event.preventDefault();
    await askQuestion(message.trim());
  }
  return <section className="page-content assistant-screen integration-page">
    <div className="page-heading">
      <div>
        <p className="overline">AGENTIC RAG + DATAHUB MCP</p>
        <h1>Assistant</h1>
        <p>Answers are verified against live DataHub evidence before they are presented as facts.</p>
      </div>
      <div className={`assistant-status ${ready ? "ready" : ""}`}><i /> {ready ? (status?.state === "RUNNING" ? "CHAT READY · INDEXING" : "INDEX READY") : status?.state ?? "INDEX UNAVAILABLE"}</div>
    </div>
    <div className="assistant-board live-assistant">
      <div className="assistant-intro assistant-intro-compact">
        <div className="assistant-mark">✦</div>
        <h2>What do you want to understand?</h2>
        <p>{status?.message ?? "Start controlled metadata indexing to enable the assistant."}</p>
        <div className="suggestions">
          <button onClick={() => setMessage("Tell me about the orders dataset.")}>Tell me about orders</button>
          <button onClick={() => setMessage("Show the downstream lineage of the orders dataset.")}>Show downstream lineage</button>
          <button onClick={() => setMessage("What is the schema of the Snowflake orders dataset?")}>Inspect a schema</button>
        </div>
      </div>
      <section className="chat-shell" aria-label="DataHub conversation">
        <div className="chat-viewport" ref={chatViewport}>
          {error && <p className="integration-error">{error}</p>}
          {turns.length === 0 && <div className="chat-empty"><b>Start with a question</b><span>Choose an example above or ask about a table, dashboard, owner, schema, or lineage.</span></div>}
          {turns.length > 0 && <section className="conversation-history" aria-live="polite">{turns.map((turn) => <div className="conversation-turn" key={turn.id}>
            <div className="user-message"><span>You</span><p>{turn.question}</p></div>
            <AssistantResponse reply={turn.reply} go={go} onAnalysisHandoff={onAnalysisHandoff} onChooseTarget={(target) => {
              // Preserve the original intent (schema, lineage, or impact),
              // then add the user's explicit platform selection. The click
              // immediately re-runs the same request rather than leaving a
              // generic, misleading draft in the composer.
              void askQuestion(`${turn.question}\nUse the ${displayPlatform(target)} asset named ${target.label}.`);
            }} />
          </div>)}</section>}
        </div>
        <div className="chat-composer">
          <form className="message-box live-message" onSubmit={ask}>
            <span>✦</span>
            <input value={message} onChange={(event) => setMessage(event.target.value)} disabled={!ready || busy !== null} placeholder={ready ? "Ask a question about DataHub…" : "Index metadata first"} />
            <button disabled={!ready || busy !== null}>{busy === "query" ? "…" : "↑"}</button>
          </form>
          <div className="assistant-controls">
            <button className="ghost" onClick={index} disabled={busy !== null || status?.state === "RUNNING"}>{status?.state === "RUNNING" ? "Indexing…" : "Index DataHub metadata"}</button>
            <label><input type="checkbox" checked={memoryEnabled} onChange={(event) => setMemoryEnabled(event.target.checked)} /> Conversation memory</label>
          </div>
        </div>
      </section>
    </div>
  </section>;
}

function AssistantResponse({ reply, go, onAnalysisHandoff, onChooseTarget }: {
  reply: ChatReply;
  go: (page: Page) => void;
  onAnalysisHandoff: (handoff: ChatAnalysisHandoff) => void;
  onChooseTarget: (target: NonNullable<ChatReply["target_resolution"]>["targets"][number]) => void;
}) {
  const verification = reply.verification;
  const resolved = reply.target_resolution;
  const outcome = reply.action_proposal.action !== "NONE" ? "ACTION REQUIRED" : verification?.passed ? "VERIFIED" : "LIMITED";
  const handoff = createChatHandoff({
    action: reply.action_proposal.action,
    resolution: reply.target_resolution,
    handoffId: reply.analysis_handoff_id,
    expiresAt: reply.analysis_handoff_expires_at,
  });
  return <article className={`live-answer ${verification?.passed ? "verified" : ""}`}>
        <div className="answer-status">
          <b>{outcome}</b>
          {verification && <span>{verification.factual_claim_count} claims · {verification.supported_claim_count} supported · {Math.round(verification.claim_coverage * 100)}% coverage</span>}
        </div>
        <p>{reply.answer}</p>
        {resolved && resolved.status !== "NOT_REQUIRED" && <div className="target-resolution">
          <p className="overline">DATAHUB TARGET · {resolved.status === "RESOLVED" ? "CONFIRMED" : "YOUR CHOICE IS NEEDED"}</p>
          <p>{resolved.status === "AMBIGUOUS" ? "We found several matching data assets. Choose the source you mean before we inspect its schema or lineage." : "This is the exact DataHub asset used to verify the answer."}</p>
          <div className="target-choice-list">
            {resolved.targets.map((target) => <button type="button" key={target.urn} onClick={() => onChooseTarget(target)}>
              <b>{target.label}</b><span>{displayPlatform(target)} · {target.entity_type.toLowerCase()}</span>
            </button>)}
          </div>
          <details className="target-technical"><summary>Technical identifier</summary>{resolved.targets.map((target) => <code key={target.urn}>{target.urn}</code>)}</details>
        </div>}
        {(reply.evidence ?? []).length > 0 && <div className="evidence-grid">
          {(reply.evidence ?? []).map((item) => <div key={item.id}>
            <span>{item.id} · {evidenceTool(item.kind)}</span>
            <p>{friendlyEvidenceSummary(item)}</p>
          </div>)}
        </div>}
        <div className="evidence-tags">{reply.citations.map((citation) => <code key={`${citation.source}-${citation.urn}`}>{citation.label} · {citation.source === "datahub_mcp_live" ? "MCP verified" : "RAG context"}</code>)}</div>
        <details><summary>How this answer was checked</summary><ul>{reply.agent_trace.map((step) => <li key={`${step.id}-${step.detail}`}>{step.label} · {step.status} · {step.detail}</li>)}</ul></details>
        {reply.action_proposal.action !== "NONE" && <div className="action-callout">
          <b>{reply.action_proposal.action}</b>
          <p>{reply.action_proposal.reason}</p>
          {reply.action_proposal.action === "ANALYZE_IMPACT" && <><button className="cta" onClick={() => handoff && onAnalysisHandoff(handoff)} disabled={!isHandoffUsable(handoff)}>Analyze impact on this target →</button>{!handoff && <small>A live, unambiguous DataHub target is required before analysis.</small>}</>}
          {reply.action_proposal.action === "HITL_WRITEBACK" && <button className="ghost" onClick={() => go("Review")}>Open governed review →</button>}
        </div>}
        <span className="verification-note">{reply.verification_note}</span>
      </article>;
}

function evidenceTool(kind: string) {
  return kind === "schema" ? "list_schema_fields" : kind === "lineage" ? "get_lineage" : "search";
}

function displayPlatform(target: { urn: string; platform_urn?: string | null }) {
  const raw = target.platform_urn?.split(":").at(-1) ?? target.urn.match(/dataPlatform:([^,\)]+)/)?.[1] ?? "DataHub";
  return raw.replaceAll("_", " ");
}

function friendlyEvidenceSummary(item: NonNullable<ChatReply["evidence"]>[number]) {
  if (item.kind === "schema") {
    const fields = item.facts.filter((fact) => fact.startsWith("column=")).slice(0, 3).map((fact) => fact.replace(/^column=/, "").replace(", type=", " · "));
    return fields.length ? `Fields checked: ${fields.join(" · ")}.` : "The schema was checked directly in DataHub.";
  }
  if (item.kind === "lineage") return item.summary || "The connected downstream assets were read directly from DataHub.";
  const asset = item.facts.find((fact) => fact.startsWith("asset="))?.replace("asset=", "") ?? "Matching data asset";
  const platform = item.facts.find((fact) => fact.startsWith("platform="))?.replace("platform=", "");
  return `${asset}${platform ? ` · ${platform}` : ""} was confirmed in DataHub.`;
}

function AnalysisView({ go, handoff, catalogTarget, revision, onClearHandoff, onClearCatalogTarget, onClearRevision }: {
  go: (page: Page) => void;
  handoff: ChatAnalysisHandoff | null;
  catalogTarget: VerifiedTarget | null;
  revision: { request: ChangeRequestPayload; comment: string } | null;
  onClearHandoff: () => void;
  onClearCatalogTarget: () => void;
  onClearRevision: () => void;
}) {
  const [assetUrn, setAssetUrn] = useState("urn:li:dataset:(urn:li:dataPlatform:dbt,b2fd91.order_entry_db.order_entry.orders,PROD)");
  const [changeType, setChangeType] = useState<ChangeType>("ADD_COLUMN");
  const [columnName, setColumnName] = useState("lineageguard_demo_note");
  const [newValue, setNewValue] = useState("");
  const [columnNullable, setColumnNullable] = useState(true);
  const [typeChangeCompatible, setTypeChangeCompatible] = useState<boolean | null>(null);
  const [reason, setReason] = useState("Controlled LineageGuard analysis.");
  const [depth, setDepth] = useState(2);
  const [execution, setExecution] = useState<WorkflowExecution | null>(null);
  const [submittedFingerprint, setSubmittedFingerprint] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [analysisProgress, setAnalysisProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [restoredFromServer, setRestoredFromServer] = useState(false);
  const restoreAttempted = useRef(false);
  const progressTimer = useRef<number | null>(null);
  const sessionId = useMemo(chatSessionId, []);
  const draft = useMemo<AnalysisDraft>(() => ({
    assetUrn,
    changeType,
    columnName,
    newValue,
    reason,
    depth,
    columnNullable,
    typeChangeCompatible,
  }), [assetUrn, changeType, columnName, newValue, reason, depth, columnNullable, typeChangeCompatible]);
  const errors = useMemo(() => validateDraft(draft), [draft]);
  const payload = errors.length === 0 ? buildChangeRequest(draft) : null;
  const fingerprint = payload ? requestFingerprint(payload) : null;
  const revisionFingerprint = revision ? requestFingerprint(revision.request) : null;

  useEffect(() => {
    if (!handoff) return;
    if (!isHandoffUsable(handoff)) {
      onClearHandoff();
      setError("The verified chat target expired. Resolve the asset again in the assistant.");
      return;
    }
    setAssetUrn(handoff.target.urn);
    setExecution(null);
    setSubmittedFingerprint(null);
    setRestoredFromServer(false);
    clearAnalysisRun(window.sessionStorage);
  }, [handoff]);

  useEffect(() => {
    if (!catalogTarget || handoff) return;
    setAssetUrn(catalogTarget.urn);
    setExecution(null);
    setSubmittedFingerprint(null);
    setRestoredFromServer(false);
    clearAnalysisRun(window.sessionStorage);
  }, [catalogTarget, handoff]);

  useEffect(() => () => {
    if (progressTimer.current !== null) window.clearInterval(progressTimer.current);
  }, []);

  useEffect(() => {
    if (!revision) return;
    const restored = draftFromRequest(revision.request);
    setAssetUrn(restored.assetUrn);
    setChangeType(restored.changeType);
    setColumnName(restored.columnName);
    setNewValue(restored.newValue);
    setReason(restored.reason);
    setDepth(restored.depth);
    setColumnNullable(restored.columnNullable);
    setTypeChangeCompatible(restored.typeChangeCompatible);
    setExecution(null);
    setSubmittedFingerprint(null);
    setRestoredFromServer(false);
    clearAnalysisRun(window.sessionStorage);
  }, [revision]);

  useEffect(() => {
    if (restoreAttempted.current) return;
    restoreAttempted.current = true;
    if (handoff) return;
    const storedRunId = loadAnalysisRun(window.sessionStorage);
    if (!storedRunId) return;
    request<WorkflowExecution>(`/api/v1/workflows/analysis/${storedRunId}`)
      .then((restoredExecution) => {
        const restored = draftFromRequest(restoredExecution.impact_report.request);
        setAssetUrn(restored.assetUrn);
        setChangeType(restored.changeType);
        setColumnName(restored.columnName);
        setNewValue(restored.newValue);
        setReason(restored.reason);
        setDepth(restored.depth);
        setColumnNullable(restored.columnNullable);
        setTypeChangeCompatible(restored.typeChangeCompatible);
        setExecution(restoredExecution);
        setSubmittedFingerprint(requestFingerprint(buildChangeRequest(restored)));
        setRestoredFromServer(true);
      })
      .catch(() => {
        clearAnalysisRun(window.sessionStorage);
        setExecution(null);
        setSubmittedFingerprint(null);
        setRestoredFromServer(false);
        setError("The saved analysis no longer exists on the server; no stale report was restored.");
      });
  }, []);

  useEffect(() => {
    if (submittedFingerprint !== null && fingerprint !== submittedFingerprint) {
      setExecution(null);
      setSubmittedFingerprint(null);
      setRestoredFromServer(false);
      clearAnalysisRun(window.sessionStorage);
    }
  }, [fingerprint, submittedFingerprint]);

  async function analyze(event: FormEvent) {
    event.preventDefault();
    if (!payload) {
      setError(errors[0] ?? "Complete the change request.");
      return;
    }
    if (handoff && (!isHandoffUsable(handoff) || handoff.target.urn !== payload.asset_urn)) {
      onClearHandoff();
      setError("The verified target is missing, expired, or does not match this request.");
      return;
    }
    setBusy(true);
    setAnalysisProgress(12);
    progressTimer.current = window.setInterval(() => {
      setAnalysisProgress((current) => Math.min(current + 9, 90));
    }, 650);
    setError(null);
    try {
      const result = handoff
        ? await request<WorkflowExecution>("/api/v1/chat/execute-analysis", {
          change_request: payload,
          confirmed: true,
          handoff_id: handoff.handoffId,
          session_id: sessionId,
        })
        : await request<WorkflowExecution>("/api/v1/workflows/analyze", payload);
      setExecution(result);
      setSubmittedFingerprint(requestFingerprint(payload));
      setRestoredFromServer(false);
      saveAnalysisRun(window.sessionStorage, result.analysis_run_id);
      if (handoff) onClearHandoff();
      if (catalogTarget) onClearCatalogTarget();
      if (revision) onClearRevision();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Analysis unavailable");
    } finally {
      if (progressTimer.current !== null) window.clearInterval(progressTimer.current);
      progressTimer.current = null;
      setAnalysisProgress(100);
      setBusy(false);
    }
  }

  const impact = execution?.impact_report;
  const needsNewValue = changeType === "RENAME_COLUMN" || changeType === "CHANGE_COLUMN_TYPE";
  return <section className="page-content integration-page">
    <div className="page-heading"><div><p className="overline">READ-ONLY IMPACT ANALYSIS</p><h1>New analysis</h1><p>Describe a change. LineageGuard reads DataHub and prepares a recommendation; it does not modify data.</p></div><span className="safe-badge">✓ No mutation</span></div>
    <div className="analysis-grid">
      <form className="card form-card" onSubmit={analyze}>
        <div className="step-number">01</div><h2>Your change</h2>
        {handoff && <div className="verified-handoff"><b>MCP-verified target</b><span>{handoff.target.label}</span><code>{handoff.target.urn}</code><button type="button" className="ghost" onClick={onClearHandoff}>Choose another asset</button></div>}
        {catalogTarget && !handoff && <div className="verified-handoff"><b>Catalog-selected target</b><span>{catalogTarget.label}</span><code>{catalogTarget.urn}</code><small>Selected from the live DataHub catalog. The analysis remains read-only.</small><button type="button" className="ghost" onClick={onClearCatalogTarget}>Choose another asset</button></div>}
        {revision && <div className="verified-handoff"><b>Revision requested</b><span>{revision.comment}</span><small>Change at least one field. Prior judge and approval authority cannot be reused.</small></div>}
        <label>DataHub asset URN<input value={assetUrn} onChange={(event) => { setAssetUrn(event.target.value); if (handoff) onClearHandoff(); if (catalogTarget) onClearCatalogTarget(); }} readOnly={handoff !== null} required /></label>
        <div className="field-pair">
          <label>Change type<select value={changeType} onChange={(event) => setChangeType(event.target.value as ChangeType)}><option value="ADD_COLUMN">Add a column</option><option value="RENAME_COLUMN">Rename a column</option><option value="CHANGE_COLUMN_TYPE">Change a column type</option><option value="DROP_COLUMN">Drop a column</option></select></label>
          <label>{changeType === "ADD_COLUMN" ? "New column name" : "Existing column name"}<input value={columnName} onChange={(event) => setColumnName(event.target.value)} required /></label>
        </div>
        <div className="field-pair">
          {needsNewValue && <label>{changeType === "RENAME_COLUMN" ? "New column name" : "New data type"}<input value={newValue} onChange={(event) => setNewValue(event.target.value)} required /></label>}
          {changeType === "ADD_COLUMN" && <label>Nullability<select value={columnNullable ? "true" : "false"} onChange={(event) => setColumnNullable(event.target.value === "true")}><option value="true">Nullable</option><option value="false">Non-nullable</option></select></label>}
          {changeType === "CHANGE_COLUMN_TYPE" && <label>Known compatibility<select value={typeChangeCompatible === null ? "unknown" : String(typeChangeCompatible)} onChange={(event) => setTypeChangeCompatible(event.target.value === "unknown" ? null : event.target.value === "true")}><option value="unknown">Determine during analysis</option><option value="true">Compatible</option><option value="false">Incompatible</option></select></label>}
          <label>Lineage depth<select value={depth} onChange={(event) => setDepth(Number(event.target.value))}>{[1, 2, 3, 4, 5].map((value) => <option key={value} value={value}>{value} hop(s)</option>)}</select></label>
        </div>
        <label>Reason<textarea value={reason} onChange={(event) => setReason(event.target.value)} required /></label>
        {errors.length > 0 && <ul className="integration-errors">{errors.map((item) => <li key={item}>{item}</li>)}</ul>}
        <button className="cta wide" disabled={busy || errors.length > 0 || (revisionFingerprint !== null && fingerprint === revisionFingerprint)}>{busy ? "Reading DataHub…" : revision ? "Run revised analysis →" : "Analyze impact →"}</button>
        {revisionFingerprint !== null && fingerprint === revisionFingerprint && <p className="integration-error">A revision must change at least one request field.</p>}
    {error && <p className="integration-error">{error}</p>}
    {restoredFromServer && <p className="cache-observability" data-testid="workflow-restore-status">Read-only analysis restored from the server. Judge and approval authority were reset.</p>}
      </form>
      <aside className="analysis-side">{busy && <section className="analysis-progress" role="status" aria-live="polite"><div><b>Checking what this change could affect</b><span>{analysisProgress < 35 ? "Finding the selected data item" : analysisProgress < 70 ? "Following connected tables and reports" : "Preparing a safe recommendation"}</span></div><div className="analysis-progress-track"><i style={{ width: `${analysisProgress}%` }} /></div><small>{analysisProgress}% · This check never modifies DataHub.</small></section>}{impact
        ? <section className={`demo-result live-impact risk-${impact.risk_assessment.level.toLowerCase()}`} data-testid="analysis-report" data-analysis-run-id={execution?.analysis_run_id ?? ""}>
          <span className="risk-pill">{impact.risk_assessment.level} · {impact.risk_assessment.score}/100</span>
          <h3>{impact.blast_radius} assets may be affected</h3>
          <p>{impact.evidence_bundle.items.length} DataHub evidence records support this read-only report.</p>
          <ul>{impact.impacted_assets.slice(0, 5).map((item) => <li key={item.asset_urn}><b>{item.criticality}</b> {shortUrn(item.asset_urn)}</li>)}</ul>
          <button className="ghost wide" onClick={() => go("Review")}>Continue to governed review →</button>
        </section>
        : <section className="card guide-card">
          <div className="guide-icon">✦</div>
          <h2>Simple and governed</h2>
          <p>The system evaluates evidence and proposes steps. It never deploys a schema change.</p>
          <div><span>1</span> Describe the change</div>
          <div><span>2</span> Review the impact</div>
          <div><span>3</span> Decide with evidence</div>
        </section>}</aside>
    </div>
  </section>;
}

function FollowUp({ go }: { go: (page: Page) => void }) {
  const [history, setHistory] = useState<RunSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { request<RunSummary[]>("/api/v1/judges/history").then(setHistory).catch((caught) => setError(caught instanceof Error ? caught.message : "History unavailable")); }, []);
  return <section className="page-content integration-page">
    <div className="page-heading">
      <div>
        <p className="overline">AUDITABLE FOLLOW-UP</p>
        <h1>Analysis follow-up</h1>
        <p>Review persisted independent-judging outcomes. Detailed proposal and audit controls stay in the governed review.</p>
      </div>
      <button className="ghost" onClick={() => go("Review")}>Open current review</button>
    </div>
    <section className="card follow-table">
      <div className="table-head"><h2>Recent governed reviews</h2><span>{history.length} run(s)</span></div>
      {error && <p className="integration-error">{error}</p>}
      {history.length === 0 && !error && <p className="empty-state">No judging run has been recorded yet. Run an impact analysis, then continue to governed review.</p>}
      {history.map((item) => <button className="table-row" key={item.run_id} onClick={() => go("Review")}>
        <span className="row-symbol">◌</span>
        <span><b>{item.decision ?? "GATE 0"}</b><code>{item.run_id}</code></span>
        <span className={`status ${item.decision === "FINALIZE_READ_ONLY" ? "done" : "pending"}`}>{item.openai_status ?? "—"} / {item.groq_status ?? "—"}</span>
        <span className="row-go">→</span>
      </button>)}
    </section>
  </section>;
}

function HealthView({ health }: { health: RuntimeHealth | null }) {
  const items = health ? [["API", health.status], ["DataHub", health.datahub], ["Qdrant", health.qdrant], ["LLM providers", health.llm_providers]] : [["API", "checking"], ["DataHub", "checking"], ["Qdrant", "checking"], ["LLM providers", "checking"]];
  const providers = health ? Object.entries(health.providers ?? {}) : [];
  const operational = health?.status === "ok";
  return <section className="page-content health-screen integration-page">
    <div className="page-heading">
      <div>
        <p className="overline">LIVE TECHNICAL STATUS</p>
        <h1>Platform health</h1>
        <p>This screen reads the LineageGuard health endpoint; it never displays provider secrets.</p>
      </div>
      <div className={`assistant-status ${operational ? "ready" : ""}`}><i /> {operational ? "OPERATIONAL" : "CHECKING"}</div>
    </div>
    <section className="health-hero">
      <span className="health-check">{operational ? "✓" : "…"}</span>
      <div>
        <h2>{operational ? "Core services are available" : "Checking service health"}</h2>
        <p>Health reports configuration readiness. External providers are considered live only after a successful request.</p>
      </div>
      <small>env: {health?.environment ?? "unknown"}</small>
    </section>
    <div className="health-grid">{items.map(([name, value]) => <HealthCard key={name} name={name} status={value} />)}</div>
    {providers.length > 0 && <section className="provider-health" data-testid="provider-readiness">
      <div className="page-heading compact">
        <div>
          <p className="overline">OPTIONAL MODEL ROLES</p>
          <h2>Provider configuration</h2>
          <p>Unconfigured actions are disabled. Configured providers still require a successful live request.</p>
        </div>
      </div>
      <div className="provider-row">{providers.map(([name, readiness]) => <article className={`provider-action ${readiness.available ? "available" : "unavailable"}`} key={name}>
        <header><b>{name.replaceAll("_", " ")}</b><strong>{readiness.available ? "CONFIGURED" : "DISABLED"}</strong></header>
        <code>{readiness.model ?? "Not configured"}</code>
        <small>{readiness.reason}</small>
      </article>)}</div>
    </section>}
    {health && <p className="writeback-bar">Write-back: <b className={health.writeback === "ready" ? "warn" : ""}>{health.writeback}</b> · demo mode: {String(health.demo_mode)} · the only possible mutation is one DataHub Analysis document, behind the reviewer capability and the opt-in flag.</p>}
  </section>;
}

function HealthCard({ name, status }: { name: string; status: string }) {
  const reachable = status === "ok";
  const configured = status === "configured";
  return <article className="health-card">
    <span className="health-mark">{reachable || configured ? "✓" : "!"}</span>
    <b>{name}</b>
    <span>{reachable ? "Reachable" : configured ? "Configured — validate live reads in Cartography" : "Requires attention or is checking"}</span>
    <div className={`health-state ${reachable || configured ? "ok" : "warn"}`}>{status}</div>
  </article>;
}
function icon(page: Page) { return ({ Accueil: "⌂", Cartographie: "◌", Assistant: "✦", "Nouvelle analyse": "＋", Suivi: "◷", Santé: "✓", Review: "▣" })[page]; }
function pageLabel(page: Page) { return ({ Accueil: "Home", Cartographie: "Cartography", Assistant: "Assistant", "Nouvelle analyse": "New analysis", Suivi: "Activity", Santé: "Health", Review: "Governed review" })[page]; }
function platformName(platform?: string | null) { return (platform ?? "unknown").replace("urn:li:dataPlatform:", ""); }
function shortUrn(urn: string) { return urn.length > 52 ? `${urn.slice(0, 23)}…${urn.slice(-25)}` : urn; }
