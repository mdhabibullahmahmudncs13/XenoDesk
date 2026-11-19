"use client";

import { FormEvent, useState } from "react";
import { setAccessToken } from "../lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8001";

export function SignupForm() {
  const [values, setValues] = useState({ business_name: "", name: "", email: "", password: "" });
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [emailTouched, setEmailTouched] = useState(false);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const emailInvalid = emailTouched && !values.email.includes("@");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(`${API_BASE}/api/v1/auth/signup`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(values),
      });
      if (!response.ok) {
        const detail = (await response.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(detail?.detail ?? "Unable to create the account.");
      }
      const data = (await response.json()) as { access_token: string };
      setAccessToken(data.access_token);
      window.location.assign("/dashboard");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to create the account.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="auth-card" aria-labelledby="signup-title">
      <p className="eyebrow">XENOVARIENTS</p>
      <h1 id="signup-title">Create your workspace</h1>
      <p className="muted">The account creator becomes the business owner.</p>
      <form onSubmit={submit} className="auth-form">
        <label htmlFor="signup-business">Business name</label>
        <input id="signup-business" name="organization" required autoComplete="organization" value={values.business_name} onChange={(event) => setValues({ ...values, business_name: event.target.value })} />
        <label htmlFor="signup-name">Your name</label>
        <input id="signup-name" name="name" required autoComplete="name" value={values.name} onChange={(event) => setValues({ ...values, name: event.target.value })} />
        <label htmlFor="signup-email">Email</label>
        <input
          id="signup-email"
          name="email"
          required
          autoComplete="username"
          spellCheck={false}
          type="email"
          value={values.email}
          aria-invalid={emailInvalid}
          onBlur={() => setEmailTouched(true)}
          onChange={(event) => setValues({ ...values, email: event.target.value })}
        />
        <label htmlFor="signup-password">Password</label>
        <div className="password-field">
          <input
            id="signup-password"
            name="password"
            required
            autoComplete="new-password"
            minLength={8}
            type={passwordVisible ? "text" : "password"}
            value={values.password}
            onChange={(event) => setValues({ ...values, password: event.target.value })}
          />
          <button
            className="password-toggle"
            type="button"
            aria-pressed={passwordVisible}
            onClick={() => setPasswordVisible((visible) => !visible)}
          >
            {passwordVisible ? "Hide" : "Show"}
          </button>
        </div>
        <button disabled={busy} type="submit">{busy ? "Creating…" : "Create workspace"}</button>
      </form>
      {message && <p className="error-text" role="alert">{message}</p>}
    </section>
  );
}
