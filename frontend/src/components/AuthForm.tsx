"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { setAccessToken } from "../lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8001";

export function AuthForm() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [emailTouched, setEmailTouched] = useState(false);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const emailInvalid = emailTouched && !email.includes("@");

  useEffect(() => {
    const isLocalHost =
      window.location.hostname === "localhost" ||
      window.location.hostname === "127.0.0.1";
    if (isLocalHost) {
      setEmail("test.user@example.com");
      setPassword("TestUser123!");
    }
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(`${API_BASE}/api/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { detail?: string; code?: string } | null;
        if (response.status === 503 || body?.code === "unavailable") {
          throw new Error("The API database is unavailable. Start PostgreSQL and try again.");
        }
        if (response.status === 429) {
          throw new Error("Too many sign-in attempts. Wait a moment and try again.");
        }
        throw new Error(body?.detail || "Incorrect email or password.");
      }
      const data = (await response.json()) as { access_token: string };
      setAccessToken(data.access_token);
      window.location.assign("/dashboard");
    } catch (error) {
      if (error instanceof TypeError) {
        setMessage("Can't reach the server. Check your connection and try again.");
      } else {
        setMessage(error instanceof Error ? error.message : "Unable to sign in.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-card" aria-labelledby="login-title">
        <p className="eyebrow">XENODESK</p>
        <h1 id="login-title">Sign in</h1>
        <p className="muted">Use your business account to access the workspace.</p>
        <form onSubmit={submit} className="auth-form" aria-busy={busy}>
          <div className="auth-field">
            <label htmlFor="login-email">Email</label>
            <input
              id="login-email"
              name="email"
              required
              autoComplete="email"
              inputMode="email"
              spellCheck={false}
              type="email"
              value={email}
              aria-invalid={emailInvalid}
              aria-describedby={message ? "login-error" : undefined}
              onBlur={() => setEmailTouched(true)}
              onChange={(event) => setEmail(event.target.value)}
            />
          </div>
          <div className="auth-field">
            <label htmlFor="login-password">Password</label>
            <div className="password-field">
              <input
                id="login-password"
                name="password"
                required
                autoComplete="current-password"
                minLength={8}
                type={passwordVisible ? "text" : "password"}
                value={password}
                aria-describedby={message ? "login-error" : undefined}
                onChange={(event) => setPassword(event.target.value)}
              />
              <button
                className="auth-toggle"
                type="button"
                aria-pressed={passwordVisible}
                aria-label={passwordVisible ? "Hide password" : "Show password"}
                onClick={() => setPasswordVisible((visible) => !visible)}
              >
                {passwordVisible ? "Hide" : "Show"}
              </button>
            </div>
            <div className="auth-error-slot">
              {message && (
                <p className="auth-error" id="login-error" role="alert">
                  {message}
                </p>
              )}
            </div>
          </div>
          <button className="auth-submit" disabled={busy} type="submit">
            {busy && <span className="auth-spinner" aria-hidden="true" />}
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="auth-switch">New here? <Link href="/signup">Create a workspace</Link></p>
      </section>
    </main>
  );
}
