"use client";

import { useEffect, useRef, useState, type PointerEvent, type RefObject } from "react";

type Loop = { start_s: number; end_s: number };

const VOLUME_KEY = "ohush-voice-volume";

const playback = new WeakMap<HTMLAudioElement, { ctx: AudioContext; gain: GainNode }>();

function playbackFor(audio: HTMLAudioElement) {
  const existing = playback.get(audio);
  if (existing) return existing;
  const ctx = new AudioContext();
  const source = ctx.createMediaElementSource(audio);
  const gain = ctx.createGain();
  source.connect(gain);
  gain.connect(ctx.destination);
  const created = { ctx, gain };
  playback.set(audio, created);
  return created;
}

function loopHint(loop: Loop | null, loopOn: boolean, duration: number | undefined) {
  if (!loop) return "No range";
  if (!loopOn) return "Off";
  const heard = duration && Number.isFinite(duration) ? duration : null;
  const whole = loop.start_s <= 0.05 && (heard == null || loop.end_s >= heard - 0.25);
  return whole ? "Whole clip" : "This box";
}

export function WaveTransport({
  src,
  audioRef,
  canvasRef,
  loop,
  loopByDefault,
  plain,
  waveHeight = 160,
  volumeControl = false,
  compact = false,
  /** Farm mode: always 1×, loop always on, no speed/loop chips. */
  simple = false,
  knownDuration,
  onDecoded,
  onPointerDown,
  onPointerMove,
  onPointerUp,
  onPointerCancel,
  onPointerLeave,
}: {
  src: string;
  audioRef: RefObject<HTMLAudioElement | null>;
  canvasRef: RefObject<HTMLCanvasElement | null>;
  loop: Loop | null;
  loopByDefault: boolean;
  plain?: boolean;
  waveHeight?: number;
  volumeControl?: boolean;
  /** Tighter controls for single-screen labelers. */
  compact?: boolean;
  simple?: boolean;
  /** Authoritative length when <audio>.duration is NaN/Infinity (common on WAV). */
  knownDuration?: number;
  onDecoded?: (buffer: AudioBuffer) => void;
  onPointerDown?: (event: PointerEvent<HTMLCanvasElement>) => void;
  onPointerMove?: (event: PointerEvent<HTMLCanvasElement>) => void;
  onPointerUp?: (event: PointerEvent<HTMLCanvasElement>) => void;
  onPointerCancel?: (event: PointerEvent<HTMLCanvasElement>) => void;
  onPointerLeave?: (event: PointerEvent<HTMLCanvasElement>) => void;
}) {
  const playheadRef = useRef<HTMLDivElement | null>(null);
  const gestureRef = useRef<{ x: number; y: number; moved: boolean } | null>(null);
  const timeRef = useRef<HTMLSpanElement | null>(null);
  const ofRef = useRef<HTMLSpanElement | null>(null);
  const lastTickTimeRef = useRef(0);
  const onDecodedRef = useRef(onDecoded);
  const loopRef = useRef(loop);
  const loopOnRef = useRef(loopByDefault);
  const knownDurRef = useRef(knownDuration);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1);
  const [loopOn, setLoopOn] = useState(simple ? true : loopByDefault);
  const [coarse, setCoarse] = useState(false);
  const [volume, setVolume] = useState(3);
  const volumeRef = useRef(3);
  const gainRef = useRef<GainNode | null>(null);
  onDecodedRef.current = onDecoded;
  loopRef.current = loop;
  loopOnRef.current = simple ? true : loopOn;
  knownDurRef.current = knownDuration;

  useEffect(() => {
    if (!simple) return;
    setRate(1);
    setLoopOn(true);
  }, [simple, src]);

  useEffect(() => {
    lastTickTimeRef.current = 0;
  }, [src]);

  function heardSeconds(audio: HTMLAudioElement | null) {
    const known = knownDurRef.current;
    if (known != null && Number.isFinite(known) && known > 0) return known;
    const d = audio?.duration;
    if (d != null && Number.isFinite(d) && d > 0) return d;
    return 0;
  }

  useEffect(() => {
    setCoarse(window.matchMedia("(pointer: coarse)").matches);
    const saved = Number(localStorage.getItem(VOLUME_KEY));
    if (Number.isFinite(saved) && saved >= 0.25 && saved <= 6) {
      volumeRef.current = saved;
      setVolume(saved);
    }
  }, []);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.src = src;
    audio.playbackRate = 1;
    setRate(1);
    setPlaying(false);
    let cancelled = false;
    let context: AudioContext | null = null;
    fetch(src)
      .then((res) => res.arrayBuffer())
      .then((buf) => {
        context = new AudioContext();
        return context.decodeAudioData(buf.slice(0));
      })
      .then((decoded) => {
        if (!cancelled) onDecodedRef.current?.(decoded);
      })
      .catch(() => undefined);
    let startPlay: (() => void) | null = null;
    if (plain) {
      startPlay = () => {
        void audio.play().catch(() => undefined);
      };
      audio.addEventListener("canplay", startPlay);
    }
    return () => {
      cancelled = true;
      if (startPlay) audio.removeEventListener("canplay", startPlay);
      void context?.close();
    };
  }, [src, audioRef, plain]);

  useEffect(() => {
    const audio = audioRef.current;
    if (audio) audio.playbackRate = rate;
  }, [rate, audioRef, src]);

  useEffect(() => {
    if (!volumeControl) return;
    const audio = audioRef.current;
    if (!audio) return;
    const graph = playbackFor(audio);
    graph.gain.gain.value = volumeRef.current;
    gainRef.current = graph.gain;
    const resume = () => void graph.ctx.resume();
    audio.addEventListener("play", resume);
    return () => {
      audio.removeEventListener("play", resume);
      gainRef.current = null;
    };
  }, [volumeControl, audioRef]);

  useEffect(() => {
    volumeRef.current = volume;
    if (gainRef.current) gainRef.current.gain.value = volume;
    const audio = audioRef.current;
    if (audio) audio.dataset.volume = volume.toFixed(2);
  }, [volume, audioRef]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    const onEnded = () => {
      const range = loopRef.current;
      if (loopOnRef.current && range) {
        audio.currentTime = range.start_s;
        void audio.play();
        return;
      }
      setPlaying(false);
    };
    audio.addEventListener("play", onPlay);
    audio.addEventListener("pause", onPause);
    audio.addEventListener("ended", onEnded);
    return () => {
      audio.removeEventListener("play", onPlay);
      audio.removeEventListener("pause", onPause);
      audio.removeEventListener("ended", onEnded);
    };
  }, [src, audioRef]);

  useEffect(() => {
    let frame = 0;
    const tick = () => {
      const audio = audioRef.current;
      const line = playheadRef.current;
      const label = timeRef.current;
      const range = loopRef.current;
      if (audio && line) {
        // Only wrap when playback crosses the end — not when the user seeks past a short range.
        if (
          loopOnRef.current &&
          range &&
          audio.currentTime >= range.end_s - 0.02 &&
          lastTickTimeRef.current < range.end_s - 0.02 &&
          lastTickTimeRef.current >= range.start_s - 0.05
        ) {
          audio.currentTime = range.start_s;
        }
        lastTickTimeRef.current = audio.currentTime;
        const duration = heardSeconds(audio);
        const at = audio.currentTime || 0;
        if (duration > 0) {
          line.style.left = `${Math.min(100, Math.max(0, (at / duration) * 100))}%`;
          if (ofRef.current) ofRef.current.textContent = `of ${duration.toFixed(0)}s`;
        }
        if (label) label.textContent = at.toFixed(2);
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [src, audioRef, knownDuration]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.code !== "Space") return;
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "BUTTON" || tag === "SELECT") return;
      event.preventDefault();
      const audio = audioRef.current;
      if (!audio) return;
      if (audio.paused) void audio.play();
      else audio.pause();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [audioRef]);

  function toggle() {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) void audio.play();
    else audio.pause();
  }

  function plainDown(event: PointerEvent<HTMLDivElement>) {
    event.currentTarget.setPointerCapture(event.pointerId);
    gestureRef.current = { x: event.clientX, y: event.clientY, moved: false };
  }

  function plainMove(event: PointerEvent<HTMLDivElement>) {
    const gesture = gestureRef.current;
    if (!gesture || !event.currentTarget.hasPointerCapture(event.pointerId)) return;
    if (Math.hypot(event.clientX - gesture.x, event.clientY - gesture.y) > 12) gesture.moved = true;
    if (gesture.moved) seek(event.clientX, event.currentTarget);
  }

  function plainUp() {
    const gesture = gestureRef.current;
    gestureRef.current = null;
    if (gesture && !gesture.moved) toggle();
  }

  function seek(clientX: number, element: HTMLElement) {
    const audio = audioRef.current;
    if (!audio) return;
    const rect = element.getBoundingClientRect();
    const fraction = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    const duration = heardSeconds(audio);
    if (duration <= 0) return;
    audio.currentTime = fraction * duration;
  }

  const ownsWavePointers = Boolean(onPointerDown);

  if (plain) {
    return (
      <div className="wave-plain">
        <div
          className="wave-plain-stage"
          role="group"
          aria-label={playing ? "Playing. Tap to pause, drag to move." : "Tap to hear. Drag to move."}
          onPointerDown={plainDown}
          onPointerMove={plainMove}
          onPointerUp={plainUp}
          onPointerCancel={plainUp}
        >
          <canvas ref={canvasRef} width={840} height={220} className="wave-canvas" />
          <div ref={playheadRef} className="wave-plain-head" aria-hidden />
          <span ref={timeRef} className="wave-plain-time">
            0.00
          </span>
          {playing ? null : (
            <div className="wave-plain-hint" aria-hidden>
              Tap to hear
            </div>
          )}
        </div>
        <audio ref={audioRef} preload="auto" playsInline />
      </div>
    );
  }

  const h = compact || simple ? Math.min(waveHeight, simple ? 110 : 72) : waveHeight;
  const hideTransportChips = simple || compact;

  return (
    <div
      className={simple ? "farm-wave-transport" : undefined}
      style={{ display: "flex", flexDirection: "column", gap: simple ? 0 : hideTransportChips ? "0.3rem" : "0.55rem" }}
    >
      <div
        className={simple ? "farm-wave-stage" : undefined}
        style={
          simple
            ? undefined
            : {
                display: "flex",
                background: "#1a1024",
                borderRadius: 8,
                overflow: "hidden",
              }
        }
      >
        <button
          type="button"
          className={simple ? "farm-side-col farm-play-col" : undefined}
          onClick={toggle}
          aria-label={playing ? "Pause" : "Play"}
          style={
            simple
              ? undefined
              : {
                  width: hideTransportChips ? 44 : 56,
                  border: 0,
                  borderRight: "1px solid rgba(255,255,255,0.12)",
                  background: "transparent",
                  color: "#7dffb3",
                  fontSize: hideTransportChips ? "1.15rem" : "1.4rem",
                  cursor: "pointer",
                }
          }
        >
          {playing ? "❚❚" : "▶"}
        </button>
        <div className={simple ? "farm-wave-pane" : undefined} style={{ position: "relative", flex: 1, minWidth: 0 }}>
          <canvas
            ref={canvasRef}
            width={840}
            height={h}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerCancel}
            onPointerLeave={onPointerLeave}
            className="wave-canvas"
            style={{ width: "100%", height: h, display: "block", touchAction: "none" }}
          />
          {/* Only use the seek overlay when the parent does not own wave pointers —
              otherwise it fights grab-drags and seeks with a wrong duration. */}
          {ownsWavePointers ? null : (
            <div
              className="wave-seek"
              onPointerDown={(event) => {
                event.currentTarget.setPointerCapture(event.pointerId);
                seek(event.clientX, event.currentTarget);
              }}
              onPointerMove={(event) => {
                if (event.currentTarget.hasPointerCapture(event.pointerId)) seek(event.clientX, event.currentTarget);
              }}
            />
          )}
          <div
            ref={playheadRef}
            aria-hidden
            style={{
              position: "absolute",
              top: 0,
              bottom: 0,
              left: 0,
              width: 2,
              background: "#7dffb3",
              boxShadow: "0 0 8px #7dffb3",
              pointerEvents: "none",
            }}
          />
        </div>
      </div>
      {simple ? (
        <div className="farm-simple-meta">
          {volumeControl ? (
            <label className="farm-vol">
              <span className="farm-vol-icon" aria-hidden>
                {volume <= 0.3 ? "🔇" : volume < 1.5 ? "🔈" : volume < 3.5 ? "🔉" : "🔊"}
              </span>
              <input
                type="range"
                min={0.25}
                max={6}
                step={0.05}
                value={volume}
                aria-label={`Volume ${volume.toFixed(1)}×`}
                onChange={(event) => {
                  const next = Number(event.target.value);
                  volumeRef.current = next;
                  setVolume(next);
                  localStorage.setItem(VOLUME_KEY, String(next));
                }}
              />
            </label>
          ) : (
            <span />
          )}
          <span className="farm-simple-time" aria-live="polite">
            <span ref={timeRef}>0.00</span>
            <span ref={ofRef}>
              {" "}
              of {knownDuration && knownDuration > 0 ? `${knownDuration.toFixed(0)}s` : "…"}
            </span>
          </span>
        </div>
      ) : (
        <>
          <div className="tool-row">
            <button type="button" className={rate === 1 ? "tool-card on" : "tool-card"} onClick={() => setRate(1)}>
              <span className="tool-value">1×</span>
              <span className="tool-kicker">Full</span>
            </button>
            <button type="button" className={rate === 0.5 ? "tool-card on" : "tool-card"} onClick={() => setRate(0.5)}>
              <span className="tool-value">½×</span>
              <span className="tool-kicker">Slower</span>
            </button>
            <button
              type="button"
              className={loopOn && loop ? "tool-card on" : "tool-card"}
              disabled={!loop}
              onClick={() => setLoopOn((value) => !value)}
            >
              <span className="tool-value">Loop</span>
              <span className="tool-kicker">
                {loopHint(loop, loopOn, knownDuration ?? audioRef.current?.duration)}
              </span>
            </button>
            <div className="tool-card read" aria-live="polite">
              <span className="tool-value" ref={timeRef}>
                0.00
              </span>
              <span className="tool-kicker" ref={ofRef}>
                of {knownDuration && knownDuration > 0 ? `${knownDuration.toFixed(0)}s` : "…"}
              </span>
            </div>
            {volumeControl ? (
              <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", minWidth: "6.5rem", flex: 1 }}>
                <span style={{ minWidth: "6.5rem" }}>Volume {volume.toFixed(1)}×</span>
                <input
                  type="range"
                  min={0.25}
                  max={6}
                  step={0.05}
                  value={volume}
                  aria-label={`Volume ${volume.toFixed(1)}×`}
                  onChange={(event) => {
                    const next = Number(event.target.value);
                    volumeRef.current = next;
                    setVolume(next);
                    localStorage.setItem(VOLUME_KEY, String(next));
                  }}
                  style={{ flex: 1, accentColor: "#7dffb3" }}
                />
              </label>
            ) : null}
          </div>
        </>
      )}
      <audio ref={audioRef} preload="auto" playsInline controls={coarse} />
    </div>
  );
}
