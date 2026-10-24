"use client";

import { useEffect, useRef, useState } from "react";
import { WaveTransport } from "@/components/WaveTransport";

type Clip = {
  id: string;
  session: string;
  play_start: number;
  duration: number;
  mark_s?: number;
  caption?: string;
};

type State = {
  name: string;
  mcus: number;
  done: number;
  total: number;
  clip: Clip | null;
};

const PUBLIC = process.env.NEXT_PUBLIC_OHUSH_PUBLIC_SITE === "1";

function firebaseConfig() {
  return {
    apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
    authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
    projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
    appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
  };
}

async function firebaseAuth() {
  const { getApp, getApps, initializeApp } = await import("firebase/app");
  const { getAuth } = await import("firebase/auth");
  const app = getApps().length ? getApp() : initializeApp(firebaseConfig());
  return getAuth(app);
}

function draw(canvas: HTMLCanvasElement, audio: AudioBuffer, mark: number | null) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const data = audio.getChannelData(0);
  const width = canvas.width;
  const height = canvas.height;
  ctx.fillStyle = "#1a1024";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "#d7c6f5";
  ctx.beginPath();
  const step = Math.max(1, Math.floor(data.length / width));
  for (let x = 0; x < width; x += 1) {
    let min = 1;
    let max = -1;
    const start = x * step;
    for (let i = 0; i < step; i += 1) {
      const sample = data[start + i] ?? 0;
      if (sample < min) min = sample;
      if (sample > max) max = sample;
    }
    ctx.moveTo(x, (1 - max) * 0.5 * height);
    ctx.lineTo(x, (1 - min) * 0.5 * height);
  }
  ctx.stroke();
  if (mark != null && audio.duration > 0) {
    const x = Math.round((mark / audio.duration) * width);
    ctx.strokeStyle = "#7dffb3";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();
  }
}

export function CrowdRoom() {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [linkSent, setLinkSent] = useState(false);
  const [linkPending, setLinkPending] = useState(false);
  const [named, setNamed] = useState(false);
  const [state, setState] = useState<State | null>(null);
  const [note, setNote] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    const res = await fetch("/api/crowd");
    if (res.status === 401) {
      setNamed(false);
      return;
    }
    setNamed(true);
    setState((await res.json()) as State);
  }

  useEffect(() => {
    void (async () => {
      if (PUBLIC && typeof window !== "undefined") {
        try {
          const { isSignInWithEmailLink, signInWithEmailLink } = await import("firebase/auth");
          const auth = await firebaseAuth();
          if (isSignInWithEmailLink(auth, window.location.href)) {
            const saved = window.localStorage.getItem("ohush_email") || "";
            if (!saved) {
              setLinkPending(true);
              setError("Enter the same email to finish signing in.");
            } else {
              const cred = await signInWithEmailLink(auth, saved, window.location.href);
              const idToken = await cred.user.getIdToken();
              await fetch("/api/crowd/session", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ idToken }),
              });
              window.history.replaceState({}, "", "/crowd");
            }
          }
        } catch {
          setError("That sign-in link did not work. Ask for a new one.");
        }
      }
      await load();
    })();
  }, []);

  async function sendLink(event: React.FormEvent) {
    event.preventDefault();
    const address = email.trim();
    setBusy(true);
    setError("");
    try {
      if (linkPending) {
        const { signInWithEmailLink } = await import("firebase/auth");
        const cred = await signInWithEmailLink(await firebaseAuth(), address, window.location.href);
        const idToken = await cred.user.getIdToken();
        const res = await fetch("/api/crowd/session", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ idToken }),
        });
        if (!res.ok) throw new Error("session");
        window.localStorage.setItem("ohush_email", address);
        window.history.replaceState({}, "", "/crowd");
        setLinkPending(false);
        await load();
      } else {
        const { sendSignInLinkToEmail } = await import("firebase/auth");
        await sendSignInLinkToEmail(await firebaseAuth(), address, {
          url: "https://hush--hushdev.us-east4.hosted.app/crowd",
          handleCodeInApp: true,
        });
        window.localStorage.setItem("ohush_email", address);
        setLinkSent(true);
      }
    } catch {
      setError(linkPending ? "That email does not match the link." : "That email did not send. Try again.");
    }
    setBusy(false);
  }

  async function signOutHere() {
    await fetch("/api/crowd/session", { method: "DELETE" });
    if (PUBLIC) {
      const { signOut } = await import("firebase/auth");
      await signOut(await firebaseAuth());
    }
    setNamed(false);
    setState(null);
    setMessage("");
  }

  async function signIn(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const res = await fetch("/api/crowd/name", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    setBusy(false);
    if (!res.ok) {
      setError("Use your name, up to 24 letters.");
      return;
    }
    await load();
  }

  async function choose(action: "on" | "off") {
    if (!state?.clip || busy) return;
    setBusy(true);
    setError("");
    const res = await fetch("/api/crowd", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: state.clip.id, action, note }),
    });
    const body = (await res.json().catch(() => ({}))) as { status?: string; mcus?: number; error?: string };
    setBusy(false);
    if (!res.ok) {
      setError(body.error || "That one did not save.");
      return;
    }
    setNote("");
    setMessage(
      body.status === "matched"
        ? `Matched. You have ${body.mcus} MCU${body.mcus === 1 ? "" : "s"}.`
        : body.status === "split"
          ? "Saved. Someone heard it the other way, so this clip pays no MCU."
          : "Saved. An MCU is paid when someone else hears it the same way.",
    );
    await load();
  }

  if (!named) {
    return (
      <main className="shell identity-shell">
        <div className="atmosphere" aria-hidden="true" />
        <header className="top">
          <p className="tag">Crowd</p>
          <h1 className="identity-ask">{PUBLIC ? "Sign in" : "Your name"}</h1>
          <p className="identity-note">An MCU is paid only when another person, who never sees your answer, chooses the same thing.</p>
        </header>
        {PUBLIC ? (
          <form className="identity-card" onSubmit={sendLink}>
            <label className="identity-said" style={{ display: "flex", flexDirection: "column" }}>
              Email
              <input
                className="phone-code"
                type="email"
                autoComplete="email"
                inputMode="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                style={{ fontSize: 16, minHeight: "3rem" }}
              />
            </label>
            <button type="submit" className="arrow-btn finish" disabled={busy || email.trim().length === 0}>
              {linkPending ? "Finish sign-in" : "Email me a link"}
            </button>
            {linkSent ? <p className="identity-note">Check your email and open the link on this device.</p> : null}
            {error ? <p className="device">{error}</p> : null}
          </form>
        ) : null}
        {PUBLIC ? null : (
        <form className="identity-card" onSubmit={signIn}>
          <label className="identity-said" style={{ display: "flex", flexDirection: "column" }}>
            Name
            <input className="phone-code" value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <button type="submit" className="arrow-btn finish" disabled={busy || name.trim().length === 0}>
            Start
          </button>
          {error ? <p className="device">{error}</p> : null}
        </form>
        )}
      </main>
    );
  }

  const clip = state?.clip;
  return (
    <main className="shell identity-shell">
      <div className="atmosphere" aria-hidden="true" />
      <header className="top">
        <p className="tag">
          {state?.name} · {state?.mcus ?? 0} MCU{(state?.mcus ?? 0) === 1 ? "" : "s"} · {state?.done ?? 0} of {state?.total ?? 0}
          {PUBLIC ? (
            <>
              {" "}
              ·{" "}
              <button type="button" onClick={() => void signOutHere()} style={{ background: "none", border: 0, color: "inherit", cursor: "pointer", font: "inherit" }}>
                Sign out
              </button>
            </>
          ) : null}
        </p>
        <h1 className="identity-ask">Would you leave this on?</h1>
        {clip?.caption ? <p className="identity-note">{clip.caption}</p> : null}
      </header>
      {message ? <p className="identity-note">{message}</p> : null}
      {clip ? (
        <section className="identity-card">
          <WaveTransport
            src={
              PUBLIC
                ? `/api/crowd/audio?id=${encodeURIComponent(clip.id)}`
                : `/api/audio?session=${encodeURIComponent(clip.session)}&mode=timeline&start=${clip.play_start}&duration=${clip.duration}`
            }
            audioRef={audioRef}
            canvasRef={canvasRef}
            loop={{ start_s: 0, end_s: clip.duration }}
            loopByDefault
            onDecoded={(buffer) => {
              const canvas = canvasRef.current;
              if (canvas) draw(canvas, buffer, clip.mark_s ?? null);
            }}
          />
          <label className="identity-said" style={{ display: "flex", flexDirection: "column" }}>
            What it is
            <input className="phone-code" value={note} placeholder="Optional" onChange={(event) => setNote(event.target.value)} />
          </label>
          <div className="identity-choices">
            <button type="button" disabled={busy} onClick={() => void choose("on")}>
              Leave this on
            </button>
            <button type="button" disabled={busy} onClick={() => void choose("off")}>
              This left the show
            </button>
          </div>
          {error ? <p className="device">{error}</p> : null}
        </section>
      ) : (
        <p className="identity-note">You have heard every clip in this pile. MCUs still change if a later person agrees or disagrees.</p>
      )}
    </main>
  );
}
