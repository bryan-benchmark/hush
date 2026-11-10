"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { WaveTransport } from "@/components/WaveTransport";

type Frame = { file: string; t_s: number };
type Region = { start_s: number; end_s: number; bucket: string; kind: string; note: string };
type Take = {
  id: string;
  session: string;
  session_dir: string;
  audio_rel: string;
  audio_start_s?: number;
  duration_s: number;
  recorded_utc: string;
  channel: string;
  group: string;
  program: string;
  date: string;
  time: string;
  dow: string;
  daypart: string;
  frames: Frame[];
  caption: string;
  why?: string | null;
  ask?: string | null;
  help?: boolean;
  expect_bucket?: string | null;
  source?: string;
  whole_clip?: boolean;
  cloud?: boolean;
};
type Saved = { id: string; regions: Region[]; saved_at: string };
type Draft = { start_s: number; end_s: number };

/** Plain-language labels — only these five choices matter for the human. */
const LABELS = [
  {
    id: "paid_ad",
    icon: "🛒",
    title: "Commercial",
    blurb: "Standalone ad for a product, store, insurance, app…",
    kind: "dry_vo",
  },
  {
    id: "program",
    icon: "📺",
    title: "The show",
    blurb: "Game, news desk, studio talk — the program itself",
    kind: "program_sports",
  },
  {
    id: "show_promo",
    icon: "📣",
    title: "Show promo",
    blurb: "Promo for another show, network, or streaming title",
    kind: "show_promo",
  },
  {
    id: "program_mention",
    icon: "🤝",
    title: "Sponsor in show",
    blurb: "Show keeps going while they name a sponsor / PiP ad",
    kind: "in_show_sponsorship",
  },
  {
    id: "uncertain",
    icon: "❓",
    title: "Not sure",
    blurb: "Mixed, unclear, or you want a second look later",
    kind: "unknown",
  },
] as const;

const COLORS: Record<string, string> = {
  paid_ad: "#ff8ad4",
  program: "#7ec8ff",
  show_promo: "#f2c14e",
  program_mention: "#9dffce",
  uncertain: "#d7c6f5",
};

function labelMeta(id: string) {
  return LABELS.find((row) => row.id === id) || LABELS[4];
}

function drawWave(
  canvas: HTMLCanvasElement,
  audio: AudioBuffer,
  regions: Region[],
  draft: Draft | null,
) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const data = audio.getChannelData(0);
  const width = canvas.width;
  const height = canvas.height;
  let peak = 0;
  for (let i = 0; i < data.length; i += 8) peak = Math.max(peak, Math.abs(data[i]));
  const gain = peak > 0.001 ? 0.92 / peak : 1;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#1a1024";
  ctx.fillRect(0, 0, width, height);

  const dur = audio.duration || 1;
  for (const region of regions) {
    const x0 = (region.start_s / dur) * width;
    const x1 = (region.end_s / dur) * width;
    ctx.fillStyle = `${COLORS[region.bucket] || "#d7c6f5"}33`;
    ctx.fillRect(x0, 0, Math.max(2, x1 - x0), height);
  }
  if (draft && draft.end_s > draft.start_s) {
    const x0 = (draft.start_s / dur) * width;
    const x1 = (draft.end_s / dur) * width;
    ctx.fillStyle = "#ffffff22";
    ctx.fillRect(x0, 0, Math.max(2, x1 - x0), height);
    ctx.strokeStyle = "#ffffffaa";
    ctx.strokeRect(x0, 1, Math.max(2, x1 - x0), height - 2);
  }

  ctx.strokeStyle = "#d7c6f5";
  ctx.beginPath();
  const step = Math.max(1, Math.floor(data.length / width));
  for (let x = 0; x < width; x += 1) {
    let min = 1;
    let max = -1;
    const start = x * step;
    for (let i = 0; i < step; i += 1) {
      const sample = Math.max(-1, Math.min(1, (data[start + i] ?? 0) * gain));
      min = Math.min(min, sample);
      max = Math.max(max, sample);
    }
    ctx.moveTo(x, (1 - max) * 0.5 * height);
    ctx.lineTo(x, (1 - min) * 0.5 * height);
  }
  ctx.stroke();
}

/** Still that covers time t: latest frame at or before t (else first). */
function frameAt(frames: Frame[], t: number): Frame | null {
  if (!frames.length) return null;
  let best = frames[0];
  for (const frame of frames) {
    if (frame.t_s <= t + 0.05) best = frame;
    else break;
  }
  return best;
}

export function FarmLabelApp() {
  const [items, setItems] = useState<Take[]>([]);
  const [saved, setSaved] = useState<Saved[]>([]);
  const [index, setIndex] = useState(0);
  const [error, setError] = useState("");
  const [regions, setRegions] = useState<Region[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [markIn, setMarkIn] = useState<number | null>(null);
  const [bucket, setBucket] = useState("paid_ad");
  const [kind, setKind] = useState("dry_vo");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [playhead, setPlayhead] = useState(0);
  const [narrow, setNarrow] = useState(false);

  function pickLabel(id: string) {
    const meta = labelMeta(id);
    setBucket(meta.id);
    setKind(meta.kind);
  }

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 700px), (pointer: coarse)");
    const apply = () => setNarrow(mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const decodedRef = useRef<AudioBuffer | null>(null);
  const dragRef = useRef<{ start: number; pointerId: number; x: number; y: number; moved: boolean } | null>(null);
  const [heardDur, setHeardDur] = useState(0);

  const [helpN, setHelpN] = useState(0);
  /** Clips left via Done — Prev restores the last one (Done used to leave index stuck at 0). */
  const [history, setHistory] = useState<Take[]>([]);

  useEffect(() => {
    fetch("/api/farm-takes")
      .then((res) => res.json())
      .then((data) => {
        const next = (data.items ?? []) as Take[];
        const prior = (data.saved ?? []) as Saved[];
        setItems(next);
        setSaved(prior);
        setHistory([]);
        setHelpN(Number(data.help_n || next.filter((row) => row.help).length || 0));
        const judged = new Set(prior.filter((row) => row.regions.length > 0).map((row) => row.id));
        const first = next.findIndex((row) => !judged.has(row.id));
        setIndex(first >= 0 ? first : 0);
      })
      .catch(() => setError("Could not load farm takes."));
  }, []);

  const item = items[index];
  const savedCount = saved.filter((row) => row.regions.length > 0).length;
  const remaining = items.length;

  useEffect(() => {
    if (!item) return;
    const last = saved.find((row) => row.id === item.id);
    setRegions(last?.regions ?? []);
    setMarkIn(null);
    setPlayhead(0);
    setHeardDur(Number(item.duration_s) || 0);
    decodedRef.current = null;
    dragRef.current = null;
    // Clip mode: whole section is pre-selected — just pick the label.
    const whole = Boolean(item.whole_clip) || Number(item.duration_s) <= 60;
    if (whole && Number(item.duration_s) > 0.35) {
      setDraft({ start_s: 0, end_s: Number(item.duration_s) });
    } else {
      setDraft(null);
    }
    if (item.expect_bucket) pickLabel(item.expect_bucket);
    else if (item.whole_clip) pickLabel("uncertain");
    else pickLabel("paid_ad");
    // Short note: first clause only (merged aid captions get long).
    const hint = (item.caption || "")
      .replace(/^expect_\w+\s*/i, "")
      .split(" · ")
      .map((s) => s.trim())
      .find((s) => s && !/^still_diff|^transcript|^fallback|^label_aid/i.test(s));
    setNote(hint && hint.length <= 80 ? hint : hint ? hint.slice(0, 72) : "");
    // Map known expect words in caption when expect_bucket missing.
    const cap = (item.caption || "").toLowerCase();
    if (!item.expect_bucket) {
      if (/mitsubishi|geico|commercial|auto ad|hump day/.test(cap)) pickLabel("paid_ad");
      else if (/promo|tulsa king/.test(cap)) pickLabel("show_promo");
      else if (/pip|chase sapphire|sponsor/.test(cap)) pickLabel("program_mention");
      else if (/soccer|sports|studio|scorebug|nba|nwsl/.test(cap)) pickLabel("program");
    }
    setError("");
  }, [item, saved]);

  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const audio = audioRef.current;
      if (audio) {
        const at = audio.currentTime || 0;
        setPlayhead((prev) => (Math.abs(prev - at) >= 0.05 ? at : prev));
        if (markIn != null && at > markIn) {
          setDraft({ start_s: markIn, end_s: at });
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [item, markIn]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const decoded = decodedRef.current;
    if (!canvas || !decoded) return;
    drawWave(canvas, decoded, regions, draft);
  }, [regions, draft, item]);

  const activeFrame = useMemo(() => (item ? frameAt(item.frames, playhead) : null), [item, playhead]);
  const frameSrc = (file: string) => {
    if (!item) return "";
    if (item.cloud || !item.session_dir) {
      return `/api/farm-frame?id=${encodeURIComponent(item.id)}&file=${encodeURIComponent(file)}`;
    }
    return `/api/farm-frame?session_dir=${encodeURIComponent(item.session_dir)}&file=${encodeURIComponent(file)}`;
  };

  function seekTo(t: number) {
    if (audioRef.current) audioRef.current.currentTime = t;
    setPlayhead(t);
  }

  function timeAt(clientX: number) {
    const canvas = canvasRef.current;
    const duration =
      (heardDur > 0 ? heardDur : 0) ||
      item?.duration_s ||
      decodedRef.current?.duration ||
      1;
    if (!canvas) return 0;
    const rect = canvas.getBoundingClientRect();
    const x = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    return Math.round(x * duration * 100) / 100;
  }

  function onPointerDown(event: React.PointerEvent<HTMLCanvasElement>) {
    if (!item) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    const at = timeAt(event.clientX);
    // Click = seek only. Drag past a small threshold = grab. Avoids accidental 0→end grabs.
    dragRef.current = {
      start: at,
      pointerId: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      moved: false,
    };
    setMarkIn(null);
    seekTo(at);
  }

  function onPointerMove(event: React.PointerEvent<HTMLCanvasElement>) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    if (!drag.moved) {
      // Phones: slightly lower threshold so a short drag still counts as a grab.
      if (Math.hypot(event.clientX - drag.x, event.clientY - drag.y) < (narrow ? 7 : 10)) return;
      drag.moved = true;
    }
    const at = timeAt(event.clientX);
    setDraft({ start_s: Math.min(drag.start, at), end_s: Math.max(drag.start, at) });
  }

  function onPointerUp(event: React.PointerEvent<HTMLCanvasElement>) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    dragRef.current = null;
    const at = timeAt(event.clientX);
    if (!drag.moved) {
      // Plain click — already seeked on down; do not invent a grab.
      return;
    }
    const start = Math.min(drag.start, at);
    const end = Math.max(drag.start, at);
    if (end - start < 0.35) {
      setDraft(null);
      return;
    }
    setDraft({ start_s: start, end_s: end });
  }

  function markInOut() {
    const audio = audioRef.current;
    if (!audio || !item) return;
    const at = Math.round(audio.currentTime * 100) / 100;
    if (markIn == null) {
      setMarkIn(at);
      setDraft({ start_s: at, end_s: at });
      return;
    }
    const start = Math.min(markIn, at);
    const end = Math.max(markIn, at);
    setMarkIn(null);
    if (end - start >= 0.2) setDraft({ start_s: start, end_s: end });
  }

  function buildRegion(): Region | null {
    const span =
      draft && draft.end_s - draft.start_s >= 0.35
        ? draft
        : item && (item.whole_clip || item.duration_s <= 60)
          ? { start_s: 0, end_s: item.duration_s }
          : null;
    if (!span) return null;
    return {
      start_s: span.start_s,
      end_s: span.end_s,
      bucket,
      kind,
      note,
    };
  }

  function addRegion() {
    const region = buildRegion();
    if (!region) {
      setError("Select a section on the wave first (or use a short clip).");
      return;
    }
    setRegions((prev) => [...prev, region]);
    setMarkIn(null);
    setNote("");
    setError("");
    // Keep a whole-clip grab ready for another Add, or drag to replace with a part.
    if (item && (item.whole_clip || item.duration_s <= 60)) {
      setDraft({ start_s: 0, end_s: item.duration_s });
    } else {
      setDraft(null);
    }
  }

  async function saveRegions(nextRegions: Region[]) {
    if (!item) return;
    setSaving(true);
    setError("");
    try {
      const res = await fetch("/api/farm-takes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: item.id, regions: nextRegions }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(String(data.error || "Save failed"));
        setSaving(false);
        return;
      }
      const nextSaved: Saved = { id: item.id, regions: nextRegions, saved_at: new Date().toISOString() };
      setSaved((prev) => {
        const others = prev.filter((row) => row.id !== item.id);
        return [...others, nextSaved];
      });
      const wasHelp = Boolean(item.help);
      const leaving = item;
      setHistory((prev) => [...prev, leaving]);
      setItems((prev) => {
        const next = prev.filter((row) => row.id !== leaving.id);
        setIndex(0);
        return next;
      });
      if (wasHelp) setHelpN((n) => Math.max(0, n - 1));
      setSaving(false);
    } catch {
      setError("Save failed.");
      setSaving(false);
    }
  }

  async function saveTake() {
    await saveRegions(regions);
  }

  /** Save every section you Added, then advance. */
  async function confirmClip() {
    if (regions.length === 0) {
      setError("Add at least one section first (label + optional note).");
      return;
    }
    await saveRegions(regions);
  }

  const audioStart = item?.audio_start_s ?? 0;
  const audioSrc = !item
    ? ""
    : item.cloud || !item.session_dir
      ? `/api/farm-audio?id=${encodeURIComponent(item.id)}`
      : item.audio_rel
        ? `/api/farm-audio?session_dir=${encodeURIComponent(item.session_dir)}&audio_rel=${encodeURIComponent(item.audio_rel)}&start=${audioStart}&duration=${item.duration_s}`
        : "";

  const selected = labelMeta(bucket);
  const clipMode = Boolean(
    item && (item.whole_clip || Number(item.duration_s) > 0 && Number(item.duration_s) <= 60),
  );
  const grabReady = Boolean(draft && draft.end_s - draft.start_s >= 0.35) || clipMode;

  return (
    <main className={`shell identity-shell farm-labeler${narrow ? " is-narrow" : ""}`}>
      <div className="atmosphere" aria-hidden="true" />
      <header className="farm-labeler-top">
        <h1 className="identity-ask farm-labeler-title">
          Label · {items.length ? `${index + 1}/${items.length}` : "—"}
        </h1>
        <p className="tag farm-labeler-hint">
          {helpN > 0 ? `${helpN} need help · ` : ""}
          {remaining} left · {savedCount} saved
          <span className="farm-labeler-hint-long">
            {clipMode ? " · pick what this is → Done" : " · drag → pick → Add"}
          </span>
        </p>
      </header>

      {item ? (
        <section className="identity-card farm-labeler-card">
          <div className="farm-labeler-meta">
            {activeFrame ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                key={activeFrame.file}
                src={frameSrc(activeFrame.file)}
                alt=""
                className="farm-labeler-still"
              />
            ) : null}
            <div className="identity-note farm-labeler-meta-text">
              <strong>{item.channel}</strong>
              <span>
                {clipMode
                  ? `${item.duration_s.toFixed(0)}s clip${item.caption ? ` · ${item.caption}` : ""}`
                  : `${playhead.toFixed(0)}s / ${item.duration_s.toFixed(0)}s`}
              </span>
              {item.help && item.why ? (
                <span className="farm-labeler-why">Model: {item.why}</span>
              ) : item.ask === "needs_human" ? (
                <span className="farm-labeler-why">Model needs a human on this one</span>
              ) : null}
            </div>
            {clipMode ? null : (
              <div className="farm-labeler-marks">
                <button type="button" className="kind-chip farm-tap" onClick={markInOut}>
                  {markIn == null ? "In" : "Out"}
                </button>
                <button
                  type="button"
                  className="kind-chip farm-tap"
                  onClick={() => setDraft(null)}
                  disabled={!draft && markIn == null}
                >
                  Clear
                </button>
              </div>
            )}
          </div>

          <div className="farm-labeler-wave">
            <div className="farm-wave-shell">
              <WaveTransport
                src={audioSrc}
                audioRef={audioRef}
                canvasRef={canvasRef}
                waveHeight={narrow ? 96 : 84}
                compact
                simple
                knownDuration={heardDur > 0 ? heardDur : item.duration_s}
                // Always loop the whole clip — never the grab box (that made seek jump back).
                loop={{ start_s: 0, end_s: item.duration_s }}
                loopByDefault
                volumeControl
                onDecoded={(buffer) => {
                  decodedRef.current = buffer;
                  if (Number.isFinite(buffer.duration) && buffer.duration > 0) {
                    setHeardDur(buffer.duration);
                  }
                  const canvas = canvasRef.current;
                  if (canvas) drawWave(canvas, buffer, regions, draft);
                }}
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                onPointerCancel={onPointerUp}
              />
            </div>
            <p className="identity-note farm-wave-hint">
              Tap = jump · drag = select a section
            </p>
          </div>

          <div className="farm-labeler-labels">
            <div className="farm-label-grid">
              {LABELS.map((row) => {
                const on = bucket === row.id;
                return (
                  <button
                    key={row.id}
                    type="button"
                    title={row.blurb}
                    className={on ? "farm-label-btn on" : "farm-label-btn"}
                    onClick={() => pickLabel(row.id)}
                    aria-pressed={on}
                    style={{
                      borderColor: on ? COLORS[row.id] : undefined,
                      background: on ? `${COLORS[row.id]}22` : undefined,
                    }}
                  >
                    <span className="farm-label-icon">{row.icon}</span>
                    <span className="farm-label-title">{row.title}</span>
                  </button>
                );
              })}
            </div>
            <p className="identity-note farm-labeler-blurb">
              {selected.icon} <strong>{selected.title}</strong>
              <span className="farm-labeler-blurb-text"> — {selected.blurb}</span>
            </p>
          </div>

          <div className="farm-add-row">
            <label className="identity-said farm-labeler-note">
              <span>Note</span>
              <input
                value={note}
                placeholder="e.g. Mitsubishi (optional)"
                enterKeyHint="done"
                autoComplete="off"
                autoCorrect="off"
                onChange={(e) => setNote(e.target.value)}
              />
            </label>
            <button
              type="button"
              className="farm-add-btn"
              onClick={addRegion}
              disabled={!grabReady}
              title="Add this selection with the label above"
            >
              {selected.icon} Add {selected.title}
            </button>
          </div>

          <div className="farm-labeler-regions">
            {regions.length ? (
              regions.map((row, i) => {
                const meta = labelMeta(row.bucket);
                return (
                  <button
                    key={`${row.start_s}-${row.end_s}-${i}`}
                    type="button"
                    className="farm-region-row farm-tap"
                    title="Tap to remove"
                    onClick={() => setRegions((prev) => prev.filter((_, j) => j !== i))}
                  >
                    <span className="farm-region-main">
                      <span className="farm-region-icon">{meta.icon}</span>
                      <span className="farm-region-label">{meta.title}</span>
                      <span className="farm-region-span">
                        {row.start_s.toFixed(0)}–{row.end_s.toFixed(0)}s
                      </span>
                      {row.note ? <span className="farm-region-note">{row.note}</span> : null}
                    </span>
                    <span className="farm-region-x" aria-hidden>
                      ✕
                    </span>
                  </button>
                );
              })
            ) : (
              <span className="identity-note farm-labeler-empty">
                Pick a type, optional note, then Add — repeat if the clip has two things
              </span>
            )}
          </div>
        </section>
      ) : (
        <p>No farm takes with audio yet.</p>
      )}
      {error ? <p className="device farm-labeler-error">{error}</p> : null}

      {item ? (
        <div className="farm-labeler-dock">
          <button
            type="button"
            className="farm-dock-btn"
            disabled={history.length === 0 && index === 0}
            onClick={() => {
              if (history.length > 0) {
                const prevClip = history[history.length - 1];
                setHistory((h) => h.slice(0, -1));
                setItems((list) => [prevClip, ...list.filter((row) => row.id !== prevClip.id)]);
                setIndex(0);
                if (prevClip.help) setHelpN((n) => n + 1);
                return;
              }
              setIndex((n) => Math.max(0, n - 1));
            }}
          >
            Prev
          </button>
          <button
            type="button"
            className="arrow-btn finish farm-dock-btn farm-dock-primary"
            disabled={saving || regions.length === 0}
            onClick={() => void (clipMode ? confirmClip() : saveTake())}
            title="Save all added sections and go to the next clip"
          >
            {saving ? "…" : regions.length > 0 ? `Done · next (${regions.length})` : "Add a section first"}
          </button>
        </div>
      ) : null}
    </main>
  );
}
