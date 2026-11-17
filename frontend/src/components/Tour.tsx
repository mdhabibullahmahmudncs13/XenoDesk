"use client";

import { useEffect, useState } from "react";
import { fetchApi } from "../lib/api";

type Step = { id: string; step_order: number; target_id: string; message: string };

export function Tour() {
  const [steps, setSteps] = useState<Step[]>([]);
  const [current, setCurrent] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchApi<Step[]>("/api/v1/agent-workspace/tours/steps")
      .then(setSteps)
      .catch((reason: Error) => setError(reason.message));
  }, []);

  async function update(state: "in_progress" | "completed") {
    try {
      await fetchApi("/api/v1/agent-workspace/tours/progress", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ state, current_step: current + 1 }),
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to save tour progress.");
    }
  }

  const step = steps[current];
  return (
    <section className="screen" aria-labelledby="tour-title">
      <p className="eyebrow">AGENT WORKSPACE</p>
      <h1 id="tour-title">Product tour</h1>
      {error && <div className="state-card error" role="alert">{error}</div>}
      {!step ? (
        <div className="state-card empty" role="status"><strong>No active tour steps</strong><p>Tour steps configured by an administrator appear here.</p></div>
      ) : (
        <article className="data-card tour-card">
          <span className="chip">Step {current + 1} of {steps.length}</span>
          <h2>{step.target_id}</h2>
          <p>{step.message}</p>
          <div className="bubble-actions">
            <button type="button" disabled={current === 0} onClick={() => setCurrent((value) => value - 1)}>Back</button>
            {current < steps.length - 1
              ? <button type="button" onClick={() => { setCurrent((value) => value + 1); void update("in_progress"); }}>Next</button>
              : <button type="button" onClick={() => void update("completed")}>Finish</button>}
          </div>
        </article>
      )}
    </section>
  );
}
