export type RecoverableCatalogGraph<TNode = unknown, TEdge = unknown> = {
  nodes: TNode[];
  edges: TEdge[];
  truncated: boolean;
};

type CatalogNodeIdentity = { urn: string };
type CatalogEdgeIdentity = {
  source_urn: string;
  target_urn: string;
  direction: string;
  hops: number;
};

export type ForceCatalogNode<TNode extends CatalogNodeIdentity> = TNode & {
  id: string;
  x?: number;
  y?: number;
  z?: number;
  vx?: number;
  vy?: number;
  vz?: number;
};

export type ForceCatalogLink<TEdge extends CatalogEdgeIdentity> = TEdge & {
  source: string | { id?: string; urn?: string };
  target: string | { id?: string; urn?: string };
  label: string;
};

export type StableCatalogGraphData<
  TNode extends CatalogNodeIdentity,
  TEdge extends CatalogEdgeIdentity,
> = {
  signature: string;
  data: {
    nodes: Array<ForceCatalogNode<TNode>>;
    links: Array<ForceCatalogLink<TEdge>>;
  };
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

/** Keep ForceGraph coordinates and object identity across status-only polls. */
export function stabilizeCatalogGraphData<
  TNode extends CatalogNodeIdentity,
  TEdge extends CatalogEdgeIdentity,
>(
  previous: StableCatalogGraphData<TNode, TEdge> | null,
  nodes: TNode[],
  edges: TEdge[],
): StableCatalogGraphData<TNode, TEdge> {
  const nodeIdentity = nodes.map((node) => node.urn).sort();
  const edgeIdentity = edges.map((edge) => catalogEdgeKey(edge)).sort();
  const signature = `${nodeIdentity.join("\u0000")}\u0001${edgeIdentity.join("\u0000")}`;
  const previousNodes = new Map(
    (previous?.data.nodes ?? []).map((node) => [node.urn, node]),
  );
  const nextNodes = nodes.map((node) => {
    const stable = previousNodes.get(node.urn);
    if (stable) {
      Object.assign(stable, node, { id: node.urn });
      return stable;
    }
    return { ...node, id: node.urn } as ForceCatalogNode<TNode>;
  });

  if (previous?.signature === signature) {
    const incomingNodes = new Map(nodes.map((node) => [node.urn, node]));
    for (const stable of previous.data.nodes) {
      const incoming = incomingNodes.get(stable.urn);
      if (incoming) Object.assign(stable, incoming, { id: stable.urn });
    }
    const incomingEdges = new Map(edges.map((edge) => [catalogEdgeKey(edge), edge]));
    for (const stable of previous.data.links) {
      const incoming = incomingEdges.get(catalogEdgeKey(stable));
      if (incoming) {
        Object.assign(stable, incoming, {
          label: `${incoming.direction} · ${incoming.hops} hop(s)`,
        });
      }
    }
    return previous;
  }

  return {
    signature,
    data: {
      nodes: nextNodes,
      links: edges.map((edge) => ({
        ...edge,
        source: edge.source_urn,
        target: edge.target_urn,
        label: `${edge.direction} · ${edge.hops} hop(s)`,
      })),
    },
  };
}

function catalogEdgeKey(edge: CatalogEdgeIdentity): string {
  return `${edge.source_urn}\u0000${edge.target_urn}\u0000${edge.direction}\u0000${edge.hops}`;
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
