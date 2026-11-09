"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { WaveTransport } from "@/components/WaveTransport";

type Draft = {
  kind?: string;
  phase?: string;
  setting?: string;
  speaker?: string;
  bucket?: string;
  note?: string;
  confidence?: string;
  ask?: string;
};

type Saved = {
  bucket: string;
  kind: string;
  phase: string;
  setting: string;
  speaker: string;
  note: string;
  saved_at: string;
};

type Item = {
  id: string;
  session: string;
  play_start: number;
  duration: number;
  t0: number;
  t1: number;
  why: string;
  caption: string;
  rank: number;
  priority: number;
  draft: Draft | null;
  saved: Saved | null;
};

const BUCKETS = [
  { id: "broadcast", label: "Broadcast" },
  { id: "non_broadcast", label: "Commercial" },
  { id: "unsure", label: "Unsure" },
] as const;

const KINDS = [
  "studio_desk",
  "injury_desk",
  "sideline_report",
  "booth",
  "highlights",
  "feature_package",
  "halftime_desk",
  "pregame_desk",
  "postgame_desk",
  "host_bridge",
  "in_show_sponsorship",
  "show_return",
  "dry_vo",
  "music_bed_ad",
  "live_host_read",
  "unknown",
] as const;

const PHASES = [
  "pregame",
  "Q1",
  "Q2",
  "halftime",
  "Q3",
  "Q4",
  "postgame",
  "unknown",
  "n/a",
] as const;

const SETTINGS = [
  "studio_desk",
  "sideline_or_remote",
  "booth_only",
  "package",
  "spot",
  "mixed",
  "unknown",
] as const;

function drawPlain(canvas: HTMLCanvasElement, audio: AudioBuffer) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const data = audio.getChannelData(0);
  const width = canvas.width;
  const height = canvas.height;
  let peak = 0;
  for (let i = 0; i < data.length; i += 8) {
    const sample = Math.abs(data[i]);
    if (sample > peak) peak = sample;
  }
  const gain = peak > 0.001 ? 0.92 / peak : 1;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#1a1024";
  ctx.fillRect(0, 0, width, height);
  // mark core span (excluding pad) roughly via CSS note — paint mid band hint
  ctx.fillStyle = "#f2c14e22";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "#d7c6f5";
  ctx.beginPath();
  const step = Math.max(1, Math.floor(data.length / width));
  for (let x = 0; x < width; x += 1) {
    let min = 1;
    let max = -1;
    const start = x * step;
    for (let i = 0; i < step; i += 1) {
      const sample = Math.max(-1, Math.min(1, (data[start + i] ?? 0) * gain));
      if (sample < min) min = sample;
      if (sample > max) max = sample;
    }
    ctx.moveTo(x, (1 - max) * 0.5 * height);
    ctx.lineTo(x, (1 - min) * 0.5 * height);
  }
  ctx.stroke();
}

export function DeepLabelApp() {
  const [items, setItems] = useState<Item[]>([]);
  const [index, setIndex] = useState(0);
  const [instructions, setInstructions] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [finished, setFinished] = useState(false);
  const [showHint, setShowHint] = useState(true);

  const [bucket, setBucket] = useState("");
  const [kind, setKind] = useState("");
  const [phase, setPhase] = useState("");
  const [setting, setSetting] = useState("");
  const [speaker, setSpeaker] = useState("");
  const [note, setNote] = useState("");

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const decodedRef = useRef<AudioBuffer | null>(null);

  useEffect(() => {
    fetch("/api/deep-label")
      .then((res) => res.json())
      .then((data) => {
        const next = (data.items ?? []) as Item[];
        setItems(next);
        setInstructions(String(data.instructions || ""));
        const first = next.findIndex((item) => !item.saved);
        setIndex(first >= 0 ? first : 0);
        if (next.length && next.every((item) => item.saved)) setFinished(true);
      })
      .catch(() => setError("Could not load the deep-label queue."));
  }, []);

  const item = items[index];
  const savedCount = items.filter((row) => row.saved).length;

  useEffect(() => {
    if (!item) return;
    const seed = item.saved ?? (showHint ? item.draft : null);
    setBucket(seed?.bucket || "");
    setKind(seed?.kind || "");
    setPhase(seed?.phase || "");
    setSetting(seed?.setting || "");
    setSpeaker(seed?.speaker || "");
    setNote(seed?.note || "");
    setError("");
    decodedRef.current = null;
  }, [item, showHint]);

  async function save() {
    if (!item) return;
    if (!bucket || !kind) {
      setError("Pick bucket and kind.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const res = await fetch("/api/deep-label", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: item.id,
          bucket,
          kind,
          phase,
          setting,
          speaker,
          note,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(String(data.error || "Save failed"));
        setSaving(false);
        return;
      }
      const saved: Saved = {
        bucket,
        kind,
        phase,
        setting,
        speaker,
        note,
        saved_at: new Date().toISOString(),
      };
      setItems((prev) => prev.map((row) => (row.id === item.id ? { ...row, saved } : row)));
      setSaving(false);
      if (index >= items.length - 1) {
        setFinished(true);
        return;
      }
      setIndex((n) => n + 1);
    } catch {
      setError("Save failed.");
      setSaving(false);
    }
  }

  if (finished) {
    return (
      <main className="shell identity-shell">
        <div className="atmosphere" aria-hidden="true" />
        <header className="top">
          <p className="tag">Deep label · broadcast vs commercial</p>
          <h1 className="identity-ask">That’s the queue.</h1>
          <p className="identity-note">
            {savedCount} of {items.length} clips saved to BROADCAST_DEEP_LABEL_001.
          </p>
        </header>
        <div className="clip-nav">
          <button
            type="button"
            className="arrow-btn finish"
            onClick={() => {
              setFinished(false);
              const first = items.findIndex((row) => !row.saved);
              setIndex(first >= 0 ? first : 0);
            }}
          >
            Back to clips
          </button>
          <Link className="tag" href="/review">
            Other labelers
          </Link>
        </div>
      </main>
    );
  }

  return (
    <main className="shell identity-shell">
      <div className="atmosphere" aria-hidden="true" />
      <header className="top">
        <p className="tag">
          Deep label · broadcast vs commercial
          {items.length ? ` · ${index + 1} of ${items.length}` : ""}
          {items.length ? ` · ${savedCount} saved` : ""}
        </p>
        <h1 className="identity-ask">What is this stretch?</h1>
        {item ? <p className="identity-note">{item.why}</p> : null}
        {instructions ? <p className="identity-note">{instructions}</p> : null}
      </header>

      {item ? (
        <section className="identity-card" style={{ display: "flex", flexDirection: "column", gap: "0.85rem" }}>
          <p className="identity-note" style={{ margin: 0 }}>
            Core {item.t0.toFixed(1)}–{item.t1.toFixed(1)}s · pad ±1.5s · {item.session}
          </p>
          <WaveTransport
            src={`/api/audio?session=${encodeURIComponent(item.session)}&mode=timeline&start=${item.play_start}&duration=${item.duration}`}
            audioRef={audioRef}
            canvasRef={canvasRef}
            loop={{ start_s: 0, end_s: item.duration }}
            loopByDefault
            plain
            waveHeight={180}
            volumeControl
            onDecoded={(buffer) => {
              decodedRef.current = buffer;
              const canvas = canvasRef.current;
              if (canvas) drawPlain(canvas, buffer);
            }}
          />

          {item.draft?.ask ? (
            <p className="identity-note" style={{ margin: 0 }}>
              Focus: {item.draft.ask}
            </p>
          ) : null}

          <label className="identity-said" style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
            <input type="checkbox" checked={showHint} onChange={(e) => setShowHint(e.target.checked)} />
            Prefill from agent hint
            {item.draft?.confidence ? ` (${item.draft.confidence})` : ""}
          </label>

          <div>
            <p className="tool-kicker" style={{ marginBottom: "0.35rem" }}>
              Bucket
            </p>
            <div className="tool-row marks" style={{ flexWrap: "wrap" }}>
              {BUCKETS.map((row) => (
                <button
                  key={row.id}
                  type="button"
                  className={bucket === row.id ? "kind-chip on" : "kind-chip"}
                  onClick={() => setBucket(row.id)}
                >
                  {row.label}
                </button>
              ))}
            </div>
          </div>

          <div>
            <p className="tool-kicker" style={{ marginBottom: "0.35rem" }}>
              Kind
            </p>
            <div className="tool-row marks" style={{ flexWrap: "wrap", gap: "0.35rem" }}>
              {KINDS.map((row) => (
                <button
                  key={row}
                  type="button"
                  className={kind === row ? "kind-chip on" : "kind-chip"}
                  onClick={() => setKind(row)}
                >
                  {row}
                </button>
              ))}
            </div>
          </div>

          <div>
            <p className="tool-kicker" style={{ marginBottom: "0.35rem" }}>
              Phase
            </p>
            <div className="tool-row marks" style={{ flexWrap: "wrap", gap: "0.35rem" }}>
              {PHASES.map((row) => (
                <button
                  key={row}
                  type="button"
                  className={phase === row ? "kind-chip on" : "kind-chip"}
                  onClick={() => setPhase(row)}
                >
                  {row}
                </button>
              ))}
            </div>
          </div>

          <div>
            <p className="tool-kicker" style={{ marginBottom: "0.35rem" }}>
              Setting
            </p>
            <div className="tool-row marks" style={{ flexWrap: "wrap", gap: "0.35rem" }}>
              {SETTINGS.map((row) => (
                <button
                  key={row}
                  type="button"
                  className={setting === row ? "kind-chip on" : "kind-chip"}
                  onClick={() => setSetting(row)}
                >
                  {row}
                </button>
              ))}
            </div>
          </div>

          <label className="identity-said" style={{ display: "flex", flexDirection: "column" }}>
            Speaker
            <input
              value={speaker}
              placeholder="Who is talking — leave blank if none / unknown"
              onChange={(e) => setSpeaker(e.target.value)}
            />
          </label>

          <label className="identity-said" style={{ display: "flex", flexDirection: "column" }}>
            Note
            <input value={note} placeholder="Anything else" onChange={(e) => setNote(e.target.value)} />
          </label>

          <div className="identity-nav">
            <button type="button" disabled={index === 0} onClick={() => setIndex((n) => n - 1)}>
              Previous
            </button>
            <button type="button" className="arrow-btn finish" disabled={saving} onClick={() => void save()}>
              {saving ? "Saving…" : item.saved ? "Update & next" : "Save & next"}
            </button>
            <button
              type="button"
              disabled={index >= items.length - 1}
              onClick={() => setIndex((n) => n + 1)}
            >
              Skip
            </button>
          </div>
        </section>
      ) : (
        <p>No clips in the queue.</p>
      )}
      {error ? <p className="device">{error}</p> : null}
      <p className="tag" style={{ marginTop: "1rem" }}>
        <Link href="/voices">Voices</Link>
        {" · "}
        <Link href="/review">Listen</Link>
        {" · "}
        <Link href="/label">Ad labeler</Link>
      </p>
    </main>
  );
}
