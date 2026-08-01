import { describe, expect, it } from "vitest";

import { providerReady, providerReason, type RuntimeHealth } from "../src/runtimeHealth";

const health: RuntimeHealth = {
  status: "ok",
  environment: "test",
  datahub: "configured",
  llm_providers: "partial",
  qdrant: "configured",
  writeback: "disabled",
  demo_mode: false,
  providers: {
    openai_judge: { available: true, model: "gpt-test", mode: "external", reason: "Configured." },
    groq_judge: { available: false, model: null, mode: "external", reason: "Missing model." },
  },
};

describe("provider readiness", () => {
  it("enables only explicitly available runtime roles", () => {
    expect(providerReady(health, "openai_judge")).toBe(true);
    expect(providerReady(health, "groq_judge")).toBe(false);
    expect(providerReady(health, "nvidia_critic")).toBe(false);
  });

  it("returns safe reasons without inferring readiness", () => {
    expect(providerReason(health, "groq_judge")).toBe("Missing model.");
    expect(providerReason(null, "groq_judge")).toContain("still loading");
  });
});
