"use client";

import { useState } from "react";

export default function FarmEnterPage() {
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const res = await fetch("/api/farm/enter", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    });
    setBusy(false);
    if (!res.ok) {
      setError("That password does not match.");
      return;
    }
    const next = new URLSearchParams(window.location.search).get("next") || "/farm";
    window.location.href = next.startsWith("/") && !next.startsWith("//") ? next : "/farm";
  }

  return (
    <main className="shell identity-shell">
      <div className="atmosphere" aria-hidden="true" />
      <header className="top">
        <p className="tag">Farm</p>
        <h1 className="identity-ask">Enter the farm password.</h1>
        <p className="identity-note">Solo labeling for ohush.co/farm. Same code as your lab, or OHUSH_FARM_CODE.</p>
      </header>
      <form className="identity-card" onSubmit={submit}>
        <label className="identity-said" style={{ display: "flex", flexDirection: "column" }}>
          Password
          <input
            className="phone-code"
            type="password"
            value={code}
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            autoComplete="current-password"
            onChange={(event) => setCode(event.target.value)}
          />
        </label>
        <button type="submit" className="arrow-btn finish" disabled={busy || code.trim().length === 0}>
          Open farm
        </button>
        {error ? <p className="device">{error}</p> : null}
      </form>
    </main>
  );
}
