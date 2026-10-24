"use client";

import { useEffect, useRef, useState } from "react";
import { WaveTransport } from "@/components/WaveTransport";
import { clipHasSplice, coversClip, noteLine, splitNote } from "@/lib/listenNote";

type Item = { id: string; session: string; play_start: number; duration: number; caption?: string; mark_s?: number };
type Region = { start_s: number; end_s: number; what: string; who: string; tags?: string[] };
type Saved = { id: string; regions: Region[] };
type Draft = { start_s: number; end_s: number };

const COLORS = ["#f2c14e", "#7ec8ff", "#ff8ad4", "#ffb086", "#d7c6f5", "#9dffce"];

function colorFor(what: string) {
  let hash = 0;
  for (const char of what.toLowerCase()) hash = (hash * 33 + char.charCodeAt(0)) >>> 0;
  return COLORS[hash % COLORS.length];
}

export function ListenReview({
  endpoint,
  kicker,
  otherHref,
  otherLabel,
}: {
  endpoint: string;
  kicker: string;
  otherHref: string;
  otherLabel: string;
}) {
  const [items, setItems] = useState<Item[]>([]);
  const [saved, setSaved] = useState<Saved[]>([]);
  const [index, setIndex] = useState(0);
  const [error, setError] = useState("");
  const [finished, setFinished] = useState(false);
  const [regions, setRegions] = useState<Region[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [markIn, setMarkIn] = useState<number | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [said, setSaid] = useState("");
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const decodedRef = useRef<AudioBuffer | null>(null);
  const regionsRef = useRef(regions);
  const draftRef = useRef(draft);
  const markInRef = useRef(markIn);
  const editingRef = useRef(editing);
  const saidRef = useRef(said);
  const savedRef = useRef<Saved[]>([]);
  const itemRef = useRef<Item | undefined>(undefined);
  const dragRef = useRef<
    { kind: "draw"; start: number; pointerId: number } | { kind: "edge"; edge: "start" | "end"; pointerId: number } | null
  >(null);
  const editGen = useRef(0);
  const nudgeRef = useRef<(edge: "start" | "end", direction: -1 | 1, step: number) => boolean>(() => false);
  const navLock = useRef(0);
  regionsRef.current = regions;
  draftRef.current = draft;
  markInRef.current = markIn;
  editingRef.current = editing;
  saidRef.current = said;
  savedRef.current = saved;
  itemRef.current = items[index];

  useEffect(() => {
    fetch(endpoint)
      .then((res) => res.json())
      .then((data) => {
        const next = (data.items ?? []) as Item[];
        const prior = (data.saved ?? []) as Saved[];
        setItems(next);
        setSaved(prior);
        const judged = new Set(prior.filter((row) => row.regions.length > 0).map((row) => row.id));
        const first = next.findIndex((item) => !judged.has(item.id));
        setIndex(first >= 0 ? first : 0);
      })
      .catch(() => setError("Could not load the review queue."));
  }, [endpoint]);

  const item = items[index];

  useEffect(() => {
    if (!item) return;
    const last = savedRef.current.find((row) => row.id === item.id);
    setRegions(last?.regions ?? []);
    setSaid("");
    saidRef.current = "";
    setDraft(null);
    setMarkIn(null);
    markInRef.current = null;
    setEditing(null);
    dragRef.current = null;
    decodedRef.current = null;
  }, [item]);

  useEffect(() => {
    if (markIn == null) return;
    let frame = 0;
    const tick = () => {
      const start = markInRef.current;
      const audio = audioRef.current;
      if (start != null && audio) {
        const duration = item?.duration ?? audio.duration ?? 20;
        const at = Math.round(Math.min(duration, Math.max(0, audio.currentTime)) * 100) / 100;
        if (at > start) setDraft({ start_s: start, end_s: at });
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [markIn, item]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const decoded = decodedRef.current;
    if (!canvas || !decoded) return;
    draw(canvas, decoded, regions, draft, editing, item?.mark_s ?? null);
  }, [regions, draft, editing, item]);

  function clipDuration() {
    const decoded = decodedRef.current?.duration;
    if (decoded && Number.isFinite(decoded) && decoded > 0) return decoded;
    const heard = audioRef.current?.duration;
    if (heard && Number.isFinite(heard) && heard > 0) return heard;
    return itemRef.current?.duration ?? 20;
  }

  function timeAt(clientX: number, canvas: HTMLCanvasElement) {
    const rect = canvas.getBoundingClientRect();
    const fraction = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    return Math.round(fraction * clipDuration() * 100) / 100;
  }

  function boxEdge(clientX: number, canvas: HTMLCanvasElement) {
    const rect = canvas.getBoundingClientRect();
    if (rect.width <= 0) return null;
    const duration = clipDuration();
    const x = clientX - rect.left;
    const xOf = (seconds: number) => (seconds / duration) * rect.width;
    let best: { edge: "start" | "end"; regionIndex: number | null; dist: number } | null = null;
    const consider = (span: { start_s: number; end_s: number }, regionIndex: number | null) => {
      if (span.end_s - span.start_s < 0.15) return;
      (["start", "end"] as const).forEach((edge) => {
        const dist = Math.abs(x - xOf(edge === "start" ? span.start_s : span.end_s));
        if (dist <= 10 && (!best || dist < best.dist)) best = { edge, regionIndex, dist };
      });
    };
    const draft = draftRef.current;
    if (draft) consider(draft, editingRef.current);
    regionsRef.current.forEach((region, index) => {
      if (draft && editingRef.current === index) return;
      consider(region, index);
    });
    if (!best) return null;
    const chosen: { edge: "start" | "end"; regionIndex: number | null } = best;
    return { edge: chosen.edge, regionIndex: chosen.regionIndex };
  }

  function showEdgeCursor(canvas: HTMLCanvasElement, on: boolean) {
    canvas.style.cursor = on ? "ew-resize" : "crosshair";
  }

  function playhead() {
    const audio = audioRef.current;
    const duration = itemRef.current?.duration ?? 20;
    const at = audio && Number.isFinite(audio.currentTime) ? audio.currentTime : 0;
    return Math.round(Math.min(duration, Math.max(0, at)) * 100) / 100;
  }

  function selectRegion(at: number) {
    const list = regionsRef.current;
    const hit = list.findIndex((region) => at >= region.start_s - 0.05 && at <= region.end_s + 0.05);
    if (hit < 0) {
      setEditing(null);
      editingRef.current = null;
      setDraft(null);
      draftRef.current = null;
      return;
    }
    const region = list[hit];
    const nextDraft = { start_s: region.start_s, end_s: region.end_s };
    const line = noteLine(region.what, region.who);
    editingRef.current = hit;
    draftRef.current = nextDraft;
    saidRef.current = line;
    setEditing(hit);
    setDraft(nextDraft);
    setSaid(line);
  }

  function onPointerDown(event: React.PointerEvent<HTMLCanvasElement>) {
    if (event.detail > 1) {
      dragRef.current = null;
      if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
      selectRegion(timeAt(event.clientX, event.currentTarget));
      return;
    }
    const hit = boxEdge(event.clientX, event.currentTarget);
    if (hit) {
      const current = draftRef.current;
      const region = hit.regionIndex == null ? null : regionsRef.current[hit.regionIndex];
      const target = region ?? current;
      const same =
        current &&
        target &&
        Math.abs(current.start_s - target.start_s) < 0.02 &&
        Math.abs(current.end_s - target.end_s) < 0.02;
      if (!same && region) {
        if (leaveBox(false) === "blocked") return;
        const fresh = regionsRef.current.find((entry) => Math.abs(entry.start_s - region.start_s) < 0.02 && Math.abs(entry.end_s - region.end_s) < 0.02) ?? region;
        const index = regionsRef.current.indexOf(fresh);
        const line = noteLine(fresh.what, fresh.who);
        const nextDraft = { start_s: fresh.start_s, end_s: fresh.end_s };
        editingRef.current = index >= 0 ? index : null;
        draftRef.current = nextDraft;
        saidRef.current = line;
        setEditing(index >= 0 ? index : null);
        setDraft(nextDraft);
        setSaid(line);
      }
      markInRef.current = null;
      setMarkIn(null);
      dragRef.current = { kind: "edge", edge: hit.edge, pointerId: event.pointerId };
      event.currentTarget.setPointerCapture(event.pointerId);
      showEdgeCursor(event.currentTarget, true);
      return;
    }
    if (leaveBox(false) === "blocked") return;
    const at = timeAt(event.clientX, event.currentTarget);
    dragRef.current = { kind: "draw", start: at, pointerId: event.pointerId };
    markInRef.current = null;
    setMarkIn(null);
    event.currentTarget.setPointerCapture(event.pointerId);
    setEditing(null);
    editingRef.current = null;
    setDraft({ start_s: at, end_s: at });
  }

  function onPointerMove(event: React.PointerEvent<HTMLCanvasElement>) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) {
      showEdgeCursor(event.currentTarget, boxEdge(event.clientX, event.currentTarget) != null);
      return;
    }
    if ((event.buttons & 1) === 0) {
      dragRef.current = null;
      showEdgeCursor(event.currentTarget, boxEdge(event.clientX, event.currentTarget) != null);
      return;
    }
    const at = timeAt(event.clientX, event.currentTarget);
    if (drag.kind === "edge") {
      const current = draftRef.current;
      const clip = itemRef.current;
      if (!current || !clip) return;
      const duration = clipDuration();
      let start = current.start_s;
      let end = current.end_s;
      if (drag.edge === "start") start = Math.min(Math.max(0, at), end - 0.2);
      else end = Math.max(Math.min(duration, at), start + 0.2);
      start = Math.round(start * 100) / 100;
      end = Math.round(end * 100) / 100;
      const others = regionsRef.current.filter((_, regionIndex) => regionIndex !== editingRef.current);
      if (coversClip(start, end, duration) && clipHasSplice(others, clip.duration)) return;
      const next = { start_s: start, end_s: end };
      draftRef.current = next;
      setDraft(next);
      showEdgeCursor(event.currentTarget, true);
      return;
    }
    setDraft({ start_s: Math.min(drag.start, at), end_s: Math.max(drag.start, at) });
  }

  function onPointerUp(event: React.PointerEvent<HTMLCanvasElement>) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    dragRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    showEdgeCursor(event.currentTarget, boxEdge(event.clientX, event.currentTarget) != null);
    if (drag.kind === "edge") return;
    const at = timeAt(event.clientX, event.currentTarget);
    const left = Math.min(drag.start, at);
    const right = Math.max(drag.start, at);
    if (right - left < 0.2) {
      selectRegion(at);
      return;
    }
    const clip = itemRef.current;
    if (clip && clipHasSplice(regionsRef.current, clip.duration) && coversClip(left, right, clip.duration)) {
      setDraft(null);
      draftRef.current = null;
      setError("This clip already has a splice, so the whole clip stays closed.");
      return;
    }
    setEditing(null);
    editingRef.current = null;
    const nextDraft = { start_s: left, end_s: right };
    draftRef.current = nextDraft;
    setDraft(nextDraft);
    setError("");
  }

  function onPointerCancel(event: React.PointerEvent<HTMLCanvasElement>) {
    if (dragRef.current?.pointerId === event.pointerId) dragRef.current = null;
    showEdgeCursor(event.currentTarget, false);
  }

  function onPointerLeave(event: React.PointerEvent<HTMLCanvasElement>) {
    if (dragRef.current) return;
    showEdgeCursor(event.currentTarget, false);
  }

  function closeOpenMark() {
    const start = markInRef.current;
    if (start == null) return true;
    const at = playhead();
    if (at - start < 0.15) {
      setError("Keep listening, then tap End.");
      return false;
    }
    const nextDraft = { start_s: start, end_s: at };
    markInRef.current = null;
    draftRef.current = nextDraft;
    setMarkIn(null);
    setDraft(nextDraft);
    return true;
  }

  async function save(next: Region[], gen: number, clip: Item) {
    setError("");
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: clip.id, regions: next }),
    });
    if (!res.ok) {
      setError("That was not saved.");
      return;
    }
    const ordered = [...next].sort((a, b) => a.start_s - b.start_s);
    const row = { id: clip.id, regions: ordered };
    const nextSaved = [...savedRef.current.filter((entry) => entry.id !== clip.id), row];
    savedRef.current = nextSaved;
    setSaved(nextSaved);
    if (itemRef.current?.id === clip.id) {
      regionsRef.current = ordered;
      setRegions(ordered);
      if (editGen.current === gen) {
        draftRef.current = null;
        editingRef.current = null;
        saidRef.current = "";
        setDraft(null);
        setEditing(null);
        setSaid("");
      }
    }
  }

  function commitNote(allowWhole = true): "empty" | "saved" | "kept" | "blocked" {
    const clip = itemRef.current;
    if (!clip) return "empty";
    if (markInRef.current != null && !closeOpenMark()) return "blocked";
    const current = draftRef.current;
    const editingNow = editingRef.current;
    const existing = editingNow != null ? regionsRef.current[editingNow] : null;
    let line = saidRef.current.trim();
    if (
      !line &&
      existing &&
      current &&
      current.end_s - current.start_s >= 0.2 &&
      (Math.abs(current.start_s - existing.start_s) > 0.001 || Math.abs(current.end_s - existing.end_s) > 0.001)
    ) {
      line = noteLine(existing.what, existing.who);
      saidRef.current = line;
    }
    if (!line) return "empty";
    const duration = clip.duration > 0 ? clip.duration : 20;
    let span = current && current.end_s - current.start_s >= 0.2 ? current : null;
    if (!span && existing) span = { start_s: existing.start_s, end_s: existing.end_s };
    const others = regionsRef.current.filter((_, regionIndex) => regionIndex !== editingNow);
    if (!span) {
      if (!allowWhole) return "kept";
      if (clipHasSplice(others, duration)) {
        setError("Box the part you mean. The whole clip is closed once a splice is in.");
        return "blocked";
      }
      span = { start_s: 0, end_s: Math.round(duration * 100) / 100 };
    }
    if (coversClip(span.start_s, span.end_s, duration) && clipHasSplice(others, duration)) {
      if (!allowWhole) return "kept";
      setError("This clip already has a splice, so the whole clip stays closed.");
      return "blocked";
    }
    const parsed = splitNote(line, span.start_s, span.end_s, duration);
    if (!parsed.what) return "empty";
    const region: Region = {
      start_s: span.start_s,
      end_s: span.end_s,
      what: parsed.what,
      who: parsed.who,
      tags: parsed.tags,
    };
    if (
      existing &&
      existing.what === region.what &&
      existing.who === region.who &&
      existing.start_s === region.start_s &&
      existing.end_s === region.end_s
    ) {
      return "empty";
    }
    const next = [...regionsRef.current];
    if (editingNow != null && editingNow < next.length) next[editingNow] = region;
    else next.push(region);
    const keptIndex = editingNow != null && editingNow < next.length ? editingNow : next.length - 1;
    const withoutWhole = coversClip(region.start_s, region.end_s, duration)
      ? next
      : next.filter((entry, regionIndex) => regionIndex === keptIndex || !coversClip(entry.start_s, entry.end_s, duration));
    regionsRef.current = withoutWhole;
    saidRef.current = "";
    draftRef.current = null;
    editingRef.current = null;
    setRegions(withoutWhole);
    setSaid("");
    setDraft(null);
    setEditing(null);
    void save(withoutWhole, editGen.current, clip);
    return "saved";
  }

  function leaveBox(allowWhole = true) {
    const result = commitNote(allowWhole);
    if (result !== "blocked") editGen.current += 1;
    return result;
  }

  function onFieldsBlur(event: React.FocusEvent<HTMLDivElement>) {
    const next = event.relatedTarget;
    if (next instanceof Node && event.currentTarget.contains(next)) return;
    if (next instanceof HTMLElement && next.dataset.skipSave === "1") return;
    commitNote();
  }

  function go(step: number) {
    const now = Date.now();
    if (now - navLock.current < 400) return;
    navLock.current = now;
    const result = commitNote(true);
    if (result === "blocked") {
      navLock.current = 0;
      return;
    }
    editGen.current += 1;
    const last = Math.max(0, items.length - 1);
    if (step > 0 && index >= last) {
      setFinished(true);
      return;
    }
    setFinished(false);
    setIndex((current) => Math.min(last, Math.max(0, current + step)));
  }

  function markWhole() {
    const clip = itemRef.current;
    if (!clip) return;
    if (clipHasSplice(regionsRef.current, clip.duration)) {
      setError("This clip already has a splice, so the whole clip stays closed.");
      return;
    }
    const end = Math.round((clip.duration > 0 ? clip.duration : 20) * 100) / 100;
    markInRef.current = null;
    setMarkIn(null);
    setEditing(null);
    editingRef.current = null;
    const nextDraft = { start_s: 0, end_s: end };
    draftRef.current = nextDraft;
    setDraft(nextDraft);
    setError("");
    if (saidRef.current.trim()) {
      commitNote(true);
      editGen.current += 1;
    }
    const audio = audioRef.current;
    if (audio) {
      audio.currentTime = 0;
      void audio.play();
    }
  }

  function markStart() {
    if (leaveBox(false) === "blocked") return;
    const at = playhead();
    markInRef.current = at;
    setMarkIn(at);
    setEditing(null);
    editingRef.current = null;
    const nextDraft = { start_s: at, end_s: at };
    draftRef.current = nextDraft;
    setDraft(nextDraft);
    setError("");
    const audio = audioRef.current;
    if (audio?.paused) void audio.play();
  }

  function markEnd() {
    if (!closeOpenMark()) return;
    setError("");
  }

  function nudge(edge: "start" | "end", direction: -1 | 1, step: number) {
    const clip = itemRef.current;
    const current = draftRef.current;
    if (!clip || !current) return false;
    const open = markInRef.current != null;
    if (open && edge === "end") return false;
    const duration = clip.duration > 0 ? clip.duration : 20;
    const minGap = 0.2;
    let start = open ? markInRef.current! : current.start_s;
    let end = current.end_s;
    if (!open && end - start < minGap - 0.001) return false;
    if (edge === "start") start = Math.round((start + direction * step) * 100) / 100;
    else end = Math.round((end + direction * step) * 100) / 100;
    start = Math.max(0, Math.min(duration, start));
    end = Math.max(0, Math.min(duration, end));
    if (!open) {
      if (edge === "start") start = Math.min(start, Math.round((end - minGap) * 100) / 100);
      else end = Math.max(end, Math.round((start + minGap) * 100) / 100);
      if (end - start < minGap - 0.001) return false;
    } else if (end < start) {
      end = start;
    }
    const others = regionsRef.current.filter((_, regionIndex) => regionIndex !== editingRef.current);
    if (!open && coversClip(start, end, duration) && clipHasSplice(others, duration)) return false;
    const next = { start_s: Math.round(start * 100) / 100, end_s: Math.round(end * 100) / 100 };
    if (next.start_s === current.start_s && next.end_s === current.end_s && (!open || markInRef.current === next.start_s)) return false;
    draftRef.current = next;
    setDraft(next);
    if (open) {
      markInRef.current = next.start_s;
      setMarkIn(next.start_s);
    }
    setError("");
    return true;
  }
  nudgeRef.current = nudge;

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      const tag = (event.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      const moved = nudgeRef.current(event.shiftKey ? "start" : "end", event.key === "ArrowLeft" ? -1 : 1, event.altKey ? 0.01 : 0.05);
      if (moved) event.preventDefault();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const duration = item?.duration ?? 20;
  const spliced = item ? clipHasSplice(regions, duration) : false;
  const whole = draft != null && coversClip(draft.start_s, draft.end_s, duration);
  const boxLabel =
    markIn != null ? `Started at ${markIn.toFixed(1)}s` : draft && draft.end_s - draft.start_s >= 0.2 ? `${draft.start_s.toFixed(1)}–${draft.end_s.toFixed(1)}s` : "";
  const lastClip = index >= items.length - 1;
  const marked = saved.filter((row) => row.regions.length > 0).length;

  if (finished) {
    return (
      <main className="shell identity-shell">
        <div className="atmosphere" aria-hidden="true" />
        <header className="top">
          <p className="tag">{kicker}</p>
          <h1 className="identity-ask">That’s the queue.</h1>
          <p className="identity-note">
            {marked} of {items.length} clips have a box.
          </p>
        </header>
        <div className="clip-nav">
          <button
            type="button"
            className="arrow-btn finish"
            onClick={() => {
              setFinished(false);
              setIndex(0);
            }}
          >
            Back to the first clip
          </button>
        </div>
        {error ? <p className="device">{error}</p> : null}
      </main>
    );
  }

  return (
    <main className="shell identity-shell">
      <div className="atmosphere" aria-hidden="true" />
      <header className="top">
        <p className="tag">
          {kicker}
          {items.length === 0 ? "" : ` · ${index + 1} of ${items.length}`}
        </p>
        <h1 className="identity-ask">What is this?</h1>
        {item?.caption ? <p className="identity-note">{item.caption}</p> : null}
      </header>
      {item ? (
        <section className="identity-card" style={{ display: "flex", flexDirection: "column", gap: "0.85rem" }}>
          <WaveTransport
            src={`/api/audio?session=${encodeURIComponent(item.session)}&mode=timeline&start=${item.play_start}&duration=${item.duration}`}
            audioRef={audioRef}
            canvasRef={canvasRef}
            loop={markIn == null && draft && draft.end_s - draft.start_s >= 0.2 ? draft : markIn == null ? { start_s: 0, end_s: item.duration } : null}
            loopByDefault
            onDecoded={(buffer) => {
              decodedRef.current = buffer;
              const canvas = canvasRef.current;
              if (canvas) draw(canvas, buffer, regionsRef.current, draftRef.current, editingRef.current, item.mark_s ?? null);
            }}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerCancel}
            onPointerLeave={onPointerLeave}
          />
          <div className="tool-row marks">
            {markIn == null ? (
              <button
                type="button"
                className="tool-card action"
                data-skip-save="1"
                onClick={(event) => {
                  if (event.detail > 1) return;
                  markStart();
                }}
              >
                <span className="tool-value">Start</span>
                <span className="tool-kicker">From the playhead</span>
              </button>
            ) : (
              <button
                type="button"
                className="tool-card action end"
                data-skip-save="1"
                onClick={(event) => {
                  if (event.detail > 1) return;
                  markEnd();
                }}
              >
                <span className="tool-value">End</span>
                <span className="tool-kicker">Close this box</span>
              </button>
            )}
            <button
              type="button"
              className={whole && !spliced ? "tool-card action on" : "tool-card action"}
              data-skip-save="1"
              disabled={spliced}
              onClick={(event) => {
                if (event.detail > 1) return;
                markWhole();
              }}
            >
              <span className="tool-value">Whole</span>
              <span className="tool-kicker">{spliced ? "Closed · splice in" : "The entire clip"}</span>
            </button>
            {boxLabel ? (
              <div className="tool-card read">
                <span className="tool-value">{markIn != null ? markIn.toFixed(2) : `${draft?.start_s.toFixed(2)}–${draft?.end_s.toFixed(2)}`}</span>
                <span className="tool-kicker">{markIn != null ? "Started" : "Marked"}</span>
              </div>
            ) : (
              <div className="tool-card read">
                <span className="tool-value">—</span>
                <span className="tool-kicker">No box yet</span>
              </div>
            )}
          </div>
          {draft && (markIn != null || draft.end_s - draft.start_s >= 0.2) ? (
            <div className="nudge-row" title="Arrow keys move the end. Shift moves the start. Option steps by 0.01s.">
              <EdgeNudge label="Start" seconds={markIn ?? draft.start_s} onNudge={(direction, step) => nudge("start", direction, step)} />
              <EdgeNudge label="End" seconds={draft.end_s} disabled={markIn != null} onNudge={(direction, step) => nudge("end", direction, step)} />
            </div>
          ) : null}
          <div onBlur={onFieldsBlur}>
            <label className="identity-said" style={{ display: "flex", flexDirection: "column" }}>
              What it is
              <input
                value={said}
                placeholder="A commercial, the booth, a return"
                onChange={(event) => {
                  saidRef.current = event.target.value;
                  setSaid(event.target.value);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    commitNote();
                  }
                }}
              />
            </label>
          </div>
          {regions.length ? (
            <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: "0.35rem" }}>
              {regions.map((region, regionIndex) => (
                <li key={`${regionIndex}-${region.start_s}-${region.end_s}`} style={{ display: "flex", gap: "0.6rem", alignItems: "center" }}>
                  <button
                    type="button"
                    data-skip-save="1"
                    onClick={(event) => {
                      if (event.detail > 1) return;
                      if (leaveBox() === "blocked") return;
                      const nextDraft = { start_s: region.start_s, end_s: region.end_s };
                      const line = noteLine(region.what, region.who);
                      editingRef.current = regionIndex;
                      draftRef.current = nextDraft;
                      saidRef.current = line;
                      setEditing(regionIndex);
                      setDraft(nextDraft);
                      setSaid(line);
                      if (audioRef.current) {
                        audioRef.current.currentTime = region.start_s;
                        void audioRef.current.play();
                      }
                    }}
                    style={{ borderColor: colorFor(region.what), background: `${colorFor(region.what)}33` }}
                  >
                    {region.start_s.toFixed(1)}–{region.end_s.toFixed(1)}s
                  </button>
                  <span style={{ flex: 1 }}>{noteLine(region.what, region.who)}</span>
                  <button
                    type="button"
                    data-skip-save="1"
                    onClick={(event) => {
                      if (event.detail > 1) return;
                      editGen.current += 1;
                      const clip = itemRef.current;
                      if (!clip) return;
                      void save(
                        regionsRef.current.filter((_, regionAt) => regionAt !== regionIndex),
                        editGen.current,
                        clip,
                      );
                    }}
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          <div className="clip-nav">
            <button
              type="button"
              className="arrow-btn"
              aria-label="Previous clip"
              data-skip-save="1"
              disabled={index === 0}
              onPointerDown={(event) => {
                if (event.button !== 0 || index === 0) return;
                event.preventDefault();
                go(-1);
              }}
            >
              ←
            </button>
            <button
              type="button"
              className="arrow-btn finish"
              aria-label={lastClip ? "Finish clip" : "Finish and next"}
              data-skip-save="1"
              onPointerDown={(event) => {
                if (event.button !== 0) return;
                event.preventDefault();
                go(1);
              }}
            >
              {lastClip ? "Done" : "Finish"} <span aria-hidden="true">→</span>
            </button>
          </div>
          <p className="tag">
            <a href={otherHref}>{otherLabel}</a>
            {" · "}
            <a href="/voices">Voices</a>
          </p>
        </section>
      ) : (
        <p>No clips in the queue.</p>
      )}
      {error ? <p className="device">{error}</p> : null}
    </main>
  );
}

function EdgeNudge({
  label,
  seconds,
  disabled,
  onNudge,
}: {
  label: string;
  seconds: number;
  disabled?: boolean;
  onNudge: (direction: -1 | 1, step: number) => void;
}) {
  function press(direction: -1 | 1, event: React.PointerEvent<HTMLButtonElement>) {
    if (event.button !== 0 || disabled) return;
    const step = event.altKey ? 0.01 : 0.05;
    onNudge(direction, step);
    const timer = window.setInterval(() => onNudge(direction, step), 80);
    const stop = () => {
      window.clearInterval(timer);
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
    };
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
  }

  return (
    <div className="nudge">
      <button type="button" data-skip-save="1" aria-label={`${label} earlier`} disabled={disabled} onPointerDown={(event) => press(-1, event)}>
        ←
      </button>
      <div className="nudge-mid">
        <span className="tool-value">{seconds.toFixed(2)}</span>
        <span className="tool-kicker">{label}</span>
      </div>
      <button type="button" data-skip-save="1" aria-label={`${label} later`} disabled={disabled} onPointerDown={(event) => press(1, event)}>
        →
      </button>
    </div>
  );
}

function draw(
  canvas: HTMLCanvasElement,
  audio: AudioBuffer,
  regions: Region[],
  draft: Draft | null,
  editing: number | null,
  mark: number | null,
) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const data = audio.getChannelData(0);
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
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
  const xAt = (seconds: number) => Math.round((seconds / audio.duration) * width);
  regions.forEach((region, regionIndex) => {
    const span = regionIndex === editing && draft && draft.end_s > draft.start_s ? draft : region;
    const left = xAt(span.start_s);
    const right = xAt(span.end_s);
    const color = colorFor(region.what);
    ctx.fillStyle = regionIndex === editing ? `${color}88` : `${color}44`;
    ctx.fillRect(left, 8, Math.max(2, right - left), height - 16);
    ctx.strokeStyle = color;
    ctx.lineWidth = regionIndex === editing ? 3 : 1;
    ctx.strokeRect(left, 8, Math.max(2, right - left), height - 16);
    ctx.lineWidth = 1;
    if (right - left > 48) {
      ctx.fillStyle = "#ffffff";
      ctx.font = "12px ui-monospace, monospace";
      ctx.fillText(noteLine(region.what, region.who), left + 6, 24);
    }
  });
  if (draft && draft.end_s > draft.start_s) {
    const left = xAt(draft.start_s);
    const right = xAt(draft.end_s);
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 2;
    ctx.strokeRect(left, 4, Math.max(2, right - left), height - 8);
    ctx.lineWidth = 1;
  }
  if (mark != null && audio.duration > 0) {
    const x = xAt(mark);
    ctx.strokeStyle = "#7dffb3";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();
    ctx.lineWidth = 1;
  }
}
