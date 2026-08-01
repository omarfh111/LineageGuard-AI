export type RecoverableCatalogGraph<TNode = unknown, TEdge = unknown> = {
  nodes: TNode[];
  edges: TEdge[];
  truncated: boolean;
};

const analysisRunKey = "lineageguard-analysis-run-v1";
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/** Keep the last useful graph while a failed/restarting server returns no data. */
export function recoverCatalogGraph<TNode, TEdge>(
  current: RecoverableCatalogGraph<TNode, TEdge> | null,
  incoming: RecoverableCatalogGraph<TNode, TEdge>,
): RecoverableCatalogGraph<TNode, TEdge> {
  if (incoming.nodes.length > 0 || current === null || current.nodes.length === 0) {
    return incoming;
  }
  return current;
}

export function saveAnalysisRun(storage: Storage, runId: string): void {
  if (!uuidPattern.test(runId)) throw new Error("Invalid analysis run identifier");
  storage.setItem(analysisRunKey, runId);
}

export function loadAnalysisRun(storage: Storage): string | null {
  const runId = storage.getItem(analysisRunKey);
  if (!runId) return null;
  if (!uuidPattern.test(runId)) {
    storage.removeItem(analysisRunKey);
    return null;
  }
  return runId;
}

export function clearAnalysisRun(storage: Storage): void {
  storage.removeItem(analysisRunKey);
}
