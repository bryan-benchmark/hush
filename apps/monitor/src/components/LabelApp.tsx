"use client";

import {
  PointerEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { BrandMark } from "@/components/BrandMark";

type Evidence = {
  silence_bonus?: number;
  jump_z?: number;
  flux_raw?: number;
  norm?: {
    scope?: string;
    jump_mean?: number;
    jump_std?: number;
    flux_mean?: number;
    flux_std?: number;
  };
};

type Candidate = {
  proposal_id: string;
  elapsed_seconds: number;
  score: number;
  near_silence: boolean;
  session: string;
  file: string;
  chunk_elapsed_seconds: number;
  labeled: boolean;
  started_at?: string | null;
  flux_z?: number;
  loudness_jump_db?: number;
  rms_dbfs?: number;
  suggested_out_seconds?: number | null;
  evidence?: Evidence;
  frame_index?: number;
  sample_index?: number;
  session_sample_index?: number;
  params_hash?: string;
  fades?: Array<{ elapsed_seconds: number }>;
};

type FadeHint = { elapsed: number; depth: number };
type RunInfo = { run_id: string; keeps: number | null; detector_id: string | null };
type QueueItem = {
  stratum: string;
  proposal_id?: string | null;
  session: string;
  elapsed_seconds?: number;
  window_start?: number;
  window_duration?: number;
  score?: number;
  note?: string;
};
type SessionInfo = {
  session: string;
  audio_seconds: number | null;
  started_at: string | null;
  sample_rate_hz: number;
};
type TruthEvent = {
  gold_id: string;
  session: string;
  start_seconds: number;
  end_seconds: number;
  event_class?: string;
  desired_action?: string;
  confidence?: string;
  created_at?: string;
};
type CoverageRange = {
  session: string;
  from_seconds: number;
  to_seconds: number;
  fully_annotated?: boolean;
};

const EVENT_CLASSES = ["commercial", "network_promo", "sponsorship", "other"] as const;
const ACTIONS = ["mute", "play", "unsure"] as const;

const PRE_ROLL = 12;
const POST_ROLL = 210;
/** Waveform view length (peaks only — cheap). */
const VIEW_WINDOW_S = 600;
/**
 * Playable audio clip length. A 10‑min 48kHz WAV is ~55MB and re-buffers on every
 * seek; keep audio short and seek inside it, reloading only when you jump out.
 */
const AUDIO_WINDOW_S = 120;
const AUDIO_PREROLL_S = 15;
const JUMP_STEPS = [
  { sec: 10, label: "10s" },
  { sec: 30, label: "30s" },
  { sec: 60, label: "1m" },
  { sec: 300, label: "5m" },
] as const;

type AudioDebugLine = { t: string; event: string; detail?: string };

function audioLog(event: string, detail: Record<string, unknown> = {}) {
  const t = new Date().toISOString().slice(11, 23);
  console.log(`[hush-audio ${t}]`, event, detail);
  // Scrubbing used to post one of these per pixel and crash the page when a
  // log request failed. A log must never interrupt labeling.
  if (
    event === "ensure_audio_seek" ||
    event === "seek_in_clip" ||
    event === "audio_element_progress" ||
    event === "audio_element_waiting" ||
    event === "audio_element_playing" ||
    event === "audio_element_canplay" ||
    event === "audio_element_loadeddata" ||
    event === "audio_element_loadstart"
  ) {
    return;
  }
  void fetch("/api/client-log", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event, ...detail }),
  }).catch(() => {});
}
const ERROR_TAGS = [
  "",
  "silence_false",
  "music_swell",
  "station_id",
  "in_early",
  "in_late",
  "out_early",
  "out_late",
  "missed_break",
  "other",
];

function pad(n: number) {
  return String(n).padStart(2, "0");
}

function wallClock(startedAt: string, elapsedSec: number) {
  const d = new Date(Date.parse(startedAt) + elapsedSec * 1000);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function fmtClip(sec: number) {
  const s = Math.max(0, sec);
  const m = Math.floor(s / 60);
  const r = s - m * 60;
  return `${m}:${r.toFixed(1).padStart(4, "0")}`;
}

function sessionIsFinished(session: string, ranges: CoverageRange[]) {
  return ranges.some((r) => r.session === session && r.fully_annotated !== false);
}

function pickOpenSession(list: SessionInfo[], ranges: CoverageRange[], current = "") {
  if (current && list.some((s) => s.session === current) && !sessionIsFinished(current, ranges)) {
    return current;
  }
  const open = list.find((s) => !sessionIsFinished(s.session, ranges));
  return open?.session || list[0]?.session || "";
}

type DragKind = "in" | "out" | "playhead" | null;

type WaveLaneData = {
  peak: number[];
  rms: number[];
  jump: number[];
  bright: number[];
  hi: number[];
  lo: number[];
};

const WAVE_ROWS: Array<{
  id: keyof WaveLaneData | "wave";
  label: string;
  hint: string;
  kind: "bars" | "bipolar";
  tone: string;
}> = [
  { id: "wave", label: "Wave", hint: "Actual bipolar audio shape", kind: "bipolar", tone: "wave" },
  { id: "peak", label: "Peak", hint: "Max amplitude envelope", kind: "bars", tone: "peak" },
  { id: "rms", label: "Loud", hint: "RMS loudness (smooth energy)", kind: "bars", tone: "rms" },
  { id: "jump", label: "Jump", hint: "Loudness changes — cuts & hits", kind: "bars", tone: "jump" },
  { id: "bright", label: "Edge", hint: "Sample-to-sample edge / brightness", kind: "bars", tone: "bright" },
];

const REPLICATION_TASKS = [
  {
    session: "hush_20260924_220624",
    title: "1 · Prime football",
    hint: "Listen from the start through 2:06:40. The quiet tail after that is not part of this job.",
    t0: 0,
    t1: 7600,
  },
  {
    session: "hush_20260827_135935",
    title: "2 · Hulu · Gilmore Girls",
    hint: "This opens at 5:00. Listen through 2:00:00. Saved times are on the recording clock.",
    t0: 300,
    t1: 7200,
  },
] as const;

export function LabelApp({ task }: { task?: "replication" }) {
  const [mode, setMode] = useState<"debug" | "timeline">("timeline");
  const replication = task === "replication";
  const coverageManifest = replication ? "GOLD_REPLICATION_V1" : "GOLD_DEV_V1";
  const spanRef = useRef<(typeof REPLICATION_TASKS)[number] | null>(null);
  const [runs, setRuns] = useState<RunInfo[]>([]);
  const [runId, setRunId] = useState("");
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [idx, setIdx] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [errorTag, setErrorTag] = useState("");
  const [saving, setSaving] = useState(false);

  const [windowStart, setWindowStart] = useState(0);
  const [windowDur, setWindowDur] = useState(VIEW_WINDOW_S);
  const [inPoint, setInPoint] = useState(0);
  const [outPoint, setOutPoint] = useState(0);
  const [shownIn, setShownIn] = useState<number | null>(null);
  const [shownOut, setShownOut] = useState<number | null>(null);
  const [playhead, setPlayhead] = useState(0);
  const [peaks, setPeaks] = useState<number[]>([]);
  const [waveLanes, setWaveLanes] = useState<WaveLaneData | null>(null);
  const [fades, setFades] = useState<FadeHint[]>([]);
  const [suggestedOut, setSuggestedOut] = useState<number | null>(null);
  const [loopSelection, setLoopSelection] = useState(false);
  const [postRoll, setPostRoll] = useState(POST_ROLL);

  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [timelineSession, setTimelineSession] = useState("");
  spanRef.current = replication
    ? (REPLICATION_TASKS.find((row) => row.session === timelineSession) ?? null)
    : null;
  const [timelineStart, setTimelineStart] = useState(0);
  const [coverageFrom, setCoverageFrom] = useState(0);
  const [coverageTo, setCoverageTo] = useState(3600);
  const [hideFinished, setHideFinished] = useState(true);
  const [queueOnly, setQueueOnly] = useState(true);
  const [queueIds, setQueueIds] = useState<string[]>([]);
  const [queueItems, setQueueItems] = useState<QueueItem[]>([]);
  const [withheld, setWithheld] = useState<Array<{ session: string; role: string }>>([]);
  const [truthEvents, setTruthEvents] = useState<TruthEvent[]>([]);
  const [coverageRanges, setCoverageRanges] = useState<CoverageRange[]>([]);
  const [overlay, setOverlay] = useState(false);
  const [allDoneAck, setAllDoneAck] = useState(false);
  const [eventClass, setEventClass] = useState<(typeof EVENT_CLASSES)[number]>("commercial");
  const [desiredAction, setDesiredAction] = useState<(typeof ACTIONS)[number]>("mute");
  const [confidence, setConfidence] = useState<"certain" | "unsure">("certain");
  const [pendingIn, setPendingIn] = useState<number | null>(null);
  const [lastSaved, setLastSaved] = useState<string | null>(null);
  const [audioBusy, setAudioBusy] = useState(false);
  const [audioPlaying, setAudioPlaying] = useState(false);
  const [audioClipStart, setAudioClipStart] = useState(0);
  const [audioDebug, setAudioDebug] = useState<AudioDebugLine[]>([]);
  const [mounted, setMounted] = useState(false);

  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const timelineRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<DragKind>(null);
  const pendingSlotRef = useRef<{ in: number; out: number } | null>(null);
  const seekTargetRef = useRef<number | null>(null);
  const playheadRef = useRef(0);
  const windowStartRef = useRef(0);
  const windowDurRef = useRef(VIEW_WINDOW_S);
  const audioClipStartRef = useRef(0);
  const audioClipDurRef = useRef(AUDIO_WINDOW_S);
  const audioReloadRef = useRef(false);
  const lastProgressLogRef = useRef(0);
  const alignedSessionRef = useRef<string | null>(null);
  const openedSessionRef = useRef<string | null>(null);
  const viewFollowBusyRef = useRef(false);
  const sessionsRef = useRef(sessions);
  const hideFinishedRef = useRef(hideFinished);
  sessionsRef.current = sessions;
  hideFinishedRef.current = hideFinished;

  // Stable logger — must NOT be an effect dependency (setState would retrigger effects).
  const logUi = useCallback((event: string, detail: Record<string, unknown> = {}) => {
    audioLog(event, detail);
    // Keep React state updates rare so playback/seek logging cannot render-storm.
    const mirror =
      event.startsWith("journey_") ||
      event.includes("error") ||
      event === "peaks_fetch_done" ||
      event === "peaks_fetch_error" ||
      event === "audio_url_set";
    if (!mirror) return;
    const t = new Date().toISOString().slice(11, 23);
    const detailStr = Object.keys(detail).length
      ? Object.entries(detail)
          .map(([k, v]) => {
            const s =
              typeof v === "number" && Number.isFinite(v)
                ? Number.isInteger(v)
                  ? String(v)
                  : v.toFixed(3)
                : String(v);
            return `${k}=${s}`;
          })
          .join(" ")
      : undefined;
    setAudioDebug((prev) => [...prev.slice(-40), { t, event, detail: detailStr }]);
  }, []);
  const logUiRef = useRef(logUi);
  logUiRef.current = logUi;

  const unlabeled = useMemo(() => {
    const open = candidates.filter((c) => !c.labeled);
    if (!queueOnly || queueIds.length === 0) return open;
    const ids = new Set(queueIds);
    return open.filter((c) => ids.has(c.proposal_id));
  }, [candidates, queueOnly, queueIds]);
  const current = mode === "debug" ? (unlabeled[idx] ?? null) : null;
  const startedAt =
    current?.started_at ||
    sessions.find((s) => s.session === (current?.session || timelineSession))?.started_at ||
    "";
  const labeledCount = candidates.length - unlabeled.length;

  const loadRuns = useCallback(async () => {
    try {
      const res = await fetch("/api/runs");
      if (!res.ok) throw new Error(`runs ${res.status}`);
      const data = await res.json();
      const list = (data.runs ?? []) as RunInfo[];
      setRuns(list);
      setRunId((prev) => prev || list[0]?.run_id || "");
    } catch (e) {
      // Transient HMR / server blips — don't crash the labeler shell.
      console.warn("[labeler] loadRuns failed", e);
      setRuns([]);
    }
  }, []);

  const loadSessions = useCallback(async () => {
    const attempt = async () => {
      const [sessRes, covRes] = await Promise.all([
        fetch("/api/sessions"),
        fetch(`/api/coverage?manifest=${coverageManifest}`),
      ]);
      if (!sessRes.ok) throw new Error(`sessions ${sessRes.status}`);
      const sessData = await sessRes.json();
      const covData = covRes.ok ? await covRes.json() : { coverage: [] };
      const all = (sessData.sessions ?? []) as SessionInfo[];
      const list = replication
        ? REPLICATION_TASKS.flatMap((job) => all.filter((row) => row.session === job.session))
        : all;
      const ranges = (covData.coverage ?? []) as CoverageRange[];
      setSessions(list);
      setCoverageRanges(ranges);
      setTimelineSession((prev) => {
        const next = pickOpenSession(list, ranges, prev);
        const job = REPLICATION_TASKS.find((row) => row.session === next);
        if (replication && job) setTimelineStart(job.t0);
        return next;
      });
      setError(null);
    };
    try {
      await attempt();
    } catch (e1) {
      // One retry after a short wait — covers Next HMR / route compile races.
      await new Promise((r) => setTimeout(r, 400));
      try {
        await attempt();
      } catch (e) {
        console.warn("[labeler] loadSessions failed", e1, e);
        setError(e instanceof Error ? e.message : "Failed to load sessions");
      }
    }
  }, [coverageManifest, replication]);

  const loadCandidates = useCallback(async (id: string) => {
    if (!id) {
      setCandidates([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/candidates?run_id=${encodeURIComponent(id)}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "load failed");
      setCandidates(data.candidates ?? []);
      setWithheld(data.withheld ?? []);
      setIdx(0);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const boot = async () => {
      // Blind timeline needs sessions; runs are optional (debug queue only).
      await loadSessions();
      if (cancelled) return;
      await loadRuns();
    };
    void boot();
    return () => {
      cancelled = true;
    };
  }, [loadRuns, loadSessions]);

  useEffect(() => {
    if (runId) void loadCandidates(runId);
  }, [runId, loadCandidates]);

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    fetch(`/api/queue?run_id=${encodeURIComponent(runId)}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`queue ${r.status}`))))
      .then((data) => {
        if (cancelled) return;
        const items = (data.items ?? []) as QueueItem[];
        setQueueItems(items);
        setQueueIds(items.map((item) => item.proposal_id).filter((id): id is string => Boolean(id)));
      })
      .catch((e) => {
        console.warn("[labeler] loadQueue failed", e);
        if (!cancelled) {
          setQueueIds([]);
          setQueueItems([]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [runId]);

  const refreshTruth = useCallback(async (session: string) => {
    if (!session) {
      setTruthEvents([]);
      return;
    }
    const res = await fetch(`/api/truth?session=${encodeURIComponent(session)}`);
    const data = await res.json();
    setTruthEvents((data.truth_events ?? []) as TruthEvent[]);
  }, []);

  useEffect(() => {
    if (mode !== "timeline" || !timelineSession) return;
    // Hard gate: same session must not re-open on every render/HMR dep flap.
    if (openedSessionRef.current === timelineSession) return;
    openedSessionRef.current = timelineSession;
    let cancelled = false;
    logUiRef.current("journey_open_session", {
      session: timelineSession,
      hide_finished: hideFinishedRef.current,
    });
    void refreshTruth(timelineSession)
      .then(() => {
        if (!cancelled) logUiRef.current("journey_truth_loaded", { session: timelineSession });
      })
      .catch(() => {
        if (!cancelled) setTruthEvents([]);
      });
    fetch(`/api/coverage?manifest=${coverageManifest}`)
      .then((r) => r.json())
      .then((data) => {
        if (cancelled) return;
        const ranges = (data.coverage ?? []) as CoverageRange[];
        setCoverageRanges(ranges);
        if (sessionIsFinished(timelineSession, ranges) && hideFinishedRef.current) {
          const next = pickOpenSession(sessionsRef.current, ranges, "");
          if (next && next !== timelineSession) {
            logUiRef.current("journey_skip_finished", {
              from: timelineSession,
              to: next,
            });
            openedSessionRef.current = null;
            alignedSessionRef.current = null;
            setTimelineSession(next);
            setTimelineStart(REPLICATION_TASKS.find((row) => row.session === next)?.t0 ?? 0);
          }
        }
      })
      .catch(() => {
        if (!cancelled) setCoverageRanges([]);
      });
    return () => {
      cancelled = true;
    };
  }, [coverageManifest, mode, timelineSession, refreshTruth]);

  useEffect(() => {
    if (mode !== "debug" || !current) {
      if (mode === "debug") {
        setAudioUrl(null);
        setPeaks([]);
        setWaveLanes(null);
      }
      return;
    }

    const inAbs = current.elapsed_seconds;
    const suggested = current.suggested_out_seconds ?? null;
    const ws = Math.max(0, inAbs - PRE_ROLL);
    const dur = PRE_ROLL + postRoll;
    setWindowStart(ws);
    setWindowDur(dur);
    setInPoint(inAbs);
    setShownIn(inAbs);
    setShownOut(suggested);
    setSuggestedOut(suggested);
    setOutPoint(suggested ?? inAbs + Math.min(150, postRoll - 5));
    setPlayhead(inAbs);
    setNote("");
    setFades(
      (current.fades ?? []).map((fade) => ({ elapsed: fade.elapsed_seconds, depth: 0 })),
    );

    const q =
      `session=${encodeURIComponent(current.session)}` +
      `&mode=break&start=${ws}&duration=${dur}&in=${inAbs}` +
      `&run_id=${encodeURIComponent(runId)}` +
      `&proposal_id=${encodeURIComponent(current.proposal_id)}`;
    setAudioUrl(`/api/audio?${q}`);

    let cancelled = false;
    fetch(`/api/peaks?${q}&buckets=360&lanes=1`)
      .then((r) => r.json())
      .then((d) => {
        if (cancelled) return;
        setPeaks(d.peaks ?? []);
        setWaveLanes((d.lanes as WaveLaneData | undefined) ?? null);
        if (d.hints?.fades) setFades(d.hints.fades);
      })
      .catch(() => undefined);

    const t = window.setTimeout(() => {
      audioRef.current?.play().catch(() => undefined);
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [current, postRoll, mode, runId]);

  useEffect(() => {
    playheadRef.current = playhead;
  }, [playhead]);

  useEffect(() => {
    windowStartRef.current = windowStart;
    windowDurRef.current = windowDur;
  }, [windowStart, windowDur]);

  useEffect(() => {
    audioClipStartRef.current = audioClipStart;
  }, [audioClipStart]);

  // Waveform / view window — peaks only, does not reload playable audio.
  useEffect(() => {
    if (mode !== "timeline" || !timelineSession) return;
    const ws = Math.max(0, timelineStart);
    const dur = VIEW_WINDOW_S;
    setWindowStart(ws);
    setWindowDur(dur);
    windowStartRef.current = ws;
    windowDurRef.current = dur;
    const pending = pendingSlotRef.current;
    if (pending) {
      setInPoint(pending.in);
      setOutPoint(pending.out);
      setPlayhead(pending.in);
      playheadRef.current = pending.in;
      seekTargetRef.current = pending.in;
      pendingSlotRef.current = null;
    }
    setShownIn(null);
    setShownOut(null);
    setSuggestedOut(null);
    setFades([]);
    const q =
      `session=${encodeURIComponent(timelineSession)}` +
      `&mode=timeline&start=${ws}&duration=${dur}`;
    const t0 = performance.now();
    logUiRef.current("peaks_fetch_begin", {
      session: timelineSession,
      view_start: ws,
      view_dur: dur,
    });
    let cancelled = false;
    fetch(`/api/peaks?${q}&buckets=480&lanes=1`)
      .then((r) => r.json())
      .then((d) => {
        if (cancelled) return;
        setPeaks(d.peaks ?? []);
        setWaveLanes((d.lanes as WaveLaneData | undefined) ?? null);
        logUiRef.current("peaks_fetch_done", {
          ms: Math.round(performance.now() - t0),
          bins: (d.peaks ?? []).length,
          lanes: d.lanes ? Object.keys(d.lanes).length : 0,
        });
      })
      .catch((e) => {
        logUiRef.current("peaks_fetch_error", { error: String(e) });
      });
    return () => {
      cancelled = true;
    };
  }, [mode, timelineSession, timelineStart]);

  // Playable audio — short clip; reload only when audioClipStart changes.
  useEffect(() => {
    if (mode !== "timeline" || !timelineSession) return;
    // Quantize for server cache hits across Range requests / tiny float drift.
    const start = Math.round(Math.max(0, audioClipStart) * 10) / 10;
    audioClipStartRef.current = start;
    audioClipDurRef.current = AUDIO_WINDOW_S;
    audioReloadRef.current = true;
    setAudioBusy(true);
    const q =
      `session=${encodeURIComponent(timelineSession)}` +
      `&mode=timeline&start=${start}&duration=${AUDIO_WINDOW_S}`;
    const url = `/api/audio?${q}`;
    logUiRef.current("audio_url_set", {
      reason: "audioClipStart_effect",
      session: timelineSession,
      clip_start: start,
      clip_dur: AUDIO_WINDOW_S,
      seek_target: seekTargetRef.current,
      playhead: playheadRef.current,
      url,
    });
    setAudioUrl(url);
  }, [mode, timelineSession, audioClipStart]);

  // Align playable clip only when the recording actually changes (not every view jump).
  useEffect(() => {
    if (mode !== "timeline" || !timelineSession) return;
    if (alignedSessionRef.current === timelineSession) return;
    alignedSessionRef.current = timelineSession;
    const start = Math.round(Math.max(0, timelineStart) * 10) / 10;
    logUiRef.current("session_align_audio", {
      session: timelineSession,
      timeline_start: start,
      note: "first open of this session only",
    });
    seekTargetRef.current = start;
    setPlayhead(start);
    playheadRef.current = start;
    setAudioClipStart(start);
    audioClipStartRef.current = start;
  }, [mode, timelineSession, timelineStart]);

  useEffect(() => {
    const a = audioRef.current;
    if (!a) return;
    const onTime = () => {
      let abs = audioClipStartRef.current + a.currentTime;
      const span = spanRef.current;
      if (span && abs >= span.t1) {
        a.pause();
        abs = span.t1;
      }
      setPlayhead(abs);
      playheadRef.current = abs;
      if (loopSelection && abs >= outPoint) {
        a.currentTime = Math.max(0, inPoint - audioClipStartRef.current);
      }

      // Keep the 10‑min wave view scrolling with playback (otherwise the
      // playhead pins to the right edge while the clock keeps advancing).
      const ws = windowStartRef.current;
      const dur = windowDurRef.current;
      const viewEnd = ws + dur;
      const rightMargin = Math.min(90, dur * 0.12);
      if (!viewFollowBusyRef.current && abs > viewEnd - rightMargin) {
        const next = Math.round(Math.max(0, abs - dur * 0.25) * 10) / 10;
        if (next > ws + 15) {
          viewFollowBusyRef.current = true;
          logUiRef.current("view_follow_scroll", {
            abs,
            old_view_start: ws,
            new_view_start: next,
            view_end: viewEnd,
          });
          setTimelineStart(next);
          // Peaks fetch is async; unlock after a beat so we don't stack scrolls.
          window.setTimeout(() => {
            viewFollowBusyRef.current = false;
          }, 800);
        }
      }

      // Quietly slide the playable clip forward before it ends.
      const clipEnd = audioClipStartRef.current + audioClipDurRef.current;
      // Slide clip only when truly near the end (avoid reload thrash).
      if (abs > clipEnd - 8 && !audioReloadRef.current) {
        const next = Math.round(Math.max(0, abs - AUDIO_PREROLL_S) * 10) / 10;
        if (next > audioClipStartRef.current + 20) {
          audioReloadRef.current = true;
          logUiRef.current("audio_prefetch_slide", {
            reason: "near_clip_end",
            abs,
            clip_end: clipEnd,
            next_clip_start: next,
          });
          seekTargetRef.current = abs;
          setAudioClipStart(next);
        }
      }
    };
    const onWaiting = () =>
      logUi("audio_element_waiting", {
        currentTime: a.currentTime,
        readyState: a.readyState,
        networkState: a.networkState,
        clip_start: audioClipStartRef.current,
      });
    const onStalled = () =>
      logUi("audio_element_stalled", {
        currentTime: a.currentTime,
        readyState: a.readyState,
      });
    const onError = () =>
      logUi("audio_element_error", {
        code: a.error?.code,
        message: a.error?.message,
      });
    const onPlay = () => setAudioPlaying(true);
    const onPause = () => setAudioPlaying(false);
    a.addEventListener("timeupdate", onTime);
    a.addEventListener("waiting", onWaiting);
    a.addEventListener("stalled", onStalled);
    a.addEventListener("error", onError);
    a.addEventListener("play", onPlay);
    a.addEventListener("playing", onPlay);
    a.addEventListener("pause", onPause);
    a.addEventListener("ended", onPause);
    setAudioPlaying(!a.paused);
    return () => {
      a.removeEventListener("timeupdate", onTime);
      a.removeEventListener("waiting", onWaiting);
      a.removeEventListener("stalled", onStalled);
      a.removeEventListener("error", onError);
      a.removeEventListener("play", onPlay);
      a.removeEventListener("playing", onPlay);
      a.removeEventListener("pause", onPause);
      a.removeEventListener("ended", onPause);
    };
  }, [inPoint, outPoint, loopSelection, audioUrl]);

  function togglePlayPause() {
    const a = audioRef.current;
    if (!a) {
      ensureAudio(playheadRef.current);
      return;
    }
    if (a.paused) void a.play().catch((e) => logUi("play_error", { error: String(e) }));
    else a.pause();
  }

  function switchSession(
    next: string,
    startAt = replication
      ? (REPLICATION_TASKS.find((row) => row.session === next)?.t0 ?? 0)
      : 0,
  ) {
    if (!next) return;
    if (next !== timelineSession) {
      openedSessionRef.current = null;
      alignedSessionRef.current = null;
      setTimelineSession(next);
    }
    setTimelineStart(startAt);
    setPendingIn(null);
  }

  function absToPct(abs: number) {
    return ((abs - windowStart) / windowDur) * 100;
  }

  function clientXToAbs(clientX: number, el?: HTMLElement | null) {
    const node = el ?? timelineRef.current;
    if (!node) return windowStart;
    const rect = node.getBoundingClientRect();
    const pct = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    const abs = windowStart + pct * windowDur;
    const span = spanRef.current;
    if (!span) return abs;
    return Math.min(span.t1, Math.max(span.t0, abs));
  }

  function seekAbs(abs: number) {
    const a = audioRef.current;
    const clip0 = audioClipStartRef.current;
    const offset = Math.max(0, abs - clip0);
    logUi("seek_in_clip", {
      abs,
      clip_start: clip0,
      offset,
      readyState: a?.readyState,
    });
    setPlayhead(abs);
    playheadRef.current = abs;
    seekTargetRef.current = abs;
    if (!a) return;
    try {
      a.currentTime = offset;
    } catch (e) {
      logUi("seek_error", { error: String(e) });
    }
    void a.play().catch((e) => logUi("play_error", { error: String(e) }));
  }

  /** Keep the 10‑min waveform under the playhead when needed. */
  function ensureView(target: number) {
    const ws = windowStartRef.current;
    const dur = windowDurRef.current;
    if (target >= ws + 5 && target <= ws + dur - 5) {
      return;
    }
    const floor = spanRef.current?.t0 ?? 0;
    const next = Math.max(floor, target - Math.min(90, dur * 0.25));
    logUiRef.current("ensure_view_shift", {
      target,
      old_view_start: ws,
      new_view_start: next,
      reason: "target_outside_waveform",
    });
    pendingSlotRef.current = { in: target, out: target + 0.25 };
    setTimelineStart(next);
  }

  /**
   * Seek inside the short playable clip when possible.
   * Reload only that ~2‑min clip when the target is outside it.
   */
  function ensureAudio(target: number) {
    const clip0 = audioClipStartRef.current;
    const clip1 = clip0 + audioClipDurRef.current;
    if (target >= clip0 + 0.5 && target <= clip1 - 2) {
      logUi("ensure_audio_seek", { target, clip_start: clip0, clip_end: clip1 });
      seekAbs(target);
      return;
    }
    const next = Math.round(Math.max(0, target - AUDIO_PREROLL_S) * 10) / 10;
    logUi("ensure_audio_reload", {
      target,
      old_clip_start: clip0,
      old_clip_end: clip1,
      new_clip_start: next,
      reason: "target_outside_playable_clip",
    });
    seekTargetRef.current = target;
    playheadRef.current = target;
    setPlayhead(target);
    setAudioClipStart(next);
  }

  function jumpAudio(deltaSec: number) {
    const from = playheadRef.current;
    const span = spanRef.current;
    const lo = span?.t0 ?? 0;
    const hi = span?.t1 ?? Number.POSITIVE_INFINITY;
    const target = Math.min(hi, Math.max(lo, from + deltaSec));
    logUi("journey_jump", { delta: deltaSec, from, target });
    ensureView(target);
    ensureAudio(target);
  }

  function onPointerDown(kind: DragKind, e: PointerEvent) {
    e.preventDefault();
    e.stopPropagation();
    dragRef.current = kind;
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
  }

  function onTimelinePointerDown(e: PointerEvent<HTMLDivElement>) {
    dragRef.current = "playhead";
    timelineRef.current = e.currentTarget;
    const abs = clientXToAbs(e.clientX, e.currentTarget);
    setPlayhead(abs);
    playheadRef.current = abs;
    e.currentTarget.setPointerCapture(e.pointerId);
  }

  function onPointerMove(e: PointerEvent) {
    if (!dragRef.current) return;
    const abs = clientXToAbs(e.clientX, timelineRef.current);
    if (dragRef.current === "in") {
      setInPoint(Math.min(abs, outPoint - 0.25));
    } else if (dragRef.current === "out") {
      setOutPoint(Math.max(abs, inPoint + 0.25));
    } else if (dragRef.current === "playhead") {
      setPlayhead(abs);
      playheadRef.current = abs;
    }
  }

  function onPointerUp() {
    const kind = dragRef.current;
    dragRef.current = null;
    if (kind === "playhead") {
      const abs = playheadRef.current;
      ensureView(abs);
      ensureAudio(abs);
    }
  }

  function nudge(which: "in" | "out", delta: number) {
    if (which === "in") {
      setInPoint((v) => Math.min(Math.max(windowStart, v + delta), outPoint - 0.1));
    } else {
      setOutPoint((v) => Math.max(Math.min(windowStart + windowDur, v + delta), inPoint + 0.1));
    }
  }

  function playSelection() {
    ensureAudio(inPoint);
  }

  async function saveReview(verdict: "ad_break" | "not_break" | "unsure") {
    if (!current) return;
    setSaving(true);
    setError(null);
    try {
      const payload = {
        run_id: runId,
        proposal_id: current.proposal_id,
        params_hash: current.params_hash ?? null,
        session: current.session,
        verdict,
        suggested_in_seconds: shownIn,
        suggested_out_seconds: shownOut,
        human_in_seconds: inPoint,
        human_out_seconds: outPoint,
        in_drag_delta_seconds: shownIn === null ? null : inPoint - shownIn,
        out_drag_delta_seconds: shownOut === null ? null : outPoint - shownOut,
        error_tag: errorTag || null,
        note: note.trim() || null,
        reviewer: reviewer.trim() || null,
      };
      const res = await fetch("/api/reviews", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "save failed");
      setCandidates((prev) =>
        prev.map((c) => (c.proposal_id === current.proposal_id ? { ...c, labeled: true } : c)),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "save failed");
    } finally {
      setSaving(false);
    }
  }

  async function saveTruth(start = inPoint, end = outPoint) {
    const session = timelineSession;
    if (!session || end - start < 5 || saving) return;
    const span = spanRef.current;
    if (span && (start < span.t0 || end > span.t1)) {
      setError("That mark is outside this recording's span.");
      return;
    }
    setSaving(true);
    setError(null);
    const t0 = performance.now();
    try {
      const rate = sessions.find((s) => s.session === session)?.sample_rate_hz ?? 48000;
      const res = await fetch("/api/truth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session,
          start_seconds: start,
          end_seconds: end,
          sample_rate_hz: rate,
          reviewer: reviewer.trim() || null,
          note: note.trim() || null,
          event_class: eventClass,
          desired_action: desiredAction,
          confidence,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "save failed");
      setNote("");
      setPendingIn(null);
      const stamp = sessions.find((s) => s.session === session)?.started_at;
      setLastSaved(
        stamp
          ? `${wallClock(stamp, start)} – ${wallClock(stamp, end)}`
          : `${fmtClip(start)}–${fmtClip(end)}`,
      );
      await refreshTruth(session);
      logUi("journey_save_ok", {
        session,
        start,
        end,
        ms: Math.round(performance.now() - t0),
      });
    } catch (e) {
      logUi("journey_save_error", { error: String(e) });
      setError(e instanceof Error ? e.message : "save failed");
    } finally {
      setSaving(false);
    }
  }

  function markBreakStart() {
    logUi("journey_mark_start", { at: playhead, session: timelineSession });
    setPendingIn(playhead);
    setLastSaved(null);
    setError(null);
  }

  function markBreakEnd() {
    if (pendingIn === null) return;
    if (playhead - pendingIn < 5) {
      logUi("journey_mark_end_rejected", {
        pending_in: pendingIn,
        playhead,
        reason: "too_short",
      });
      setError("Break is too short — keep listening, then tap End.");
      return;
    }
    logUi("journey_mark_end", {
      start: pendingIn,
      end: playhead,
      duration: playhead - pendingIn,
      session: timelineSession,
    });
    void saveTruth(pendingIn, playhead);
  }

  function cancelPending() {
    logUi("journey_mark_cancel", { pending_in: pendingIn });
    setPendingIn(null);
    setError(null);
  }

  async function retractTruth(goldId: string) {
    const session = timelineSession;
    if (!session) return;
    logUi("journey_delete", { session, gold_id: goldId });
    setSaving(true);
    setError(null);
    try {
      const res = await fetch("/api/truth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session,
          retract: true,
          supersedes: goldId,
          reviewer: reviewer.trim() || null,
          note: "retracted",
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "retract failed");
      await refreshTruth(session);
    } catch (e) {
      logUi("journey_delete_error", { error: String(e) });
      setError(e instanceof Error ? e.message : "retract failed");
    } finally {
      setSaving(false);
    }
  }

  async function closeCoverage(from = coverageFrom, to = coverageTo) {
    const session = timelineSession;
    if (!session) return;
    logUi("journey_mark_recording_complete", {
      session,
      from,
      to,
      n_commercials: sessionSlots.length,
    });
    setSaving(true);
    setError(null);
    try {
      const rate = sessions.find((s) => s.session === session)?.sample_rate_hz ?? 48000;
      const res = await fetch("/api/coverage", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          manifest: coverageManifest,
          session,
          from_seconds: from,
          to_seconds: to,
          sample_rate_hz: rate,
          fully_annotated: true,
          note: "Marked from timeline mode. No ad inside this range means no ad.",
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "coverage failed");
      setCoverageFrom(from);
      setCoverageTo(to);
      const nextRanges: CoverageRange[] = [
        ...coverageRanges,
        {
          session,
          from_seconds: from,
          to_seconds: to,
          fully_annotated: true,
        },
      ];
      setCoverageRanges(nextRanges);
      if (hideFinished) {
        const next = pickOpenSession(sessions, nextRanges, "");
        if (next && next !== session) {
          logUi("journey_advance_next_recording", { from: session, to: next });
          switchSession(next);
        }
      }
    } catch (e) {
      logUi("journey_complete_error", { error: String(e) });
      setError(e instanceof Error ? e.message : "coverage failed");
    } finally {
      setSaving(false);
    }
  }

  useEffect(() => {
    if (mode !== "timeline") return;
    function onKey(e: KeyboardEvent) {
      const tag = e.target instanceof HTMLElement ? e.target.tagName : "";
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      // Space = Start / End (capture so <audio> doesn't steal it for play/pause).
      if (e.code === "Space" || e.key === "[" || e.key === "b" || e.key === "B") {
        e.preventDefault();
        e.stopPropagation();
        if (saving || sessionIsFinished(timelineSession, coverageRanges)) return;
        if (pendingIn === null) markBreakStart();
        else markBreakEnd();
        return;
      }
      // k = play / pause
      if (e.key === "k" || e.key === "K") {
        e.preventDefault();
        const a = audioRef.current;
        if (!a) return;
        if (a.paused) void a.play();
        else a.pause();
        return;
      }
      if (e.key === "]") {
        e.preventDefault();
        markBreakEnd();
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        cancelPending();
      }
    }
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [
    mode,
    saving,
    timelineSession,
    coverageRanges,
    pendingIn,
  ]);

  const inPct = absToPct(inPoint);
  const outPct = absToPct(outPoint);
  const playPct = absToPct(playhead);
  const breakLen = outPoint - inPoint;
  const blind = mode === "timeline";
  const overlayAllowed = coverageRanges.some(
    (range) =>
      range.session === timelineSession &&
      range.fully_annotated !== false &&
      range.from_seconds <= windowStart &&
      range.to_seconds >= windowStart + windowDur,
  );
  const overlayMarks =
    blind && overlay && overlayAllowed
      ? candidates.filter(
          (row) =>
            row.session === timelineSession &&
            row.elapsed_seconds >= windowStart &&
            row.elapsed_seconds <= windowStart + windowDur,
        )
      : [];
  const slotsInWindow = truthEvents.filter(
    (event) =>
      event.end_seconds > windowStart && event.start_seconds < windowStart + windowDur,
  );
  const sessionSlots = truthEvents
    .filter((event) => event.session === timelineSession)
    .slice()
    .sort((a, b) => a.start_seconds - b.start_seconds);
  const lastCommercial =
    sessionSlots.length > 0 ? sessionSlots[sessionSlots.length - 1] : null;
  const sinceLastSec =
    lastCommercial != null ? playhead - lastCommercial.end_seconds : null;
  const slotsInHour = sessionSlots.filter(
    (event) => event.end_seconds > coverageFrom && event.start_seconds < coverageTo,
  );
  const visibleSessions = hideFinished
    ? sessions.filter(
        (s) => !sessionIsFinished(s.session, coverageRanges) || s.session === timelineSession,
      )
    : sessions;
  const openSessions = sessions.filter((s) => !sessionIsFinished(s.session, coverageRanges));
  const sessionDone = sessionIsFinished(timelineSession, coverageRanges);

  if (!mounted) {
    return <div className="shell label-shell" suppressHydrationWarning aria-busy="true" />;
  }

  return (
    <main className="shell label-shell" suppressHydrationWarning>
      <div className="atmosphere" aria-hidden="true" suppressHydrationWarning />

      <header className="top">
        <BrandMark />
        <p className="tag">
          {replication
            ? "Listen only. Mark the commercial, then the return."
            : blind
              ? "blind truth · what aired"
              : "reviews answer proposals · truth is what aired"}
        </p>
      </header>

      {replication ? (
        <p className="device">{spanRef.current?.hint ?? "Two recordings. Prime first, then Hulu."}</p>
      ) : (
      <div className="zoom-row">
        <button
          type="button"
          className={mode === "debug" ? "zoom-chip active" : "zoom-chip"}
          onClick={() => setMode("debug")}
        >
          Debug queue
        </button>
        <button
          type="button"
          className={mode === "timeline" ? "zoom-chip active" : "zoom-chip"}
          onClick={() => setMode("timeline")}
        >
          Blind truth
        </button>
        {mode === "debug" ? (
          <button
            type="button"
            className={queueOnly ? "zoom-chip active" : "zoom-chip"}
            onClick={() => setQueueOnly((v) => !v)}
          >
            {queueOnly ? "Queue only" : "All keeps"}
          </button>
        ) : null}
        {mode === "timeline" ? (
          <button
            type="button"
            className={hideFinished ? "zoom-chip active" : "zoom-chip"}
            onClick={() => {
              setHideFinished((v) => {
                const next = !v;
                if (next) {
                  const open = pickOpenSession(sessions, coverageRanges, timelineSession);
                  if (open) switchSession(open);
                }
                return next;
              });
            }}
          >
            {hideFinished ? "Skip finished" : "Show finished"}
          </button>
        ) : null}
      </div>
      )}

      {mode === "debug" ? (
        <label className="device">
          Run{" "}
          <select className="note-alone" value={runId} onChange={(e) => setRunId(e.target.value)}>
            {runs.length === 0 ? <option value="">no runs yet</option> : null}
            {runs.map((run) => (
              <option key={run.run_id} value={run.run_id}>
                {run.run_id}
                {run.keeps !== null ? ` · ${run.keeps} keeps` : ""}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      {mode === "debug" && withheld.length ? (
        <p className="device">
          Sealed or non-dev audio is withheld:{" "}
          {withheld.map((row) => `${row.session} (${row.role})`).join(" · ")}
        </p>
      ) : null}

      {mode === "debug" && queueItems.some((item) => !item.proposal_id) ? (
        <div className="zoom-row">
          {queueItems
            .filter((item) => !item.proposal_id)
            .map((item) => (
              <button
                key={`${item.stratum}-${item.session}-${item.elapsed_seconds}`}
                type="button"
                className="zoom-chip"
                onClick={() => {
                  setMode("timeline");
                  switchSession(
                    item.session,
                    item.window_start ?? item.elapsed_seconds ?? 0,
                  );
                }}
              >
                {item.stratum} {fmtClip(item.window_start ?? item.elapsed_seconds ?? 0)}
              </button>
            ))}
        </div>
      ) : null}

      {mode === "timeline" && allDoneAck && openSessions.length === 0 ? (
        <section className="blind-panel">
          <p className="blind-done">Both recordings are saved.</p>
          <p className="device">1 · Prime football</p>
          <p className="device">2 · Hulu · Gilmore Girls</p>
          <p className="device">You can close this page.</p>
        </section>
      ) : null}

      {mode === "timeline" && !(allDoneAck && openSessions.length === 0) ? (
        <section className="blind-panel">
          <div className="blind-toolbar">
            <label className="device toolbar-left">
              Recording{" "}
              <select
                className="note-alone"
                value={timelineSession}
                onChange={(e) => {
                  alignedSessionRef.current = null;
                  switchSession(e.target.value);
                }}
              >
                <option value="">
                  {visibleSessions.length === 0 ? "no recordings" : "choose recording"}
                </option>
                {visibleSessions.map((s) => {
                  const done = sessionIsFinished(s.session, coverageRanges);
                  const job = REPLICATION_TASKS.find((row) => row.session === s.session);
                  const hours = s.audio_seconds != null ? (s.audio_seconds / 3600).toFixed(1) : "?";
                  return (
                    <option key={s.session} value={s.session}>
                      {job ? job.title : s.session}
                      {done ? " · done" : ""}
                      {job ? "" : ` · ${hours}h`}
                    </option>
                  );
                })}
              </select>
            </label>
            <div className="toolbar-right">
              {!sessionDone ? (
                <button
                  type="button"
                  className="complete-btn"
                  disabled={saving || sessionSlots.length === 0}
                  title={
                    sessionSlots.length === 0
                      ? "Save at least one commercial first"
                      : "Finished listening — close this recording"
                  }
                  onClick={() => {
                    if (
                      replication &&
                      !window.confirm(
                        "Finished listening through this whole span? This locks the recording as done.",
                      )
                    ) {
                      return;
                    }
                    const span = spanRef.current;
                    const last = Math.ceil(
                      sessionSlots.reduce((m, e) => Math.max(m, e.end_seconds), 0) ||
                        playhead ||
                        3600,
                    );
                    void closeCoverage(span?.t0 ?? 0, span?.t1 ?? last);
                  }}
                >
                  <svg width="18" height="18" viewBox="0 0 16 16" aria-hidden="true">
                    <path
                      fill="currentColor"
                      d="M6.2 11.4 2.8 8l1.1-1.1 2.3 2.3 5.9-5.9L13.2 4.4 6.2 11.4z"
                    />
                  </svg>
                  Done
                </button>
              ) : (
                <button
                  type="button"
                  className="complete-btn"
                  onClick={() => {
                    const next = sessions.find((s) => !sessionIsFinished(s.session, coverageRanges));
                    if (next) {
                      switchSession(next.session);
                      return;
                    }
                    setAllDoneAck(true);
                  }}
                >
                  {openSessions.length ? "Next →" : "All done"}
                </button>
              )}
            </div>
          </div>
          <p className="device">
            {sessionSlots.length} commercials
            {openSessions.length ? ` · ${openSessions.length} recordings left` : ""}
          </p>

          {sessionDone ? (
            <p className="blind-done">
              {allDoneAck && openSessions.length === 0
                ? "Both recordings are saved. You can leave this page."
                : `Finished. You marked ${sessionSlots.length} commercials.`}
            </p>
          ) : (
            <p className="device">
              Listen. Press <kbd>Space</kbd> (or Start/End) when a commercial begins, again when
              the show returns. <kbd>K</kbd> play/pause.
            </p>
          )}

          <p className="blind-clock mono" suppressHydrationWarning>
            {mounted && startedAt ? wallClock(startedAt, playhead) : fmtClip(playhead)}
          </p>
          {lastCommercial != null && sinceLastSec != null ? (
            <p className="since-last-readout mono">
              {sinceLastSec >= 0
                ? `${fmtClip(sinceLastSec)} after last commercial`
                : `${fmtClip(-sinceLastSec)} before last commercial ends`}
              {" · "}
              last ended{" "}
              {mounted && startedAt
                ? wallClock(startedAt, lastCommercial.end_seconds)
                : fmtClip(lastCommercial.end_seconds)}
            </p>
          ) : null}

          {error ? <p className="mark-error">{error}</p> : null}
          {lastSaved ? <p className="device">Saved {lastSaved}. Keep going.</p> : null}
          {pendingIn !== null ? (
            <p className="blind-pending">
              Started at{" "}
              {mounted && startedAt ? wallClock(startedAt, pendingIn) : fmtClip(pendingIn)}. Press
              End when it finishes.
            </p>
          ) : null}

          {replication ? null : (
          <p className="device wave-stack-hint">
            Click any row at the same place — Wave is the real shape; Jump/Edge often light up at
            commercial cuts.
          </p>
          )}
          <div className="wave-stack">
            {(replication ? WAVE_ROWS.filter((row) => row.id === "wave") : WAVE_ROWS).map((row, rowIndex) => {
              const bars =
                row.id === "wave"
                  ? peaks
                  : waveLanes?.[row.id as keyof WaveLaneData] ?? peaks;
              const hi = waveLanes?.hi ?? [];
              const lo = waveLanes?.lo ?? [];
              const showTrash = rowIndex === 0;
              return (
                <div key={row.id} className="wave-lane-row">
                  <div className="wave-lane-meta">
                    <span className="wave-lane-name mono">{row.label}</span>
                    <span className="wave-lane-hint">{row.hint}</span>
                  </div>
                  <div
                    className={`timeline break-timeline tone-${row.tone}`}
                    ref={rowIndex === 0 ? timelineRef : undefined}
                    onPointerDown={onTimelinePointerDown}
                    onPointerMove={onPointerMove}
                    onPointerUp={onPointerUp}
                    onPointerCancel={onPointerUp}
                  >
                    {row.kind === "bipolar" && hi.length > 0 ? (
                      <div className="wave bipolar">
                        {hi.map((h, i) => {
                          const l = lo[i] ?? -h;
                          const top = ((1 - h) / 2) * 100;
                          const height = Math.max(1.5, ((h - l) / 2) * 100);
                          return (
                            <span
                              key={i}
                              style={{
                                top: `${top}%`,
                                height: `${height}%`,
                              }}
                            />
                          );
                        })}
                      </div>
                    ) : (
                      <div className="wave">
                        {bars.map((p, i) => (
                          <span key={i} style={{ height: `${Math.max(3, p * 100)}%` }} />
                        ))}
                      </div>
                    )}
                    {slotsInWindow.map((event) => {
                      const left = absToPct(Math.max(event.start_seconds, windowStart));
                      const right = absToPct(
                        Math.min(event.end_seconds, windowStart + windowDur),
                      );
                      const width = Math.max(1.2, right - left);
                      const isLast = lastCommercial?.gold_id === event.gold_id;
                      return (
                        <div
                          key={event.gold_id}
                          className={isLast ? "saved-slot last-commercial" : "saved-slot"}
                          style={{ left: `${left}%`, width: `${width}%` }}
                          title={`${mounted && startedAt ? wallClock(startedAt, event.start_seconds) : fmtClip(event.start_seconds)} – ${mounted && startedAt ? wallClock(startedAt, event.end_seconds) : fmtClip(event.end_seconds)}${isLast ? " · last marked" : ""}`}
                        >
                          {showTrash ? (
                            <>
                              <span className="slot-time mono">
                                {mounted && startedAt
                                  ? wallClock(startedAt, event.start_seconds)
                                  : fmtClip(event.start_seconds)}
                              </span>
                              <button
                                type="button"
                                className="slot-trash"
                                disabled={saving}
                                aria-label="Delete this commercial"
                                title="Delete"
                                onPointerDown={(e) => e.stopPropagation()}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  void retractTruth(event.gold_id);
                                }}
                              >
                                <svg width="12" height="12" viewBox="0 0 16 16" aria-hidden="true">
                                  <path
                                    fill="currentColor"
                                    d="M6 2h4l1 1h3v1.5H2V3h3l1-1zm1 4.5h1.5V12H7V6.5zm3 0H11.5V12H10V6.5zM3.5 4.5h9l-.7 9.2A1.5 1.5 0 0 1 10.3 15H5.7a1.5 1.5 0 0 1-1.5-1.3L3.5 4.5z"
                                  />
                                </svg>
                              </button>
                            </>
                          ) : null}
                        </div>
                      );
                    })}
                    {pendingIn !== null ? (
                      <div
                        className="pending-slot"
                        style={{
                          left: `${absToPct(Math.max(pendingIn, windowStart))}%`,
                          width: `${Math.max(
                            0.4,
                            absToPct(
                              Math.min(
                                Math.max(playhead, pendingIn + 0.25),
                                windowStart + windowDur,
                              ),
                            ) - absToPct(Math.max(pendingIn, windowStart)),
                          )}%`,
                        }}
                      />
                    ) : null}
                    {lastCommercial != null &&
                    sinceLastSec != null &&
                    sinceLastSec >= 0 &&
                    lastCommercial.end_seconds < windowStart + windowDur &&
                    playhead > windowStart
                      ? (() => {
                          const gapStart = Math.max(lastCommercial.end_seconds, windowStart);
                          const gapEnd = Math.min(playhead, windowStart + windowDur);
                          if (gapEnd <= gapStart) return null;
                          const left = absToPct(gapStart);
                          const width = absToPct(gapEnd) - left;
                          return (
                            <div
                              className="since-last-band"
                              style={{ left: `${left}%`, width: `${Math.max(0.35, width)}%` }}
                              title={`${fmtClip(sinceLastSec)} after last commercial`}
                            >
                              {showTrash ? (
                                <span className="since-last-band-label mono">
                                  {fmtClip(sinceLastSec)}
                                </span>
                              ) : null}
                            </div>
                          );
                        })()
                      : null}
                    {lastCommercial != null &&
                    lastCommercial.end_seconds >= windowStart &&
                    lastCommercial.end_seconds <= windowStart + windowDur ? (
                      <div
                        className={showTrash ? "last-end-mark" : "last-end-mark bare"}
                        style={{ left: `${absToPct(lastCommercial.end_seconds)}%` }}
                        title="End of last commercial"
                      />
                    ) : null}
                    {overlay && overlayAllowed
                      ? overlayMarks.map((mark) => (
                          <div
                            key={mark.proposal_id}
                            className="detector-in"
                            style={{ left: `${absToPct(mark.elapsed_seconds)}%` }}
                          />
                        ))
                      : null}
                    <div className="playhead" style={{ left: `${playPct}%` }} />
                  </div>
                </div>
              );
            })}
          </div>

          {/* Hidden engine — native controls use clip-local time (2m) and fight the 10m wave view. */}
          {mounted && audioUrl ? (
            <audio
              key={audioUrl}
              ref={audioRef}
              autoPlay
              preload="auto"
              src={audioUrl}
              className="label-audio-hidden"
              onLoadStart={() => logUi("audio_element_loadstart", { url: audioUrl })}
              onProgress={() => {
                const now = performance.now();
                if (now - lastProgressLogRef.current < 750) return;
                lastProgressLogRef.current = now;
                const a = audioRef.current;
                if (!a || a.buffered.length === 0) return;
                logUi("audio_element_progress", {
                  buffered_end: a.buffered.end(a.buffered.length - 1),
                  duration: a.duration,
                  readyState: a.readyState,
                });
              }}
              onPlaying={() => {
                logUi("audio_element_playing", {
                  currentTime: audioRef.current?.currentTime,
                  clip_start: audioClipStartRef.current,
                });
                audioReloadRef.current = false;
                setAudioBusy(false);
                setAudioPlaying(true);
              }}
              onCanPlay={() => {
                logUi("audio_element_canplay", {
                  currentTime: audioRef.current?.currentTime,
                  duration: audioRef.current?.duration,
                  readyState: audioRef.current?.readyState,
                });
                audioReloadRef.current = false;
                setAudioBusy(false);
              }}
              onLoadedData={() => {
                const a = audioRef.current;
                if (!a) return;
                const target = seekTargetRef.current ?? audioClipStartRef.current;
                const offset = Math.max(0, target - audioClipStartRef.current);
                logUi("audio_element_loadeddata", {
                  target,
                  offset,
                  duration: a.duration,
                  readyState: a.readyState,
                });
                const go = () => {
                  try {
                    a.currentTime = Math.min(offset, Math.max(0, (a.duration || offset) - 0.05));
                  } catch {
                    /* ignore */
                  }
                  void a.play().catch((e) => logUi("play_error", { error: String(e) }));
                  audioReloadRef.current = false;
                  setAudioBusy(false);
                };
                if (a.readyState >= 1) go();
                else a.addEventListener("canplay", go, { once: true });
              }}
              onEnded={() => {
                const next = audioClipStartRef.current + audioClipDurRef.current - AUDIO_PREROLL_S;
                const target = Math.max(playheadRef.current, next + AUDIO_PREROLL_S);
                logUi("audio_element_ended", {
                  next_clip_start: Math.max(0, next),
                  seek_target: target,
                });
                seekTargetRef.current = target;
                setAudioClipStart(Math.max(0, next));
              }}
            />
          ) : null}

          <div className="wave-lane-row transport-row">
            <div className="wave-lane-meta">
              <button
                type="button"
                className="transport-play"
                onClick={togglePlayPause}
                aria-label={audioPlaying ? "Pause" : "Play"}
                title={audioPlaying ? "Pause (K)" : "Play (K)"}
              >
                {audioPlaying ? "Pause" : "Play"}
              </button>
              <span className="wave-lane-hint">same scale as waves</span>
            </div>
            <div
              className="timeline break-timeline transport-scrub"
              onPointerDown={onTimelinePointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onPointerCancel={onPointerUp}
            >
              <div className="transport-fill" style={{ width: `${Math.min(100, Math.max(0, playPct))}%` }} />
              <div className="playhead" style={{ left: `${playPct}%` }} />
              <span className="transport-time mono">
                {mounted && startedAt ? wallClock(startedAt, playhead) : fmtClip(playhead)}
                {" · "}
                view {fmtClip(windowStart)}–{fmtClip(windowStart + windowDur)}
              </span>
            </div>
          </div>
          {audioBusy ? <p className="device audio-busy">Loading audio…</p> : null}
          <details className="audio-debug">
            <summary className="device">
              Audio debug ({audioDebug.length}) · clip {audioClipStart.toFixed(0)}–
              {(audioClipStart + AUDIO_WINDOW_S).toFixed(0)}s · view {windowStart.toFixed(0)}–
              {(windowStart + windowDur).toFixed(0)}s
            </summary>
            <pre className="audio-debug-log mono">
              {audioDebug.length === 0
                ? "No events yet. Jump / play to capture logs."
                : audioDebug
                    .slice()
                    .reverse()
                    .map((line) => `${line.t}  ${line.event}${line.detail ? `  ${line.detail}` : ""}`)
                    .join("\n")}
            </pre>
          </details>

          <div className="blind-nav jump-nav">
            {[...JUMP_STEPS].reverse().map((j) => (
              <button
                key={`back-${j.sec}`}
                type="button"
                className="jump-btn"
                aria-label={`Back ${j.label}`}
                title={`Back ${j.label}`}
                onClick={() => jumpAudio(-j.sec)}
              >
                <span aria-hidden="true">‹</span>
                <span className="jump-amt">{j.label}</span>
              </button>
            ))}
            {pendingIn === null ? (
              <button
                type="button"
                className="mark-chip start"
                disabled={saving}
                onClick={markBreakStart}
              >
                Start
              </button>
            ) : (
              <button
                type="button"
                className="mark-chip end"
                disabled={saving}
                onClick={markBreakEnd}
              >
                End
              </button>
            )}
            {JUMP_STEPS.map((j) => (
              <button
                key={`fwd-${j.sec}`}
                type="button"
                className="jump-btn"
                aria-label={`Ahead ${j.label}`}
                title={`Ahead ${j.label}`}
                onClick={() => jumpAudio(j.sec)}
              >
                <span className="jump-amt">{j.label}</span>
                <span aria-hidden="true">›</span>
              </button>
            ))}
          </div>
          {pendingIn !== null ? (
            <button type="button" className="cancel-link" disabled={saving} onClick={cancelPending}>
              Cancel mark
            </button>
          ) : null}

          {sessionSlots.length > 0 ? (
            <ol className="slot-list plain-list">
              {sessionSlots.map((event, i) => {
                const inLabel =
                  mounted && startedAt
                    ? wallClock(startedAt, event.start_seconds)
                    : fmtClip(event.start_seconds);
                const outLabel =
                  mounted && startedAt
                    ? wallClock(startedAt, event.end_seconds)
                    : fmtClip(event.end_seconds);
                return (
                  <li key={event.gold_id} className="slot-row">
                    <button
                      type="button"
                      className="slot-jump"
                      onClick={() => {
                        pendingSlotRef.current = {
                          in: event.start_seconds,
                          out: event.end_seconds,
                        };
                        seekTargetRef.current = event.start_seconds;
                        setTimelineStart(Math.max(0, event.start_seconds - 12));
                        setAudioClipStart(Math.max(0, event.start_seconds - AUDIO_PREROLL_S));
                      }}
                    >
                      <span className="slot-num">#{i + 1}</span>
                      <span className="slot-stamp mono">
                        {inLabel} – {outLabel}
                      </span>
                    </button>
                    <button
                      type="button"
                      className="icon-btn danger"
                      disabled={saving}
                      aria-label={`Delete commercial ${i + 1}`}
                      title="Delete this commercial"
                      onClick={() => void retractTruth(event.gold_id)}
                    >
                      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
                        <path
                          fill="currentColor"
                          d="M6 2h4l1 1h3v1.5H2V3h3l1-1zm1 4.5h1.5V12H7V6.5zm3 0H11.5V12H10V6.5zM3.5 4.5h9l-.7 9.2A1.5 1.5 0 0 1 10.3 15H5.7a1.5 1.5 0 0 1-1.5-1.3L3.5 4.5z"
                        />
                      </svg>
                    </button>
                  </li>
                );
              })}
            </ol>
          ) : null}

          {sessionDone && !replication ? (
            <button
              type="button"
              className={overlay ? "zoom-chip active" : "zoom-chip"}
              aria-label="Overlay detector"
              onClick={() => setOverlay((value) => !value)}
            >
              {overlay ? "Hide computer guesses" : "Show computer guesses"}
            </button>
          ) : null}
        </section>
      ) : null}

      {mode === "debug" ? (
        <>
          <p className="device">
            {`${labeledCount}/${candidates.length} reviewed${current ? ` · ${idx + 1}/${unlabeled.length}` : ""}`}
            {current ? ` · span ${fmtClip(breakLen)}` : ""}
          </p>
          {loading ? <p className="device">Loading…</p> : null}
          {error ? <p className="mark-error">{error}</p> : null}
          {!loading && runs.length === 0 ? (
            <p className="device">
              No run yet. Generate one with{" "}
              <span className="mono">python experiments/run_detector.py --session hush_20260827_135935</span>
            </p>
          ) : null}
          {!loading && runs.length > 0 && !current ? (
            <p className="device">All proposals in this run have a review.</p>
          ) : null}

          {current ? (
            <>
              <section className="hero label-hero">
                <div className="status-line">
                  <span className="pill on">score {current.score.toFixed(2)}</span>
                  <span className="elapsed mono wall-big">
                    {startedAt ? wallClock(startedAt, current.elapsed_seconds) : fmtClip(current.elapsed_seconds)}
                  </span>
                </div>
                <p className="device">
                  Python suggestion only. frame {current.frame_index ?? "—"} · sample{" "}
                  {current.session_sample_index ?? "—"} · silence bonus{" "}
                  {current.evidence?.silence_bonus ?? "—"} · jump z {current.evidence?.jump_z?.toFixed(2) ?? "—"} ·
                  flux z {Number(current.flux_z).toFixed(2)} · norm {current.evidence?.norm?.scope ?? "chunk"}
                  {current.near_silence ? " · near silence" : ""}
                </p>
                <div className="zoom-row">
                  {[120, 180, 210, 300].map((r) => (
                    <button
                      key={r}
                      type="button"
                      className={postRoll === r ? "zoom-chip active" : "zoom-chip"}
                      onClick={() => setPostRoll(r)}
                    >
                      +{r / 60}m after IN
                    </button>
                  ))}
                </div>
                <div
                  className="timeline break-timeline"
                  ref={timelineRef}
                  onPointerDown={onTimelinePointerDown}
                  onPointerMove={onPointerMove}
                  onPointerUp={onPointerUp}
                  onPointerCancel={onPointerUp}
                >
                  <div className="wave">
                    {peaks.map((p, i) => (
                      <span key={i} style={{ height: `${Math.max(3, p * 100)}%` }} />
                    ))}
                  </div>
                  <div className="sel" style={{ left: `${inPct}%`, width: `${Math.max(0, outPct - inPct)}%` }} />
                  {fades.map((f) => (
                    <div
                      key={f.elapsed}
                      className="fade-mark"
                      style={{ left: `${absToPct(f.elapsed)}%` }}
                      title="fade from Python run"
                    />
                  ))}
                  {suggestedOut !== null ? (
                    <div className="suggest-out" style={{ left: `${absToPct(suggestedOut)}%` }} title="Python OUT" />
                  ) : null}
                  <div className="playhead" style={{ left: `${playPct}%` }} />
                  <button
                    type="button"
                    className="handle in"
                    style={{ left: `${inPct}%` }}
                    onPointerDown={(e) => onPointerDown("in", e)}
                    aria-label="In point"
                  />
                  <button
                    type="button"
                    className="handle out"
                    style={{ left: `${outPct}%` }}
                    onPointerDown={(e) => onPointerDown("out", e)}
                    aria-label="Out point"
                  />
                </div>
                <div className="tc-row mono">
                  <div>
                    <span className="tc-label">IN</span>
                    <strong>{startedAt ? wallClock(startedAt, inPoint) : fmtClip(inPoint)}</strong>
                  </div>
                  <div>
                    <span className="tc-label">PLAY</span>
                    <strong>{startedAt ? wallClock(startedAt, playhead) : fmtClip(playhead)}</strong>
                  </div>
                  <div>
                    <span className="tc-label">OUT</span>
                    <strong>{startedAt ? wallClock(startedAt, outPoint) : fmtClip(outPoint)}</strong>
                  </div>
                </div>
                {audioUrl ? (
                  <audio key={audioUrl} ref={audioRef} controls src={audioUrl} className="label-audio" />
                ) : null}
                <div className="seek-row">
                  <button type="button" className="mark-btn" onClick={playSelection}>
                    Play IN→OUT
                  </button>
                  <button type="button" className="mark-btn" onClick={() => seekAbs(inPoint)}>
                    Jump IN
                  </button>
                  <button type="button" className="mark-btn" onClick={() => seekAbs(outPoint)}>
                    Jump OUT
                  </button>
                  {suggestedOut !== null ? (
                    <button type="button" className="mark-btn" onClick={() => setOutPoint(suggestedOut)}>
                      Snap OUT to Python
                    </button>
                  ) : null}
                  <button type="button" className="mark-btn" onClick={() => setLoopSelection((v) => !v)}>
                    Loop {loopSelection ? "on" : "off"}
                  </button>
                </div>
                <div className="nudge-row">
                  <span className="device">IN</span>
                  <button type="button" onClick={() => nudge("in", -1)}>−1s</button>
                  <button type="button" onClick={() => nudge("in", -0.1)}>−0.1</button>
                  <button type="button" onClick={() => nudge("in", 0.1)}>+0.1</button>
                  <button type="button" onClick={() => nudge("in", 1)}>+1s</button>
                  <span className="device">OUT</span>
                  <button type="button" onClick={() => nudge("out", -5)}>−5s</button>
                  <button type="button" onClick={() => nudge("out", -1)}>−1s</button>
                  <button type="button" onClick={() => nudge("out", 1)}>+1s</button>
                  <button type="button" onClick={() => nudge("out", 5)}>+5s</button>
                </div>
              </section>
              <input
                className="note-alone"
                value={reviewer}
                onChange={(e) => setReviewer(e.target.value)}
                placeholder="Reviewer initials"
              />
              <input
                className="note-alone"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Note"
              />
              <select className="note-alone" value={errorTag} onChange={(e) => setErrorTag(e.target.value)}>
                {ERROR_TAGS.map((tag) => (
                  <option key={tag || "none"} value={tag}>
                    {tag || "error tag (optional)"}
                  </option>
                ))}
              </select>
              <section className="marks label-actions">
                <div className="mark-row">
                  <button
                    type="button"
                    className="mark-btn ad"
                    disabled={saving || breakLen < 20}
                    onClick={() => void saveReview("ad_break")}
                  >
                    Proposal is a break
                  </button>
                  <button
                    type="button"
                    className="mark-btn content"
                    disabled={saving}
                    onClick={() => void saveReview("not_break")}
                  >
                    Not a break
                  </button>
                </div>
                <button type="button" className="mark-btn" disabled={saving} onClick={() => void saveReview("unsure")}>
                  Unsure
                </button>
              </section>
            </>
          ) : null}
        </>
      ) : null}

      <p className="folder mono">
        <a href="/">← live monitor</a>
      </p>
    </main>
  );
}
