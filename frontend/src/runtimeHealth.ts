export type ProviderReadiness = {
  available: boolean;
  model: string | null;
  mode: "external" | "local_fallback";
  reason: string;
};

export type RuntimeHealth = {
  status: string;
  environment: string;
  datahub: "configured" | "not_configured";
  llm_providers: "configured" | "partial" | "not_configured";
  qdrant: "configured" | "not_configured";
  writeback: "disabled" | "reviewer_unconfigured" | "ready";
  demo_mode: boolean;
  providers: Record<string, ProviderReadiness>;
};

export function providerReady(
  health: RuntimeHealth | null,
  provider: string,
): boolean {
  return health?.providers?.[provider]?.available === true;
}

export function providerReason(
  health: RuntimeHealth | null,
  provider: string,
): string {
  if (!health) return "Provider readiness is still loading.";
  return health.providers?.[provider]?.reason ?? "Provider is unavailable in this runtime.";
}
