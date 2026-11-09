"use client";

import { useState } from "react";

export default function PhoneEnterPage() {
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const res = await fetch("/api/phone/enter", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    });
    setBusy(false);
    if (!res.ok) {
      setError("That code is not the one on this computer.");
      return;
    }
    const next = new URLSearchParams(window.location.search).get("next") || "/phone";
    window.location.href = next.startsWith("/") && !next.startsWith("//") ? next : "/phone";
  }

  return (
    <main className="shell identity-shell">
      <div className="atmosphere" aria-hidden="true" />
      <header className="top">
        <p className="tag">Phone</p>
        <h1 className="identity-ask">Enter the code from the computer.</h1>
        <p className="identity-note">This computer has to stay on. The code stays on this phone after that.</p>
      </header>
      <form className="identity-card" onSubmit={submit}>
        <label className="identity-said" style={{ display: "flex", flexDirection: "column" }}>
          Code
          <input
            className="phone-code"
            value={code}
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            inputMode="text"
            onChange={(event) => setCode(event.target.value)}
          />
        </label>
        <button type="submit" className="arrow-btn finish" disabled={busy || code.trim().length === 0}>
          Open the labeler
        </button>
        {error ? <p className="device">{error}</p> : null}
      </form>
    </main>
  );
}
