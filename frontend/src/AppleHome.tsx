import "./apple-home.css";
import "./apple-scroll-motion.css";
import "./final-home-fixes.css";
import "./showcase-title-fix.css";

type HomePage = "Cartographie" | "Assistant" | "Nouvelle analyse" | "Suivi" | "Santé";

export default function AppleHome({ go }: { go: (page: HomePage) => void }) {
  return <div className="apple-home">
    <section className="apple-hero">
      <div className="hero-copy"><p className="apple-kicker">LINEAGEGUARD</p><h1>Trust every<br /><em>data decision.</em></h1><p className="hero-subtitle">Understand what matters. Anticipate every change. Move forward with confidence.</p><div className="apple-links"><button onClick={() => go("Nouvelle analyse")}>Get started <span>→</span></button><button onClick={() => go("Cartographie")}>Explore <span>→</span></button></div></div>
      <div className="hero-logo-stage" aria-hidden="true"><div className="logo-aura" /><img src="/lineageguard-logo.png" alt="" /><div className="hero-orbit hero-orbit-one" /><div className="hero-orbit hero-orbit-two" /></div>
      <p className="hero-scroll">SCROLL TO EXPLORE <span>↓</span></p>
    </section>
    <section className="apple-intro"><p className="apple-kicker">SEE THE BIG PICTURE</p><h2>Your data.<br /><span>Finally in focus.</span></h2><p>LineageGuard turns complex information into clear decisions. See connections, understand impact, and take action with confidence.</p></section>
    <section className="apple-showcase dark-showcase"><div className="showcase-copy"><p className="apple-kicker">CARTOGRAPHY</p><h2>Everything connects.<br /><span>Everything makes sense.</span></h2><p>A living view of your information, from every source to every report that relies on it.</p><button onClick={() => go("Cartographie")}>Explore cartography <span>→</span></button></div><div className="data-universe" aria-hidden="true"><i className="universe-line u1" /><i className="universe-line u2" /><i className="universe-line u3" /><div className="universe-node source">Source</div><div className="universe-node core">Orders</div><div className="universe-node report">Report</div><div className="universe-node team">Team</div></div></section>
    <section className="apple-feature-grid"><article className="feature-tile assistant-tile"><div><p className="apple-kicker">ASSISTANT</p><h3>Answers when<br />you need them.</h3><p>Ask a question in your own words.</p><button onClick={() => go("Assistant")}>Try the assistant <span>→</span></button></div><div className="assistant-glow">✦</div></article><article className="feature-tile analysis-tile"><div><p className="apple-kicker">ANALYSIS</p><h3>Change without<br />surprises.</h3><p>Discover what a change can affect before you commit.</p><button onClick={() => go("Nouvelle analyse")}>Prepare an analysis <span>→</span></button></div><div className="impact-rings"><i /><i /><i /></div></article></section>
    <section className="apple-precision"><div className="precision-art" aria-hidden="true"><div className="precision-sphere"><span>✓</span></div><i /><i /><i /></div><div><p className="apple-kicker">FOLLOW-UP AND HEALTH</p><h2>Stay in control.<br /><span>At every moment.</span></h2><p>Track important decisions and check your platform health in one clear place.</p><div className="apple-links"><button onClick={() => go("Suivi")}>View activity <span>→</span></button><button onClick={() => go("Santé")}>View health <span>→</span></button></div></div></section>
    <section className="apple-closing"><p className="apple-kicker">READY WHEN YOU ARE</p><h2>Your data deserves<br />a clearer view.</h2><button onClick={() => go("Nouvelle analyse")}>Open workspace <span>→</span></button></section>
  </div>;
}
