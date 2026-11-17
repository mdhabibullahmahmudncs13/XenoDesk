"use client";

import { FormEvent, useEffect, useState } from "react";
import { fetchApi } from "../lib/api";

type Answer = { answer: string; answer_type: string; data_as_of: string; usage: { estimated_cost?: number } };

export function Chat() {
  const [sessionId, setSessionId] = useState("");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchApi<{ id: string }>("/api/v1/agent-workspace/sessions")
      .then((session) => setSessionId(session.id))
      .catch((reason: Error) => setError(reason.message));
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!sessionId || !question.trim()) return;
    setBusy(true);
    setError("");
    try {
      const result = await fetchApi<Answer>(`/api/v1/agent-workspace/sessions/${sessionId}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: question }),
      });
      setAnswer(result);
      setQuestion("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to send message.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="screen" aria-labelledby="chat-title">
      <p className="eyebrow">AGENT WORKSPACE</p>
      <h1 id="chat-title">Chat</h1>
      <p className="muted">Ask questions about your business. The agent cannot make changes or send messages.</p>
      <form className="chat-form" onSubmit={submit}>
        <label htmlFor="question">Question</label>
        <textarea id="question" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="How many active ads do we have?" required />
        <button type="submit" disabled={busy || !sessionId}>{busy ? "Checking…" : "Ask"}</button>
      </form>
      {error && <div className="state-card error" role="alert">{error}</div>}
      {answer && <article className="data-card chat-answer"><div className="card-header"><strong>{answer.answer_type}</strong><span className="chip">Cost: {answer.usage.estimated_cost ?? 0}</span></div><p>{answer.answer}</p><small className="muted">Data as of {new Date(answer.data_as_of).toLocaleString()}</small></article>}
    </section>
  );
}
