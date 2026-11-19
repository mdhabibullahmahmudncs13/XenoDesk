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
        throw new Error(body?.detail || "Incorrect email or password.");
      }
      const data = (await response.json()) as { access_token: string };
      setAccessToken(data.access_token);
      window.location.assign("/dashboard");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to sign in.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="auth-card" aria-labelledby="login-title">
      <p className="eyebrow">XENOVARIENTS</p>
      <h1 id="login-title">Sign in</h1>
      <p className="muted">Use your business account to access the workspace.</p>
      <form onSubmit={submit} className="auth-form">
        <label>
          Email
          <input
            id="login-email"
            name="email"
            required
            autoComplete="username"
            spellCheck={false}
            type="email"
            value={email}
            aria-invalid={emailInvalid}
            onBlur={() => setEmailTouched(true)}
            onChange={(event) => setEmail(event.target.value)}
          />
        </label>
        <label htmlFor="login-password">
          Password
        </label>
        <div className="password-field">
          <input
            id="login-password"
            name="password"
            required
            autoComplete="current-password"
            minLength={8}
            type={passwordVisible ? "text" : "password"}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
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
        <button disabled={busy} type="submit">{busy ? "Signing in…" : "Sign in"}</button>
      </form>
      {message && <p className="error-text" role="alert">{message}</p>}
      <p className="auth-switch">New here? <Link href="/signup">Create a workspace</Link></p>
    </section>
  );
}
