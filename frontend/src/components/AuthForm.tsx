"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { setAccessToken } from "../lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export function AuthForm() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

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
      if (!response.ok) throw new Error("Incorrect email or password.");
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
          <input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} />
        </label>
        <label>
          Password
          <input required minLength={8} type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
        </label>
        <button disabled={busy} type="submit">{busy ? "Signing in…" : "Sign in"}</button>
      </form>
      {message && <p className="error-text" role="alert">{message}</p>}
      <p className="auth-switch">New here? <Link href="/signup">Create a workspace</Link></p>
    </section>
  );
}
