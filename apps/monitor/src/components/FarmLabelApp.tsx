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
  review_batch?: string | null;
  draft_bucket?: string | null;
  draft_confidence?: string | null;
  whole_clip?: boolean;
  cloud?: boolean;
};
type Saved = { id: string; regions: Region[]; saved_at: string; av_mismatch?: boolean };
type Draft = { start_s: number; end_s: number };

/** Content buckets — The show first (far left); Not sure + A/V share a row below. */
const CONTENT_LABELS = [
  {
    id: "program",
    icon: "📺",
    title: "The show",
    blurb: "Game, news desk, studio talk — the program itself",
    kind: "program_sports",
  },
  {
    id: "paid_ad",
    icon: "🛒",
    title: "Commercial",
    blurb: "Standalone ad for a product, store, insurance, app…",
    kind: "dry_vo",
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
] as const;

const UNSURE_LABEL = {
  id: "uncertain",
  icon: "❓",
  title: "Not sure",
  blurb: "Mixed, unclear, or you want a second look later",
  kind: "unknown",
} as const;

/** Grow this list — saved on the region as `kind` (bucket stays paid_ad). */
const COMMERCIAL_SUBCARDS = [
  { id: "ad_car", icon: "🚗", title: "Car" },
  { id: "ad_car_insurance", icon: "🛡️", title: "Car insurance" },
  { id: "ad_health_insurance", icon: "🏥", title: "Health insurance" },
  { id: "ad_rx", icon: "💊", title: "Rx" },
  { id: "ad_other", icon: "📦", title: "Other" },
] as const;

const LABELS = [...CONTENT_LABELS, UNSURE_LABEL] as const;

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

function commercialSubMeta(kind: string) {
  return COMMERCIAL_SUBCARDS.find((row) => row.id === kind) || null;
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
  const [kind, setKind] = useState("ad_other");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [playhead, setPlayhead] = useState(0);
  const [narrow, setNarrow] = useState(false);
  /** Still vs audio out of sync — usually extreme stream lag. */
  const [avMismatch, setAvMismatch] = useState(false);

  function pickLabel(id: string) {
    const meta = labelMeta(id);
    setBucket(meta.id);
    // Commercial opens sub-cards; default Other until they tap one.
    setKind(meta.id === "paid_ad" ? "ad_other" : meta.kind);
  }

  function pickCommercialSub(subId: string) {
    setBucket("paid_ad");
    setKind(subId);
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
  /** YouTube-style: double-tap left = back, right = forward. */
  const doubleTapRef = useRef<{ at: number; side: "left" | "right" } | null>(null);
  const [heardDur, setHeardDur] = useState(0);
  const [skipFlash, setSkipFlash] = useState<string | null>(null);

  const [helpN, setHelpN] = useState(0);
  const [instructions, setInstructions] = useState("");
  const [parkedN, setParkedN] = useState(0);
  const [morningMode, setMorningMode] = useState(true);
  const [loading, setLoading] = useState(true);
  const [reloadToken, setReloadToken] = useState(0);
  /** Clips left via Done — Prev restores the last one (Done used to leave index stuck at 0). */
  const [history, setHistory] = useState<Take[]>([]);

  useEffect(() => {
    const qs = morningMode ? "" : "?all=1";
    const ac = new AbortController();
    setLoading(true);
    setError("");
    fetch(`/api/farm-takes${qs}`, { signal: ac.signal })
      .then((res) => res.json())
      .then((data) => {
        const next = (data.items ?? []) as Take[];
        const prior = (data.saved ?? []) as Saved[];
        setItems(next);
        setSaved(prior);
        setHistory([]);
        setHelpN(Number(data.help_n || next.filter((row) => row.help).length || 0));
        setParkedN(Number(data.morning_parked || 0));
        setInstructions(String(data.instructions || ""));
        const judged = new Set(prior.filter((row) => row.regions.length > 0).map((row) => row.id));
        const first = next.findIndex((row) => !judged.has(row.id));
        setIndex(first >= 0 ? first : 0);
        setLoading(false);
      })
      .catch((err) => {
        if (err?.name === "AbortError") return;
        setLoading(false);
        setError("Could not load farm takes.");
      });
    return () => ac.abort();
  }, [morningMode, reloadToken]);

  const item = items[index];
  const savedCount = saved.filter((row) => row.regions.length > 0).length;
  const remaining = items.length;

  useEffect(() => {
    if (!item) return;
    const last = saved.find((row) => row.id === item.id);
    setRegions(last?.regions ?? []);
    setAvMismatch(Boolean(last?.av_mismatch));
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

  function clipDuration() {
    if (!item) return 0;
    return (heardDur > 0 ? heardDur : 0) || item.duration_s || decodedRef.current?.duration || 0;
  }

  function skipStep() {
    const dur = clipDuration();
    if (dur <= 0) return 5;
    // Short farm clips: 5s (or ¼ of the clip), never more than half.
    return Math.max(2, Math.min(5, Math.round(dur * 0.25 * 10) / 10));
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
    const rect = event.currentTarget.getBoundingClientRect();
    const side: "left" | "right" = event.clientX < rect.left + rect.width / 2 ? "left" : "right";
    const now = Date.now();
    const prev = doubleTapRef.current;
    if (prev && now - prev.at < 320 && prev.side === side) {
      // Double-tap same half — skip like YouTube / Reels (relative to playhead).
      doubleTapRef.current = null;
      dragRef.current = null;
      const step = skipStep();
      const here = audioRef.current?.currentTime ?? playhead;
      const next = side === "left" ? Math.max(0, here - step) : Math.min(clipDuration(), here + step);
      seekTo(Math.round(next * 100) / 100);
      setMarkIn(null);
      const label = side === "left" ? `−${step}s` : `+${step}s`;
      setSkipFlash(label);
      window.setTimeout(() => setSkipFlash((cur) => (cur === label ? null : cur)), 450);
      return;
    }
    doubleTapRef.current = { at: now, side };

    const at = timeAt(event.clientX);
    // Single tap = seek. Drag past a small threshold = grab.
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
      doubleTapRef.current = null; // drag is not a double-tap skip
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
        body: JSON.stringify({ id: item.id, regions: nextRegions, av_mismatch: avMismatch || undefined }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(String(data.error || "Save failed"));
        setSaving(false);
        return;
      }
      const nextSaved: Saved = {
        id: item.id,
        regions: nextRegions,
        saved_at: new Date().toISOString(),
        ...(avMismatch ? { av_mismatch: true } : {}),
      };
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

  /** Audio ≠ picture (lag) — throw out of dataset, advance. */
  async function discardBadAv() {
    if (!item) return;
    setSaving(true);
    setError("");
    try {
      const res = await fetch("/api/farm-takes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: item.id,
          discard: "av_lag",
          note: note || "audio≠picture lag",
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(String(data.error || "Discard failed"));
        setSaving(false);
        return;
      }
      const leaving = item;
      const wasHelp = Boolean(item.help);
      setHistory((prev) => [...prev, leaving]);
      setItems((prev) => {
        const next = prev.filter((row) => row.id !== leaving.id);
        setIndex(0);
        return next;
      });
      if (wasHelp) setHelpN((n) => Math.max(0, n - 1));
      setAvMismatch(false);
      setRegions([]);
      setSaving(false);
    } catch {
      setError("Discard failed.");
      setSaving(false);
    }
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
          {item?.review_batch === "active" ? " · batch" : ""}
        </h1>
        <p className="tag farm-labeler-hint">
          {morningMode ? "Morning batch · " : "Full pile · "}
          {helpN > 0 ? `${helpN} need help · ` : ""}
          {remaining} left · {savedCount} saved
          {parkedN > 0 && morningMode ? ` · ${parkedN} parked` : ""}
          <span className="farm-labeler-hint-long">
            {clipMode ? " · pick what this is → Done" : " · drag → pick → Add"}
          </span>
        </p>
        {instructions ? <p className="tag farm-labeler-hint">{instructions}</p> : null}
        <p className="farm-labeler-hint">
          <button
            type="button"
            className="kind-chip farm-tap"
            onClick={() => setMorningMode((v) => !v)}
          >
            {morningMode ? "Show more of pile" : "Morning batch only"}
          </button>
          <button
            type="button"
            className="kind-chip farm-tap"
            style={{ marginLeft: 8 }}
            onClick={() => setReloadToken((n) => n + 1)}
          >
            Refresh
          </button>
        </p>
      </header>

      {item ? (
        <section className="identity-card farm-labeler-card">
          <div className="farm-labeler-meta">
            <div className="farm-still-wrap">
              {activeFrame ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  key={activeFrame.file}
                  src={frameSrc(activeFrame.file)}
                  alt=""
                  className="farm-labeler-still"
                />
              ) : (
                <div className="farm-labeler-still farm-still-empty" aria-hidden />
              )}
            </div>
            <div className="identity-note farm-labeler-meta-text">
              <strong>{item.channel}</strong>
              <span>
                {clipMode
                  ? `${item.duration_s.toFixed(0)}s clip${item.caption ? ` · ${item.caption}` : ""}`
                  : `${playhead.toFixed(0)}s / ${item.duration_s.toFixed(0)}s`}
              </span>
              {item.ask ? (
                <span className="farm-labeler-why">
                  {item.ask}
                  {item.draft_bucket ? ` · draft ${item.draft_bucket}` : ""}
                  {item.draft_confidence ? ` (${item.draft_confidence})` : ""}
                </span>
              ) : null}
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
              <div className="farm-wave-stage-wrap">
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
                {skipFlash ? (
                  <div className="farm-skip-flash" aria-live="polite">
                    {skipFlash}
                  </div>
                ) : null}
              </div>
            </div>
            <p className="identity-note farm-wave-hint">
              Tap = jump · double-tap L/R = skip · drag = select
            </p>
          </div>

          <div className="farm-labeler-labels">
            <div className="farm-label-grid">
              {CONTENT_LABELS.map((row) => {
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
            {bucket === "paid_ad" ? (
              <div className="farm-label-subgrid" role="group" aria-label="Commercial type">
                {COMMERCIAL_SUBCARDS.map((row) => {
                  const on = kind === row.id;
                  return (
                    <button
                      key={row.id}
                      type="button"
                      className={on ? "farm-label-btn farm-sub-btn on" : "farm-label-btn farm-sub-btn"}
                      onClick={() => pickCommercialSub(row.id)}
                      aria-pressed={on}
                      style={{
                        borderColor: on ? COLORS.paid_ad : undefined,
                        background: on ? `${COLORS.paid_ad}22` : undefined,
                      }}
                    >
                      <span className="farm-label-icon">{row.icon}</span>
                      <span className="farm-label-title">{row.title}</span>
                    </button>
                  );
                })}
              </div>
            ) : null}
            <div className="farm-label-secondary">
              <button
                type="button"
                title={UNSURE_LABEL.blurb}
                className={
                  bucket === UNSURE_LABEL.id ? "farm-label-btn farm-label-row on" : "farm-label-btn farm-label-row"
                }
                onClick={() => pickLabel(UNSURE_LABEL.id)}
                aria-pressed={bucket === UNSURE_LABEL.id}
                style={{
                  borderColor: bucket === UNSURE_LABEL.id ? COLORS.uncertain : undefined,
                  background: bucket === UNSURE_LABEL.id ? `${COLORS.uncertain}22` : undefined,
                }}
              >
                <span className="farm-label-icon">{UNSURE_LABEL.icon}</span>
                <span className="farm-label-title">{UNSURE_LABEL.title}</span>
              </button>
              <button
                type="button"
                title="Audio doesn't match the picture (lag) — remove from dataset"
                className="farm-label-btn farm-label-row farm-label-av"
                disabled={saving}
                onClick={() => void discardBadAv()}
              >
                <span className="farm-label-icon">⚠️</span>
                <span className="farm-label-title">
                  {saving ? "…" : "A/V Issue (Discard)"}
                </span>
              </button>
            </div>
            <p className="identity-note farm-labeler-blurb">
              {selected.icon} <strong>{selected.title}</strong>
              {bucket === "paid_ad" && commercialSubMeta(kind) ? (
                <span className="farm-labeler-blurb-text">
                  {" "}
                  · {commercialSubMeta(kind)!.icon} {commercialSubMeta(kind)!.title}
                </span>
              ) : (
                <span className="farm-labeler-blurb-text"> — {selected.blurb}</span>
              )}
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
              {selected.icon} Add{" "}
              {bucket === "paid_ad" && commercialSubMeta(kind)
                ? `Commercial · ${commercialSubMeta(kind)!.title}`
                : selected.title}
            </button>
          </div>

          <div className="farm-labeler-regions">
            {regions.length ? (
              regions.map((row, i) => {
                const meta = labelMeta(row.bucket);
                const sub = row.bucket === "paid_ad" ? commercialSubMeta(row.kind) : null;
                return (
                  <button
                    key={`${row.start_s}-${row.end_s}-${i}`}
                    type="button"
                    className="farm-region-row farm-tap"
                    title="Tap to remove"
                    onClick={() => setRegions((prev) => prev.filter((_, j) => j !== i))}
                  >
                    <span className="farm-region-main">
                      <span className="farm-region-icon">{sub?.icon || meta.icon}</span>
                      <span className="farm-region-label">
                        {meta.title}
                        {sub ? ` · ${sub.title}` : ""}
                      </span>
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
                Pick a type
                {bucket === "paid_ad" ? " + commercial sub-card" : ""}
                , optional note, then Add — repeat if the clip has two things
              </span>
            )}
          </div>
        </section>
      ) : loading ? (
        <p className="identity-note">Loading morning batch…</p>
      ) : (
        <p className="identity-note">
          No clips in this view.
          {parkedN > 0 ? ` ${parkedN} parked — try Refresh or Show more of pile.` : " Queue may still be building."}
        </p>
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
