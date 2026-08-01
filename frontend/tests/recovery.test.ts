import { describe, expect, it } from "vitest";
import {
  clearAnalysisRun,
  loadAnalysisRun,
  recoverCatalogGraph,
  saveAnalysisRun,
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
