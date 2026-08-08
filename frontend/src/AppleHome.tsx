import { Suspense, lazy } from "react";

// The hero field is decorative, so it streams in from the shared Three.js chunk.
const LineageField = lazy(() => import("./LineageField"));

type HomePage = "Cartographie" | "Assistant" | "Nouvelle analyse" | "Suivi" | "Santé";

const pillars = [
  {
    icon: "◌",
    tone: "blue",
    title: "Cartography",
    body: "The full bounded catalog as a live 3D graph: platform colors, lineage edges, hover metadata, and in-session activity.",
  },
  {
    icon: "✦",
    tone: "violet",
    title: "Agentic RAG assistant",
    body: "Planning, Qdrant retrieval, live MCP reads, grounded answer, deterministic verification. Every claim needs a live anchor.",
  },
  {
    icon: "＋",
    tone: "cyan",
    title: "Impact analysis",
    body: "Blast radius, risk score, remediation, and a rollback proposal marked NOT_EXECUTED — for four typed schema changes.",
  },
  {
    icon: "✓",
    tone: "mint",
    title: "Human-in-the-loop",
    body: "Double PASS is not permission. A reviewer capability, an explicit decision, and an opt-in flag gate every write.",
  },
];

const gates = [
  { step: "01", title: "Deterministic engine", body: "Contract validation, exact lineage paths, risk score." },
  { step: "02", title: "AI Critic", body: "NVIDIA Nemotron advisory review. Cannot approve or call DataHub." },
  { step: "03", title: "Independent Judge 1", body: "Reviews factual grounding, blind to the other verdict." },
  { step: "04", title: "Independent Judge 2", body: "Reviews technical correctness and safety." },
  { step: "05", title: "Human approval", body: "Capability, explicit decision, opt-in flag, audit trail.", final: true },
];

const evidence = [
  { value: "1,191", label: "live root assets" },
  { value: "0.902", label: "Precision@6" },
  { value: "0", label: "unsupported-claim escape" },
  { value: "167 / 171", label: "backend tests passing" },
];

export default function AppleHome({ go }: { go: (page: HomePage) => void }) {
  return <div className="lg-home">
    <section className="home-hero">
      <Suspense fallback={null}><LineageField mode="ambient" className="hero-field" /></Suspense>
      <div className="hero-veil" aria-hidden="true" />
      <div className="hero-inner">
        <p className="overline">LINEAGEGUARD · EVIDENCE-FIRST DATAHUB AGENTS</p>
        <h1>Trust every<br /><span>data decision.</span></h1>
        <p className="hero-subtitle">Understand what matters. Anticipate every change. Move forward with confidence — on live DataHub evidence, never on a guess.</p>
        <div className="hero-actions">
          <button className="cta" onClick={() => go("Nouvelle analyse")}>Get started <span>→</span></button>
          <button className="ghost" onClick={() => go("Cartographie")}>Explore the catalog <span>→</span></button>
        </div>
        <div className="evidence-strip">
          {evidence.map((item) => <div key={item.label}><b>{item.value}</b><span>{item.label}</span></div>)}
          <div className="evidence-note">Dated evidence, 2026-08-01 professional run</div>
        </div>
      </div>
    </section>

    <section className="home-intro">
      <p className="overline">SEE THE BIG PICTURE</p>
      <h2>Your data.<br /><span>Finally in focus.</span></h2>
      <p>LineageGuard reads live metadata and multi-hop lineage through the official DataHub MCP server, turns it into a deterministic impact dossier, and hands that dossier to independent reviewers. The only possible mutation is one governed Analysis document — after explicit human approval.</p>
    </section>

    <section className="home-pillars">
      <div className="pillar-grid">
        {pillars.map((pillar) => <article className="pillar" key={pillar.title}>
          <div className={`pillar-icon ${pillar.tone}`}>{pillar.icon}</div>
          <h3>{pillar.title}</h3>
          <p>{pillar.body}</p>
        </article>)}
      </div>
    </section>

    <section className="home-gates">
      <div className="gates-panel">
        <div className="gates-glow" aria-hidden="true" />
        <p className="overline">EVIDENCE → REVIEW → HUMAN CONTROL</p>
        <h2>Five gates between a proposal and a write.</h2>
        <div className="gate-grid">
          {gates.map((gate) => <div className={`gate ${gate.final ? "final" : ""}`} key={gate.step}>
            <span className="gate-step">{gate.step}</span>
            <b>{gate.title}</b>
            <span className="gate-body">{gate.body}</span>
          </div>)}
        </div>
      </div>
    </section>

    <section className="home-closing">
      <p className="overline">READY WHEN YOU ARE</p>
      <h2>Your data deserves a clearer view.</h2>
      <button className="cta" onClick={() => go("Nouvelle analyse")}>Open workspace <span>→</span></button>
    </section>
  </div>;
}
