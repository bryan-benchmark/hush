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
  const [named, setNamed] = useState(false);
  const [state, setState] = useState<State | null>(null);
  const [note, setNote] = useState("");
  const [noteOpen, setNoteOpen] = useState(false);
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

  async function openSession(user: { getIdToken: () => Promise<string> }) {
    const idToken = await user.getIdToken();
    const res = await fetch("/api/crowd/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ idToken }),
    });
    if (!res.ok) throw new Error("session");
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
              setError("Enter the same email, then sign in again.");
            } else {
              const cred = await signInWithEmailLink(auth, saved, window.location.href);
              await openSession(cred.user);
              window.history.replaceState({}, "", "/crowd");
            }
          }
        } catch {
          setError("That sign-in did not finish. Try again.");
        }
      }
      await load();
    })();
  }, []);

  async function signInAccount(event: React.FormEvent) {
    event.preventDefault();
    const address = email.trim();
    setBusy(true);
    setError("");
    try {
      const { sendSignInLinkToEmail } = await import("firebase/auth");
      await sendSignInLinkToEmail(await firebaseAuth(), address, {
        url: "https://hush--hushdev.us-east4.hosted.app/crowd",
        handleCodeInApp: true,
      });
      window.localStorage.setItem("ohush_email", address);
      setLinkSent(true);
    } catch {
      setError("That sign-in did not send. Try again.");
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
    setNoteOpen(false);
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
      <main className="crowd">
        <div className="atmosphere" aria-hidden="true" />
        <form className="crowd-gate" onSubmit={PUBLIC ? signInAccount : signIn}>
          <h1 className="crowd-ask">{PUBLIC ? "Sign in" : "Your name"}</h1>
          <p className="crowd-caption">{PUBLIC ? "We'll email you a link." : "This name is how this computer keeps your MCUs."}</p>
          {PUBLIC ? (
            <input
              className="crowd-field"
              type="email"
              autoComplete="email"
              inputMode="email"
              enterKeyHint="go"
              aria-label="Email"
              placeholder="Email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          ) : (
            <input
              className="crowd-field"
              aria-label="Name"
              placeholder="Name"
              autoComplete="name"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          )}
          <button
            type="submit"
            className="crowd-choice keep"
            disabled={busy || (PUBLIC ? email.trim().length === 0 : name.trim().length === 0)}
          >
            {PUBLIC ? "Sign in" : "Start"}
          </button>
          {linkSent ? <p className="crowd-status">Check your email to finish signing in.</p> : null}
          {error ? <p className="crowd-error">{error}</p> : null}
          <p className="crowd-fine">An MCU is paid when another person, who never sees your answer, chooses the same thing.</p>
        </form>
      </main>
    );
  }

  const clip = state?.clip;
  return (
    <main className="crowd">
      <div className="atmosphere" aria-hidden="true" />
      <header className="crowd-top">
        <span>
          {state?.done ?? 0} of {state?.total ?? 0}
        </span>
        <span>
          {state?.mcus ?? 0} MCU{(state?.mcus ?? 0) === 1 ? "" : "s"}
        </span>
        {PUBLIC ? (
          <button type="button" className="crowd-quiet" onClick={() => void signOutHere()}>
            Sign out
          </button>
        ) : (
          <span>{state?.name}</span>
        )}
      </header>
      {clip ? (
        <div className="crowd-main">
          <h1 className="crowd-ask">Would you leave this on?</h1>
          {clip.caption ? <p className="crowd-caption">{clip.caption}</p> : <p className="crowd-caption" />}
          <div className="crowd-wave">
            <WaveTransport
              plain
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
          </div>
          <p className="crowd-status" aria-live="polite">
            {message || error}
          </p>
          <div className="crowd-actions">
            {noteOpen ? (
              <input
                className="crowd-field crowd-note-field"
                aria-label="What it is"
                placeholder="What it is"
                value={note}
                onChange={(event) => setNote(event.target.value)}
              />
            ) : (
              <button type="button" className="crowd-note-toggle" onClick={() => setNoteOpen(true)}>
                Add a note
              </button>
            )}
            <button type="button" className="crowd-choice keep" disabled={busy} onClick={() => void choose("on")}>
              Leave this on
            </button>
            <button type="button" className="crowd-choice leave" disabled={busy} onClick={() => void choose("off")}>
              This left the show
            </button>
          </div>
        </div>
      ) : (
        <p className="crowd-done">You have heard every clip in this pile. MCUs still change if a later person agrees or disagrees.</p>
      )}
    </main>
  );
}
