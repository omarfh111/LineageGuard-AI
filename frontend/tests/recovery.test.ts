import { describe, expect, it } from "vitest";
import {
  clearAnalysisRun,
  loadAnalysisRun,
  recoverCatalogGraph,
  saveAnalysisRun,
  stabilizeCatalogGraphData,
} from "../src/recovery";

function storageFixture(): Storage {
  const values = new Map<string, string>();
  return {
    get length() { return values.size; },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => { values.delete(key); },
    setItem: (key, value) => { values.set(key, value); },
  };
}

describe("catalog refresh recovery", () => {
  it("keeps a useful graph when a transient snapshot is empty", () => {
    const current = { nodes: [{ id: "orders" }], edges: [], truncated: false };
    expect(recoverCatalogGraph(current, { nodes: [], edges: [], truncated: false })).toBe(current);
  });

  it("atomically accepts the recovered graph", () => {
    const current = { nodes: [{ id: "orders" }], edges: [], truncated: false };
    const recovered = { nodes: [{ id: "orders" }, { id: "customers" }], edges: [{ source: "orders", target: "customers" }], truncated: false };
    expect(recoverCatalogGraph(current, recovered)).toBe(recovered);
  });

  it("does not restart ForceGraph for a status-only polling response", () => {
    const nodes = [{ urn: "orders", label: "Orders", owner_urns: [] as string[] }];
    const edges = [{ source_urn: "orders", target_urn: "dashboard", direction: "DOWNSTREAM", hops: 1 }];
    const first = stabilizeCatalogGraphData(null, nodes, edges);
    first.data.nodes[0].x = 42;
    first.data.nodes[0].y = -7;

    const polled = stabilizeCatalogGraphData(first, [
      { urn: "orders", label: "Orders refreshed", owner_urns: ["owner"] },
    ], [{ ...edges[0] }]);

    expect(polled).toBe(first);
    expect(polled.data).toBe(first.data);
    expect(polled.data.nodes[0]).toBe(first.data.nodes[0]);
    expect(polled.data.nodes[0]).toMatchObject({ x: 42, y: -7, label: "Orders refreshed" });
  });

  it("accepts real topology changes while preserving known node positions", () => {
    const first = stabilizeCatalogGraphData(null, [
      { urn: "orders", label: "Orders" },
    ], []);
    first.data.nodes[0].x = 19;
    const updated = stabilizeCatalogGraphData(first, [
      { urn: "customers", label: "Customers" },
      { urn: "orders", label: "Orders" },
    ], [{ source_urn: "orders", target_urn: "customers", direction: "DOWNSTREAM", hops: 1 }]);

    expect(updated).not.toBe(first);
    expect(updated.data.nodes.find((node) => node.urn === "orders")).toBe(first.data.nodes[0]);
    expect(updated.data.nodes.find((node) => node.urn === "orders")?.x).toBe(19);
    expect(updated.data.links).toHaveLength(1);
  });

  it("ignores backend ordering differences in an unchanged topology", () => {
    const nodes = [{ urn: "orders" }, { urn: "customers" }];
    const edges = [{ source_urn: "orders", target_urn: "customers", direction: "DOWNSTREAM", hops: 1 }];
    const first = stabilizeCatalogGraphData(null, nodes, edges);
    const reordered = stabilizeCatalogGraphData(first, [...nodes].reverse(), [...edges]);
    expect(reordered).toBe(first);
  });
});

describe("opaque workflow reload pointer", () => {
  it("stores and restores only a UUID run identifier", () => {
    const storage = storageFixture();
    const runId = "4f4457c1-0b29-4f2d-8e31-b667b0427cf8";
    saveAnalysisRun(storage, runId);
    expect(loadAnalysisRun(storage)).toBe(runId);
    expect(storage.length).toBe(1);
    clearAnalysisRun(storage);
    expect(loadAnalysisRun(storage)).toBeNull();
  });

  it("removes a tampered identifier before any API request", () => {
    const storage = storageFixture();
    storage.setItem("lineageguard-analysis-run-v1", "../../secrets");
    expect(loadAnalysisRun(storage)).toBeNull();
    expect(storage.length).toBe(0);
  });
});
