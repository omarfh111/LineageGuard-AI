import { expect, test, type Page, type Route } from "@playwright/test";

const runId = "4f4457c1-0b29-4f2d-8e31-b667b0427cf8";
const ordersUrn = "urn:li:dataset:(urn:li:dataPlatform:dbt,b2fd91.order_entry_db.order_entry.orders,PROD)";

const workflowGraph = {
  nodes: ["request", "metadata", "impact", "plan", "critic", "judges", "hitl"].map((id) => ({
    id, label: id, kind: "read-only", status: "PENDING", description: `${id} node`,
  })),
  edges: [],
  tracing_enabled: true,
  tracing_project: "lineageguard-e2e",
};

const impactReport = {
  request: {
    asset_urn: ordersUrn,
    change_type: "ADD_COLUMN",
    column_name: "lineageguard_demo_note",
    reason: "Controlled professional browser test.",
    environment: "PRODUCTION",
    lineage_depth: 2,
    column_nullable: true,
  },
  evidence_bundle: { items: [{ evidence_id: "E-schema-1" }] },
  blast_radius: 1,
  impacted_assets: [{ asset_urn: ordersUrn, platform_urn: "urn:li:dataPlatform:dbt", impact_type: "SOURCE", criticality: "MEDIUM" }],
  missing_metadata: [],
  risk_assessment: { score: 42, level: "MEDIUM", components: {}, explanation: ["Bounded E2E fixture."] },
  confidence: 0.9,
};

const remediationPlan = {
  source_asset_urn: ordersUrn,
  change_type: "ADD_COLUMN",
  migration_steps: [{ order: 1, action: "Validate contracts", rationale: "Protect consumers", affected_asset_urns: [ordersUrn] }],
  execution_status: "NOT_EXECUTED",
};

const execution = {
  analysis_run_id: runId,
  impact_report: impactReport,
  remediation_plan: remediationPlan,
  graph: {
    ...workflowGraph,
    nodes: workflowGraph.nodes.map((node) => ({ ...node, status: ["request", "metadata", "impact", "plan"].includes(node.id) ? "COMPLETED" : "PENDING" })),
  },
};

const initialGraph = {
  nodes: [
    { urn: ordersUrn, label: "orders", entity_type: "DATASET", platform_urn: "urn:li:dataPlatform:dbt", owner_urns: [], recent_actions: [] },
    { urn: "urn:li:dashboard:orders", label: "Orders dashboard", entity_type: "DASHBOARD", platform_urn: "urn:li:dataPlatform:looker", owner_urns: [], recent_actions: [] },
  ],
  edges: [{ source_urn: ordersUrn, target_urn: "urn:li:dashboard:orders", direction: "DOWNSTREAM", hops: 1 }],
  truncated: false,
};

const recoveredGraph = {
  ...initialGraph,
  nodes: [...initialGraph.nodes, { urn: "urn:li:chart:orders", label: "Orders chart", entity_type: "CHART", platform_urn: "urn:li:dataPlatform:looker", owner_urns: [], recent_actions: [] }],
};

function status(state: string, graph: typeof initialGraph, generation: number) {
  return {
    status: {
      state,
      loaded_assets: graph.nodes.length,
      loaded_edges: graph.edges.length,
      message: state === "RUNNING" ? "Refreshing in background" : "Catalog ready",
      last_updated_at: "2026-08-01T15:00:00Z",
      last_checked_at: "2026-08-01T15:00:00Z",
      refresh_reason: state === "RUNNING" ? "manual_catalog_refresh" : "scheduled_catalog_poll",
      refresh_in_progress: state === "RUNNING",
      consecutive_failures: 0,
      generation,
    },
    graph,
  };
}

async function json(route: Route, body: unknown, statusCode = 200) {
  await route.fulfill({ status: statusCode, contentType: "application/json", body: JSON.stringify(body) });
}

async function mockApi(page: Page, options: { recoverRefresh?: boolean; nvidiaAvailable?: boolean; criticFails?: boolean } = {}) {
  let refreshRequested = false;
  let recoveryPolls = 0;
  let restoreCalls = 0;
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/v1/health") return json(route, { status: "ok", environment: "test", datahub: "configured", llm_providers: "partial", qdrant: "configured", writeback: "disabled", demo_mode: false, providers: {
      chat: { available: true, model: "chat-test", mode: "external", reason: "Configured for test." },
      nvidia_critic: options.nvidiaAvailable
        ? { available: true, model: "nvidia-test", mode: "external", reason: "Configured for test." }
        : { available: false, model: null, mode: "external", reason: "NVIDIA critic is not configured." },
      openai_judge: { available: true, model: "openai-test", mode: "external", reason: "Configured for test." },
      groq_judge: { available: false, model: null, mode: "external", reason: "Groq judge is not configured." },
    } });
    if (path === "/api/v1/workflows/critique" && options.criticFails) return json(route, { detail: "NVIDIA runtime unavailable" }, 502);
    if (path === "/api/v1/judges/history") return json(route, []);
    if (path === "/api/v1/workflows/graph") return json(route, workflowGraph);
    if (path === `/api/v1/workflows/analysis/${runId}`) { restoreCalls += 1; return json(route, execution); }
    if (path === "/api/v1/workflows/analyze" && request.method() === "POST") return json(route, execution);
    if (path === "/api/v1/chat/index/status") return json(route, { state: "COMPLETED", indexed_assets: 2, total_assets: 2, message: "Ready", query_available: true });
    if (path.startsWith("/api/v1/chat/memory/")) return json(route, { enabled: true, message_count: 0, max_turns: 6 });
    if (path === "/api/v1/datahub/catalog/cache/refresh" && request.method() === "POST") {
      refreshRequested = true;
      return json(route, status("RUNNING", initialGraph, 1).status);
    }
    if (path === "/api/v1/datahub/catalog/cache") {
      if (!options.recoverRefresh || !refreshRequested) return json(route, status("READY", initialGraph, 1));
      recoveryPolls += 1;
      return recoveryPolls === 1
        ? json(route, status("RUNNING", { nodes: [], edges: [], truncated: false }, 1))
        : json(route, status("READY", recoveredGraph, 2));
    }
    return json(route, { detail: `Unexpected mocked route: ${request.method()} ${path}` }, 501);
  });
  return { getRestoreCalls: () => restoreCalls };
}

test("refresh recovery never blanks the useful 3D graph", async ({ page }) => {
  await mockApi(page, { recoverRefresh: true });
  await page.goto("/#/cartographie", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("catalog-graph")).toHaveAttribute("data-node-count", "2");

  await page.getByRole("button", { name: "Refresh from DataHub" }).click();
  await expect(page.getByTestId("catalog-cache-state")).toContainText("REFRESHING");
  await expect(page.getByTestId("catalog-graph")).toHaveAttribute("data-node-count", "2");

  await expect(page.getByTestId("catalog-cache-state")).toContainText("READY", { timeout: 13_000 });
  await expect(page.getByTestId("catalog-graph")).toHaveAttribute("data-node-count", "3");
});

test("workflow reload restores only the immutable server snapshot", async ({ page }) => {
  const api = await mockApi(page);
  await page.goto("/#analyse", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "Analyze impact", exact: false }).click();
  const report = page.getByTestId("analysis-report");
  await expect(report).toHaveAttribute("data-analysis-run-id", runId);
  await expect(report).toContainText("42/100");

  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("analysis-report")).toHaveAttribute("data-analysis-run-id", runId);
  await expect(page.getByTestId("workflow-restore-status")).toContainText("Judge and approval authority were reset");
  expect(api.getRestoreCalls()).toBe(1);
  const persisted = await page.evaluate(() => Object.fromEntries(Object.entries(sessionStorage)));
  expect(persisted).toEqual({ "lineageguard-analysis-run-v1": runId });
  await expect(page.getByText("Proposition de write-back")).toHaveCount(0);
});

test("tampered workflow pointer is removed without a restore request", async ({ page }) => {
  await page.addInitScript(() => sessionStorage.setItem("lineageguard-analysis-run-v1", "../../secrets"));
  const api = await mockApi(page);
  await page.goto("/#analyse", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Your change" })).toBeVisible();
  expect(api.getRestoreCalls()).toBe(0);
  expect(await page.evaluate(() => sessionStorage.getItem("lineageguard-analysis-run-v1"))).toBeNull();
});

test("governed review disables provider actions that cannot run", async ({ page }) => {
  await page.addInitScript((id) => sessionStorage.setItem("lineageguard-analysis-run-v1", id), runId);
  await mockApi(page);
  await page.goto("/#/review", { waitUntil: "domcontentloaded" });

  await expect(page.getByTestId("governed-review")).toHaveAttribute("data-analysis-run-id", runId);
  await expect(page.getByRole("button", { name: "AI critic unavailable" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Judges unavailable" })).toBeDisabled();
  await expect(page.getByText("NVIDIA critic is not configured.")).toBeVisible();
  await expect(page.getByText("Groq judge is not configured.")).toBeVisible();
  await expect(page.getByRole("navigation")).toHaveCount(1);
});

test("a failed live provider is circuit-broken for the page session", async ({ page }) => {
  await page.addInitScript((id) => sessionStorage.setItem("lineageguard-analysis-run-v1", id), runId);
  await mockApi(page, { nvidiaAvailable: true, criticFails: true });
  await page.goto("/#/review", { waitUntil: "domcontentloaded" });

  await page.getByRole("button", { name: "Run AI critic" }).click();
  await expect(page.getByRole("alert")).toContainText("NVIDIA runtime unavailable");
  await expect(page.getByRole("button", { name: "AI critic unavailable" })).toBeDisabled();
  await expect(page.getByText(/last live request failed/i)).toBeVisible();
});
