import Link from "next/link";

export function LandingPage() {
  return (
    <main className="landing-page">
      <nav className="landing-nav" aria-label="Public navigation">
        <Link className="brand" href="/">XENOVARIENTS</Link>
        <Link className="landing-signin" href="/login">Sign in</Link>
      </nav>
      <section className="landing-hero" aria-labelledby="landing-title">
        <p className="eyebrow">CUSTOMER UNDERSTANDING · CREATOR COMMERCE · AGENT WORKSPACE</p>
        <h1 id="landing-title">Know your customers. Act with confidence.</h1>
        <p className="landing-lede">
          Xenovarients brings customer history, consent-aware reviews, and a read-only
          business assistant into one workspace.
        </p>
        <div className="landing-actions">
          <Link className="primary-action" href="/signup">Create your workspace</Link>
          <Link className="secondary-action" href="/login">Sign in</Link>
        </div>
      </section>
      <section className="landing-grid" aria-label="Product capabilities">
        <article className="landing-card">
          <span className="chip">Customer Genome</span>
          <h2>Understand repeat customers</h2>
          <p>Use authoritative purchase history, returning-customer bubbles, and variant-safe restock lists.</p>
        </article>
        <article className="landing-card">
          <span className="chip">Review</span>
          <h2>Keep consent in control</h2>
          <p>Capture reviews, preserve their original content, and export only with active permission.</p>
        </article>
        <article className="landing-card">
          <span className="chip">Agent Workspace</span>
          <h2>Ask without giving up control</h2>
          <p>Get FAQ and read-only business answers without AI write actions or unapproved outreach.</p>
        </article>
      </section>
      <p className="landing-note">Ads Intelligence is planned separately after data feasibility and platform approval.</p>
    </main>
  );
}
