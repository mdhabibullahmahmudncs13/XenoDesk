"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { fetchApi } from "../lib/api";

type Profile = {
  business_type?: string;
  location?: string;
  product_idea?: string;
  investment_budget?: number;
  team_size?: string;
  account_type?: string;
  experience?: string;
  sales_channels: string[];
};

type ChatMessage = {
  role: "assistant" | "user";
  text: string;
};

type OnboardingStep = {
  complete: boolean;
  field: string | null;
  prompt: string;
  options: string[];
  progress: number;
  total: number;
  profile: Profile | null;
};

type CartListing = {
  id: string;
  listing_id: string;
  marketplace: string;
  title: string;
  unit_price: number | null;
  currency: string;
  shipping_estimate: string | null;
};

type Quality = { score: number; label: string; reasons?: string[] };

type MarketPanel = { available: boolean; reason?: string; quality: Quality };

type MarketSnapshot = {
  keyword: string;
  captured_at: string;
  expires_at: string;
  cached?: boolean;
  stale?: boolean;
  quality: { score: number; label: string; panels: Record<string, number> };
  demand: MarketPanel & {
    level?: string;
    current_index?: number;
    change_pct?: number | null;
    direction?: string;
    peak_months?: string[];
    seasonality?: { label: string; ratio: number | null };
    regions?: { region: string; index: number }[];
    related_queries?: { query: string }[];
    series?: { month: string; index: number }[];
    window?: { months: number; from: string; to: string };
  };
  competition: MarketPanel & {
    seller_count?: number;
    listing_count?: number;
    density?: string;
    hhi?: number;
    top_seller_share_pct?: number;
    established_seller_share_pct?: number;
    median_reviews?: number | null;
    median_rating?: number | null;
  };
  prices: MarketPanel & {
    currency?: string;
    median?: number;
    p25?: number;
    p75?: number;
    min?: number;
    max?: number;
    median_discount_pct?: number | null;
    median_units_sold?: number | null;
    sample?: number;
    outliers_removed?: number;
    basis?: string;
  };
  risks: { id: string; label: string; level: string; detail: string }[];
  sources: { id: string; label: string; status: string; detail: string; url: string }[];
  method: string;
};

const emptyProfile: Profile = {
  business_type: "",
  location: "",
  product_idea: "",
  investment_budget: undefined,
  team_size: "",
  account_type: "",
  experience: "",
  sales_channels: [],
};

// The onboarding assistant's name, used on every bubble so the chat reads as one
// person talking rather than a sequence of system prompts.
const ASSISTANT = "Xeni";

export function SourcingWorkspace({ view }: { view: "onboarding" | "research" | "products" | "cart" | "settings" }) {
  const router = useRouter();
  const [profile, setProfile] = useState<Profile>(emptyProfile);
  const [cart, setCart] = useState<CartListing[]>([]);
  const [snapshot, setSnapshot] = useState<MarketSnapshot | null>(null);
  const [keyword, setKeyword] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [chatAnswer, setChatAnswer] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [currentStep, setCurrentStep] = useState<OnboardingStep | null>(null);
  const [selectedChannels, setSelectedChannels] = useState<string[]>([]);
  const chatListRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const atBottomRef = useRef(true);
  const [atBottom, setAtBottom] = useState(true);

  useEffect(() => {
    if (view === "onboarding") {
      fetchApi<OnboardingStep>("/api/v1/sourcing/onboarding")
        .then((step) => {
          setCurrentStep(step);
          setProfile(step.profile || emptyProfile);
          if (step.profile?.product_idea) setKeyword(step.profile.product_idea);
          // A returning reader still gets the last line, even when it is the closing one.
          setChatMessages([{ role: "assistant", text: step.prompt }]);
          setLoaded(true);
        })
        .catch((error: Error) => {
          setMessage(error.message);
          setLoaded(true);
        });
      return;
    }
    if (view !== "research" && view !== "products" && view !== "settings") return;
    fetchApi<Profile | null>("/api/v1/sourcing/profile")
      .then((saved) => {
        if (saved) {
          setProfile(saved);
          if (saved.product_idea) setKeyword(saved.product_idea);
        }
        setLoaded(true);
      })
      .catch((error: Error) => {
        setMessage(error.message);
        setLoaded(true);
      });
  }, [view]);

  // The list is the only scroll container, so scrolling it never moves the page.
  function scrollToLatest(behavior: ScrollBehavior = "auto") {
    const list = chatListRef.current;
    if (list) list.scrollTo({ top: list.scrollHeight, behavior });
  }

  useEffect(() => {
    // Follow the conversation only while the reader is already at the bottom;
    // otherwise they are reading back and a "Jump to latest" button appears.
    // No animation frame here: a background tab never paints, and the follow must not
    // depend on the tab being visible.
    if (atBottom) scrollToLatest();
  }, [chatMessages, busy, atBottom]);

  useEffect(() => {
    // The composer grows with the text up to about four lines, then scrolls.
    const input = composerRef.current;
    if (!input) return;
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 132)}px`;
  }, [chatAnswer]);

  function handleChatScroll() {
    const list = chatListRef.current;
    if (!list) return;
    const nearBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 72;
    atBottomRef.current = nearBottom;
    setAtBottom(nearBottom);
  }

  useEffect(() => {
    // A shorter list (a resize, the suggestion row, the closing card) would otherwise
    // leave the newest line below the fold. Follow the bottom while the reader was there.
    const list = chatListRef.current;
    if (!list || typeof ResizeObserver === "undefined") return;
    const keepAtBottom = new ResizeObserver(() => {
      if (atBottomRef.current) list.scrollTop = list.scrollHeight;
    });
    keepAtBottom.observe(list);
    return () => keepAtBottom.disconnect();
  }, [loaded]);

  useEffect(() => {
    if (view !== "cart") return;
    fetchApi<CartListing[]>("/api/v1/sourcing/cart")
      .then(setCart)
      .catch((error: Error) => setMessage(error.message));
  }, [view]);

  useEffect(() => {
    if (view !== "research") return;
    // A saved snapshot costs nothing to show and keeps the previous reading visible
    // until the reader asks for a fresh one.
    fetchApi<MarketSnapshot | null>("/api/v1/sourcing/research/latest")
      .then(setSnapshot)
      .catch(() => setSnapshot(null));
  }, [view]);

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const saved = await fetchApi<Profile>("/api/v1/sourcing/profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(profile),
      });
      setProfile(saved);
      setKeyword(saved.product_idea || "");
      setMessage("Profile saved. Market Intelligence can use this idea.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to save onboarding.");
    } finally {
      setBusy(false);
    }
  }

  async function submitOnboardingAnswer(answer: string) {
    const text = answer.trim();
    if (!text || busy) return;
    setBusy(true);
    setMessage("");
    setChatMessages((messages) => [...messages, { role: "user", text }]);
    setChatAnswer("");
    // Sending is deliberate: follow the new message even if reading back.
    atBottomRef.current = true;
    setAtBottom(true);
    try {
      const step = await fetchApi<OnboardingStep>("/api/v1/sourcing/onboarding/answer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answer: text }),
      });
      setCurrentStep(step);
      setProfile(step.profile || emptyProfile);
      if (step.profile?.product_idea) setKeyword(step.profile.product_idea);
      setSelectedChannels([]);
      if (step.complete) {
        // The server's closing line says back what it understood.
        setChatMessages((messages) => [
          ...messages,
          { role: "assistant", text: step.prompt },
        ]);
      } else {
        setChatMessages((messages) => [
          ...messages,
          { role: "assistant", text: step.prompt },
        ]);
      }
    } catch (error) {
      setChatMessages((messages) => [
        ...messages,
        { role: "assistant", text: error instanceof Error ? error.message : "Unable to save that answer." },
      ]);
    } finally {
      setBusy(false);
      composerRef.current?.focus();
    }
  }

  async function trackProduct(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      await fetchApi<{ keyword: string }>("/api/v1/sourcing/products", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ keyword }),
      });
      setMessage(`Tracking saved for ${keyword.trim()}.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to save product.");
    } finally {
      setBusy(false);
    }
  }

  async function runResearch(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    const term = keyword.trim();
    if (!term) {
      setMessage("Enter a product idea first.");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const fresh = await fetchApi<MarketSnapshot>("/api/v1/sourcing/research", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ keyword: term }),
      });
      setSnapshot(fresh);
      if (!fresh.demand.available && !fresh.competition.available) {
        setMessage("Neither free source answered. Nothing was estimated.");
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to run research.");
    } finally {
      setBusy(false);
    }
  }

  function toggleSalesChannel(channel: string) {
    setProfile((current) => ({
      ...current,
      sales_channels: current.sales_channels.includes(channel)
        ? current.sales_channels.filter((item) => item !== channel)
        : [...current.sales_channels, channel],
    }));
  }

  if (view === "onboarding") {
    if (!loaded) {
      return <section className="screen" aria-live="polite"><div className="state-card">Loading onboarding…</div></section>;
    }
    const complete = currentStep?.complete ?? false;
    const total = currentStep?.total ?? 0;
    const progress = currentStep?.progress ?? 0;
    const options = currentStep?.options ?? [];
    const multiSelect = currentStep?.field === "sales_channels";
    const lastRole = chatMessages[chatMessages.length - 1]?.role;
    return (
      <section className="screen screen-chat" aria-labelledby="onboarding-title">
        <div className="chat-column">
          <header className="chat-heading">
            <div>
              <p className="eyebrow">GETTING STARTED</p>
              <h1 id="onboarding-title">Nice to meet you</h1>
              <p className="muted">A quick chat, about a minute. Type your answer or pick a suggestion.</p>
            </div>
            {!complete && total > 0 && (
              <div className="chat-progress">
                <span className="chat-progress-label">Step {Math.min(progress + 1, total)} of {total}</span>
                <div
                  className="chat-progress-track"
                  role="progressbar"
                  aria-label="Onboarding progress"
                  aria-valuemin={0}
                  aria-valuemax={total}
                  aria-valuenow={progress}
                >
                  <div className="chat-progress-fill" style={{ width: `${(progress / total) * 100}%` }} />
                </div>
              </div>
            )}
          </header>
          <div className="chat-scroll">
                <div className="chat-fade top" aria-hidden="true" />
                <div
                  className="chat-list"
                  role="log"
                  aria-live="polite"
                  aria-label={`Conversation with ${ASSISTANT}`}
                  ref={chatListRef}
                  onScroll={handleChatScroll}
                >
                  {chatMessages.map((item, index) => {
                    const grouped = chatMessages[index - 1]?.role === item.role;
                    return (
                      <div className={`chat-row ${item.role}${grouped ? " grouped" : ""}`} key={`${item.role}-${index}`}>
                        {item.role === "assistant" &&
                          (grouped
                            ? <span className="chat-avatar-spacer" aria-hidden="true" />
                            : <span className="chat-avatar" aria-hidden="true">X</span>)}
                        <div className="chat-bubble">{item.text}</div>
                      </div>
                    );
                  })}
                  {busy && (
                    <div className={`chat-row assistant${lastRole === "assistant" ? " grouped" : ""}`}>
                      <span className="chat-avatar" aria-hidden="true">X</span>
                      <div className="chat-bubble typing" role="status" aria-label={`${ASSISTANT} is typing`}>
                        <span className="typing-dots" aria-hidden="true"><i /><i /><i /></span>
                      </div>
                    </div>
                  )}
                </div>
            <div className="chat-fade bottom" aria-hidden="true" />
            {!atBottom && (
              <button
                className="jump-latest"
                type="button"
                onClick={() => { setAtBottom(true); scrollToLatest("smooth"); }}
              >
                Jump to latest
              </button>
            )}
          </div>
          {message && <p className="error-text chat-error" role="status">{message}</p>}
          {complete ? (
            <div className="onboarding-complete state-card">
              <strong>You&apos;re all set</strong>
              <p>
                {profile.product_idea
                  ? <>Your profile is saved — Market Intelligence can use <b>{profile.product_idea}</b> now.</>
                  : "Your profile is saved."}
              </p>
              <button className="primary-action" type="button" onClick={() => router.push("/research")}>Open Market Intelligence</button>
            </div>
          ) : (
              <div className="chat-composer">
                {options.length > 0 && !busy && (
                  <div className="chat-suggestions" role="group" aria-label="Suggested answers">
                    {options.map((option) =>
                      multiSelect ? (
                        <button
                          className={selectedChannels.includes(option) ? "chat-suggestion selected" : "chat-suggestion"}
                          type="button"
                          key={option}
                          aria-pressed={selectedChannels.includes(option)}
                          onClick={() => setSelectedChannels((current) => current.includes(option) ? current.filter((item) => item !== option) : [...current, option])}
                        >
                          {option}
                        </button>
                      ) : (
                        <button
                          className="chat-suggestion"
                          type="button"
                          key={option}
                          disabled={busy}
                          // "Other" means "I'll type it", so it hands over to the composer.
                          onClick={() => (option === "Other" ? composerRef.current?.focus() : void submitOnboardingAnswer(option))}
                        >
                          {option}
                        </button>
                      )
                    )}
                    {multiSelect && (
                      <button
                        className="chat-send"
                        type="button"
                        disabled={busy || selectedChannels.length === 0}
                        onClick={() => void submitOnboardingAnswer(selectedChannels.join(", "))}
                      >
                        {busy ? "Saving…" : "Send"}
                      </button>
                    )}
                  </div>
                )}
                {!multiSelect && (
                  <form
                    className="chat-composer-form"
                    onSubmit={(event) => { event.preventDefault(); void submitOnboardingAnswer(chatAnswer); }}
                  >
                    <label htmlFor="onboarding-answer" className="visually-hidden">Your answer</label>
                    <textarea
                      id="onboarding-answer"
                      name="answer"
                      rows={1}
                      ref={composerRef}
                      value={chatAnswer}
                      onChange={(event) => setChatAnswer(event.target.value)}
                      onKeyDown={(event) => {
                        // Enter sends, Shift+Enter is a new line, like every chat app.
                        if (event.key === "Enter" && !event.shiftKey) {
                          event.preventDefault();
                          void submitOnboardingAnswer(chatAnswer);
                        }
                      }}
                      inputMode={currentStep?.field === "investment_budget" ? "numeric" : "text"}
                      enterKeyHint="send"
                      placeholder="Type your message…"
                      aria-label={`Message ${ASSISTANT}`}
                      autoComplete="off"
                      autoFocus
                    />
                    <button
                      className="chat-send"
                      type="submit"
                      disabled={busy || !chatAnswer.trim()}
                      aria-label={`Send message to ${ASSISTANT}`}
                    >
                      {busy ? "Sending…" : "Send"}
                    </button>
                  </form>
                )}
              </div>
          )}
        </div>
      </section>
    );
  }

  if (view === "settings") {
    if (!loaded) {
      return <section className="screen" aria-live="polite"><div className="state-card">Loading profile…</div></section>;
    }
    return (
      <section className="screen" aria-labelledby="profile-settings-title">
        <div className="screen-heading">
          <div>
            <p className="eyebrow">ACCOUNT</p>
            <h1 id="profile-settings-title">Sourcing profile</h1>
            <p className="muted">Saved onboarding details used by Market Intelligence.</p>
          </div>
        </div>
        <form className="onboarding-form" onSubmit={saveProfile}>
          <label htmlFor="profile-business-type">Business type
            <select id="profile-business-type" name="business_type" value={profile.business_type || ""} onChange={(event) => setProfile({ ...profile, business_type: event.target.value })}>
              <option value="">Select</option>
              <option>Retail</option>
              <option>Online store</option>
              <option>Wholesale</option>
              <option>Manufacturing</option>
            </select>
          </label>
          <label htmlFor="profile-location">Location
            <input id="profile-location" name="location" value={profile.location || ""} onChange={(event) => setProfile({ ...profile, location: event.target.value })} />
          </label>
          <label htmlFor="profile-product-idea">Product idea
            <input id="profile-product-idea" name="product_idea" required value={profile.product_idea || ""} onChange={(event) => setProfile({ ...profile, product_idea: event.target.value })} />
          </label>
          <label htmlFor="profile-investment-budget">Investment budget (BDT)
            <input id="profile-investment-budget" name="investment_budget" type="number" min="0" value={profile.investment_budget ?? ""} onChange={(event) => setProfile({ ...profile, investment_budget: event.target.value ? Number(event.target.value) : undefined })} />
          </label>
          <label htmlFor="profile-team-size">Team size
            <input id="profile-team-size" name="team_size" value={profile.team_size || ""} onChange={(event) => setProfile({ ...profile, team_size: event.target.value })} />
          </label>
          <label htmlFor="profile-account-type">Account type
            <select id="profile-account-type" name="account_type" value={profile.account_type || ""} onChange={(event) => setProfile({ ...profile, account_type: event.target.value })}>
              <option value="">Select</option>
              <option>Individual</option>
              <option>Business</option>
            </select>
          </label>
          <label htmlFor="profile-experience">Experience
            <select id="profile-experience" name="experience" value={profile.experience || ""} onChange={(event) => setProfile({ ...profile, experience: event.target.value })}>
              <option value="">Select</option>
              <option>New</option>
              <option>Some experience</option>
              <option>Experienced</option>
            </select>
          </label>
          <fieldset>
            <legend>Main sales channels</legend>
            {["Website", "Facebook", "WhatsApp", "Marketplace"].map((channel) => (
              <label className="check-label" key={channel}>
                <input
                  type="checkbox"
                  name="sales_channels"
                  value={channel}
                  checked={profile.sales_channels.includes(channel)}
                  onChange={() => toggleSalesChannel(channel)}
                />
                {channel}
              </label>
            ))}
          </fieldset>
          <button className="primary-action" type="submit" disabled={busy}>{busy ? "Saving…" : "Save profile"}</button>
        </form>
        {message && <p className="error-text" role="status">{message}</p>}
      </section>
    );
  }

  if (view === "research") {
    return (
      <section className="screen" aria-labelledby="research-title">
        <div className="screen-heading">
          <div>
            <p className="eyebrow">SOURCING WORKSPACE</p>
            <h1 id="research-title">Market Intelligence</h1>
            <p className="muted">Demand, competition and BDT prices read from free public sources. Every figure shows its source and how much data stands behind it.</p>
          </div>
        </div>
        <form className="research-form" onSubmit={runResearch}>
          <label htmlFor="research-idea">Product idea
            <input
              id="research-idea"
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              placeholder="e.g. wireless earbuds"
              autoComplete="off"
            />
          </label>
          <button className="primary-action" type="submit" disabled={busy || !keyword.trim()}>
            {busy ? "Reading sources…" : "Run research"}
          </button>
        </form>
        {message && <p className="error-text" role="status">{message}</p>}
        {!loaded || busy ? (
          <div className="state-card" role="status">
            <strong>{busy ? "Reading Google Trends and Daraz Bangladesh…" : "Loading research…"}</strong>
            <p>{busy ? "A few seconds. Nothing is stored until both sources have answered or failed." : ""}</p>
          </div>
        ) : !snapshot ? (
          <div className="state-card" role="status">
            <strong>No research yet</strong>
            <p>Run research to read live Google Trends interest and current Daraz listings. Anything that cannot be measured stays blank — nothing is estimated.</p>
          </div>
        ) : (
          <div className="mi">
            <div className="mi-meta">
              <strong>{snapshot.keyword}</strong>
              <span>Captured {new Date(snapshot.captured_at).toLocaleString()}</span>
              <span className={`mi-score ${snapshot.quality.label}`} title="Weighted data quality across the three panels">
                {snapshot.quality.score}/100 quality
              </span>
              {snapshot.stale && <span className="mi-pill medium">saved snapshot</span>}
            </div>

            <div className="mi-grid">
              <article className="mi-panel" aria-labelledby="mi-demand">
                <div className="mi-panel-head">
                  <div><p className="eyebrow">DEMAND</p><h2 id="mi-demand">Demand and trends</h2></div>
                  <PanelQuality quality={snapshot.demand.quality} />
                </div>
                {snapshot.demand.available ? (
                  <>
                    <div className="mi-figures">
                      <div>
                        <span className="mi-big">{snapshot.demand.current_index ?? "—"}</span>
                        <span className="muted">Interest index, last 3 months (this idea&apos;s own peak = 100)</span>
                      </div>
                      <div>
                        <span className={`mi-big ${snapshot.demand.direction === "falling" ? "mi-down" : "mi-up"}`}>
                          {snapshot.demand.change_pct === null || snapshot.demand.change_pct === undefined
                            ? "—"
                            : `${snapshot.demand.change_pct > 0 ? "+" : ""}${snapshot.demand.change_pct}%`}
                        </span>
                        <span className="muted">{snapshot.demand.direction} vs the previous quarter</span>
                      </div>
                    </div>
                    {(snapshot.demand.series?.length ?? 0) > 1 && (
                      <Sparkline series={snapshot.demand.series ?? []} keyword={snapshot.keyword} />
                    )}
                    <dl className="mi-facts">
                      <div><dt>Seasonality</dt><dd>{seasonalityLabel(snapshot.demand)}</dd></div>
                      <div><dt>Peak months</dt><dd>{snapshot.demand.peak_months?.join(", ") || "None above average"}</dd></div>
                      <div>
                        <dt>History</dt>
                        <dd>
                          {snapshot.demand.window
                            ? `${snapshot.demand.window.from} – ${snapshot.demand.window.to} · ${snapshot.demand.window.months} months`
                            : "—"}
                        </dd>
                      </div>
                    </dl>
                    {(snapshot.demand.regions?.length ?? 0) > 0 && (
                      <div className="mi-bars">
                        {snapshot.demand.regions?.slice(0, 4).map((region) => (
                          <div className="mi-bar-row" key={region.region}>
                            <span>{region.region}</span>
                            <div className="mi-bar-track">
                              <div className="mi-bar-fill" style={{ width: `${Math.min(100, region.index)}%` }} />
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                    {(snapshot.demand.related_queries?.length ?? 0) > 0 && (
                      <div className="mi-chips">
                        {snapshot.demand.related_queries?.slice(0, 5).map((item) => (
                          <span className="mi-chip" key={item.query}>{item.query}</span>
                        ))}
                      </div>
                    )}
                  </>
                ) : (
                  <p className="muted">{snapshot.demand.reason}</p>
                )}
              </article>

              <article className="mi-panel" aria-labelledby="mi-competition">
                <div className="mi-panel-head">
                  <div><p className="eyebrow">COMPETITION</p><h2 id="mi-competition">Who is already selling</h2></div>
                  <PanelQuality quality={snapshot.competition.quality} />
                </div>
                {snapshot.competition.available ? (
                  <>
                    <div className="mi-figures">
                      <div>
                        <span className="mi-big">{snapshot.competition.seller_count ?? "—"}</span>
                        <span className="muted">distinct sellers across {snapshot.competition.listing_count ?? 0} listings</span>
                      </div>
                      <div>
                        <span className="mi-big">{snapshot.competition.established_seller_share_pct ?? "—"}%</span>
                        <span className="muted">sellers with 50+ reviews</span>
                      </div>
                    </div>
                    <dl className="mi-facts">
                      <div><dt>Density</dt><dd>{snapshot.competition.density}</dd></div>
                      <div><dt>Concentration (HHI)</dt><dd>{snapshot.competition.hhi} / 10,000</dd></div>
                      <div><dt>Biggest seller share</dt><dd>{snapshot.competition.top_seller_share_pct ?? "—"}%</dd></div>
                      <div><dt>Median reviews</dt><dd>{snapshot.competition.median_reviews ?? "—"}</dd></div>
                      <div><dt>Median rating</dt><dd>{snapshot.competition.median_rating ?? "—"}</dd></div>
                    </dl>
                  </>
                ) : (
                  <p className="muted">{snapshot.competition.reason}</p>
                )}
              </article>

              <article className="mi-panel" aria-labelledby="mi-prices">
                <div className="mi-panel-head">
                  <div><p className="eyebrow">PRICES</p><h2 id="mi-prices">Local price range</h2></div>
                  <PanelQuality quality={snapshot.prices.quality} />
                </div>
                {snapshot.prices.available ? (
                  <>
                    <div className="mi-figures">
                      <div>
                        <span className="mi-big">{formatBdt(snapshot.prices.median)}</span>
                        <span className="muted">median retail price</span>
                      </div>
                      <div>
                        <span className="mi-big">{snapshot.prices.median_discount_pct ?? "—"}%</span>
                        <span className="muted">median listed discount</span>
                      </div>
                    </div>
                    <dl className="mi-facts">
                      <div><dt>Middle half</dt><dd>{formatBdt(snapshot.prices.p25)} – {formatBdt(snapshot.prices.p75)}</dd></div>
                      <div><dt>Full range</dt><dd>{formatBdt(snapshot.prices.min)} – {formatBdt(snapshot.prices.max)}</dd></div>
                      <div>
                        <dt>Listings used</dt>
                        <dd>
                          {snapshot.prices.sample}
                          {snapshot.prices.outliers_removed ? ` · ${snapshot.prices.outliers_removed} outliers removed` : ""}
                        </dd>
                      </div>
                      <div><dt>Median units sold</dt><dd>{snapshot.prices.median_units_sold ?? "not shown"}</dd></div>
                    </dl>
                    <p className="mi-footnote">{snapshot.prices.basis}</p>
                  </>
                ) : (
                  <p className="muted">{snapshot.prices.reason}</p>
                )}
              </article>
            </div>

            <section className="mi-section" aria-labelledby="mi-risks">
              <h2 id="mi-risks">Risks</h2>
              <ul className="mi-risks">
                {snapshot.risks.map((risk) => (
                  <li key={risk.id}>
                    <span className={`mi-pill ${risk.level}`}>{risk.level === "unknown" ? "not assessed" : risk.level}</span>
                    <div>
                      <strong>{risk.label}</strong>
                      <p className="muted">{risk.detail}</p>
                    </div>
                  </li>
                ))}
              </ul>
            </section>

            <section className="mi-section" aria-labelledby="mi-sources">
              <h2 id="mi-sources">Where these numbers came from</h2>
              <ul className="mi-sources">
                {snapshot.sources.map((source) => (
                  <li key={source.id}>
                    <span className={`mi-pill ${source.status === "ok" ? "low" : "high"}`}>{source.status}</span>
                    <div>
                      <a href={source.url} target="_blank" rel="noreferrer">{source.label}</a>
                      <p className="muted">{source.detail}</p>
                    </div>
                  </li>
                ))}
              </ul>
              <p className="mi-footnote">{snapshot.method}</p>
            </section>

            <div className="dashboard-actions">
              <button className="primary-action" type="button" onClick={() => router.push("/research/products")}>
                Continue to Products
              </button>
              <button className="secondary-action" type="button" onClick={() => void runResearch()} disabled={busy}>
                Run again
              </button>
            </div>
          </div>
        )}
      </section>
    );
  }

  if (view === "products") {
    return (
      <section className="screen" aria-labelledby="products-title">
        <div className="screen-heading"><div><p className="eyebrow">SOURCING WORKSPACE</p><h1 id="products-title">Product Search</h1></div></div>
        <form className="research-form" onSubmit={trackProduct}>
          <label htmlFor="product-keyword">Search keyword<input id="product-keyword" required value={keyword} onChange={(event) => setKeyword(event.target.value)} /></label>
          <button className="primary-action" type="submit" disabled={busy}>{busy ? "Saving…" : "Track product"}</button>
        </form>
        <div className="state-card" role="status"><strong>Supplier search unavailable</strong><p>Connect an approved supplier provider before listings can be compared.</p></div>
        {message && <p className="error-text" role="status">{message}</p>}
      </section>
    );
  }

  return (
    <section className="screen" aria-labelledby="cart-title">
      <div className="screen-heading"><div><p className="eyebrow">SOURCING WORKSPACE</p><h1 id="cart-title">Cart</h1></div></div>
      {cart.length === 0 ? <div className="state-card" role="status"><strong>No saved listings</strong><p>Listings from approved supplier search will appear here.</p></div> : <div className="dashboard-grid">{cart.map((listing) => <article className="dashboard-stat" key={listing.id}><strong>{listing.title}</strong><span className="muted">{listing.marketplace}</span><span>{listing.unit_price === null ? "Price unavailable" : `${listing.currency} ${listing.unit_price}`}</span></article>)}</div>}
      {message && <p className="error-text" role="alert">{message}</p>}
    </section>
  );
}

function formatBdt(value?: number | null): string {
  if (value === null || value === undefined) return "—";
  return `৳ ${Math.round(value).toLocaleString("en-US")}`;
}

function seasonalityLabel(demand: MarketSnapshot["demand"]): string {
  if (!demand.seasonality) return "Not measured";
  const { label, ratio } = demand.seasonality;
  return ratio ? `${label} · peak ${ratio.toFixed(2)}× the average month` : label;
}

function PanelQuality({ quality }: { quality: Quality }) {
  return (
    <span className={`mi-score ${quality.label}`} title={quality.reasons?.join(" ") ?? `Data quality ${quality.score}/100`}>
      {quality.score}/100
    </span>
  );
}

function Sparkline({ series, keyword }: { series: { month: string; index: number }[]; keyword: string }) {
  const width = 320;
  const height = 76;
  const peak = Math.max(...series.map((point) => point.index), 1);
  const step = series.length > 1 ? width / (series.length - 1) : width;
  const points = series
    .map((point, index) => {
      const x = index * step;
      const y = height - 4 - (point.index / peak) * (height - 10);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const first = series[0]?.month ?? "";
  const last = series[series.length - 1]?.month ?? "";
  return (
    <figure className="mi-spark">
      <svg
        className="mi-sparkline"
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`Monthly Google Trends interest for ${keyword}, ${first} to ${last}, where the peak month is 100`}
      >
        <polyline points={points} />
      </svg>
      <figcaption>{first} → {last} · peak month = 100</figcaption>
    </figure>
  );
}
