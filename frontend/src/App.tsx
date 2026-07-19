import { useEffect, useState } from "react";

type Health = {
  status: "ok";
  service: string;
  environment: string;
  datahub: "not_configured";
  llm_providers: "not_configured";
};

type HealthState =
  | { kind: "loading" }
  | { kind: "ready"; health: Health }
  | { kind: "unavailable" };

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export default function App() {
  const [state, setState] = useState<HealthState>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();

    fetch(`${apiBaseUrl}/api/v1/health`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error("Health check failed");
        return response.json() as Promise<Health>;
      })
      .then((health) => setState({ kind: "ready", health }))
      .catch(() => setState({ kind: "unavailable" }));

    return () => controller.abort();
  }, []);

  return (
    <main>
      <p className="eyebrow">Build with DataHub · Agents That Do Real Work</p>
      <h1>LineageGuard AI</h1>
      <p className="intro">
        Bootstrap health page. DataHub, agents, and LLM providers remain disabled
        until their dedicated implementation phases.
      </p>

      <section aria-live="polite" className="health-card">
        <h2>Service health</h2>
        {state.kind === "loading" && <p>Checking the local API…</p>}
        {state.kind === "unavailable" && (
          <p className="warning">
            API unavailable. Start the backend on port 8000, then refresh this page.
          </p>
        )}
        {state.kind === "ready" && (
          <dl>
            <div><dt>API</dt><dd className="healthy">{state.health.status}</dd></div>
            <div><dt>Environment</dt><dd>{state.health.environment}</dd></div>
            <div><dt>DataHub</dt><dd>{state.health.datahub}</dd></div>
            <div><dt>LLM providers</dt><dd>{state.health.llm_providers}</dd></div>
          </dl>
        )}
      </section>
    </main>
  );
}
