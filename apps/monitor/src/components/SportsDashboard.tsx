"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { BrandMark } from "@/components/BrandMark";
import { Icons, IconTip } from "@/components/IconTip";
import { LiveMeter } from "@/components/LiveMeter";

function isTestQuery() {
  if (typeof window === "undefined") return false;
  const params = new URLSearchParams(window.location.search);
  return params.get("preview") === "live" || params.get("mode") === "test";
}

function syncModeQuery(testMode: boolean) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (testMode) {
    url.searchParams.set("mode", "test");
    url.searchParams.delete("preview");
  } else {
    url.searchParams.delete("mode");
    url.searchParams.delete("preview");
  }
  window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
}

function ModeToggle({
  testMode,
  onChange,
}: {
  testMode: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <div className={testMode ? "mode-toggle test" : "mode-toggle live"} role="group" aria-label="Session mode">
      <button
        type="button"
        className={!testMode ? "on" : ""}
        aria-pressed={!testMode}
        onClick={() => onChange(false)}
      >
        Live
      </button>
      <button
        type="button"
        className={testMode ? "on" : ""}
        aria-pressed={testMode}
        onClick={() => onChange(true)}
      >
        Test
      </button>
    </div>
  );
}

const SOUND_LABEL: Record<string, string> = {
  silence: "Silence",
  neon: "Neon",
  wednesday_night: "Wednesday Night",
  wednesday_night_lofi_again: "Lofi Again",
  wednesday_night_cup_of_tea: "Cup of Tea",
  friends_over: "Friends Over",
  friends_over_disco: "Funky Disco",
  friends_over_empty_stretch: "Empty Stretch",
  cocktail_lounge: "Cocktail Lounge",
  cocktail_lounge_bossa: "Bossa Nova",
  rainy_night: "Rainy Night",
  stadium_vibe: "Stadium",
};

const SOUND_ICON: Record<string, ReactNode> = {
  silence: Icons.silence,
  neon: Icons.neon,
  wednesday_night: Icons.night,
  wednesday_night_lofi_again: Icons.pad,
  wednesday_night_cup_of_tea: Icons.piano,
  friends_over: Icons.charge,
  friends_over_disco: Icons.drop,
  friends_over_empty_stretch: Icons.volt,
  cocktail_lounge: Icons.harp,
  cocktail_lounge_bossa: Icons.chimes,
  rainy_night: Icons.rain,
  stadium_vibe: Icons.crowd,
};

type ServiceOption = { id: string; tip: string; slug: string; label: string };

const PRIMARY_SERVICES: ServiceOption[] = [
  { id: "Cable / antenna", tip: "TV / cable", slug: "cable", label: "TV" },
  { id: "Prime Video", tip: "Prime Video", slug: "prime", label: "Prime" },
  { id: "Netflix", tip: "Netflix", slug: "netflix", label: "Netflix" },
  { id: "YouTube TV", tip: "YouTube TV", slug: "youtube", label: "YouTube TV" },
  { id: "Hulu", tip: "Hulu", slug: "hulu", label: "Hulu" },
];

const MORE_SERVICES: ServiceOption[] = [
  { id: "Max", tip: "Max", slug: "max", label: "Max" },
  { id: "Paramount+", tip: "Paramount+", slug: "paramount", label: "Paramount+" },
  { id: "Apple TV", tip: "Apple TV", slug: "appletv", label: "Apple TV" },
  { id: "Peacock", tip: "Peacock", slug: "peacock", label: "Peacock" },
  { id: "Roku", tip: "Roku Channel / device", slug: "roku", label: "Roku" },
  { id: "Fubo", tip: "Fubo", slug: "fubo", label: "Fubo" },
  { id: "Tubi", tip: "Tubi", slug: "tubi", label: "Tubi" },
  { id: "Crunchyroll", tip: "Crunchyroll", slug: "crunchyroll", label: "Crunchyroll" },
  { id: "Plex", tip: "Plex", slug: "plex", label: "Plex" },
  { id: "Twitch", tip: "Twitch", slug: "twitch", label: "Twitch" },
  { id: "Spotify", tip: "Spotify", slug: "spotify", label: "Spotify" },
  { id: "Mubi", tip: "Mubi", slug: "mubi", label: "Mubi" },
  { id: "HBO", tip: "HBO", slug: "hbomax", label: "HBO" },
  { id: "Other", tip: "Something else", slug: "other", label: "Other" },
];

function ServiceMark({ slug, label }: { slug: string; label: string }) {
  return (
    <span className="service-chip">
      <img className="service-logo" src={`/brand/services/${slug}.svg?v=3`} alt="" draggable={false} />
      <span className="service-label">{label}</span>
    </span>
  );
}

function ServicePicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (id: string) => void;
}) {
  const inMore = MORE_SERVICES.some((row) => row.id === value);
  const [open, setOpen] = useState(inMore);

  useEffect(() => {
    if (inMore) setOpen(true);
  }, [inMore]);

  const render = (row: ServiceOption) => (
    <IconTip
      key={row.id}
      tip={row.tip}
      active={value === row.id}
      className={["service-tile", value === row.id ? "service-on" : "service-off"].join(" ")}
      onClick={() => onChange(row.id)}
    >
      <ServiceMark slug={row.slug} label={row.label} />
    </IconTip>
  );

  return (
    <div className="service-picker">
      <div className="service-grid" role="group" aria-label="Service">
        {PRIMARY_SERVICES.map(render)}
        <IconTip
          tip={open ? "Hide more services" : "More streaming services"}
          active={open || inMore}
          className={["service-tile", open || inMore ? "service-on" : "service-off"].join(" ")}
          onClick={() => setOpen((current) => !current)}
        >
          <ServiceMark slug="other" label="More" />
        </IconTip>
      </div>
      {open ? (
        <div className="service-grid service-more" role="group" aria-label="More streaming services">
          {MORE_SERVICES.map(render)}
        </div>
      ) : null}
    </div>
  );
}

const KINDS = [
  { id: "sports", tip: "Live sports", label: "Sports", icon: Icons.sports },
  { id: "tv", tip: "TV show", label: "TV", icon: Icons.tv },
  { id: "movie", tip: "Movie", label: "Movie", icon: Icons.movie },
  { id: "other", tip: "Something else", label: "Other", icon: Icons.other },
];

type TnfView = {
  mode?: string;
  return_policy?: string;
  fail_open_s?: number;
  phase?: number;
  covering?: boolean;
  cover_elapsed_s?: number | null;
  suggestion?: string;
  last_reason?: string;
  last_score?: number | null;
  audio_depart?: number;
  suggested_starts?: number;
  machine_covers?: number;
  manual_rescues?: number;
  transitions?: { t?: number; kind?: string; reason?: string }[];
  fingerprint?: string;
  error?: string;
  start?: string;
  return?: string;
};

type DeskState = {
  state: "PROGRAM" | "REPLACEMENT";
  auto: boolean;
  replacement: string;
  sounds: string[];
  timestamp: number;
  input_dbfs: number;
  recording: boolean;
  resumable?: boolean;
  input_name: string;
  output_name: string;
  error: string;
  events: { t?: number; state?: string; decision_source?: string; replacement?: string; human_override?: boolean }[];
  chunks: string[];
  show?: string;
  service?: string;
  content?: string;
  record_only?: boolean;
  cover_bar?: number | null;
  audio_score?: number | null;
  resume_show?: string;
  resume_service?: string;
  resume_content?: string;
  resume_within_min?: number;
  tnf?: TnfView;
};

type Device = { index: number; name: string };

const EMPTY: DeskState = {
  state: "PROGRAM",
  auto: true,
  replacement: "wednesday_night",
  sounds: Object.keys(SOUND_LABEL),
  timestamp: 0,
  input_dbfs: -100,
  recording: false,
  input_name: "",
  output_name: "",
  error: "",
  events: [],
  chunks: [],
  show: "",
  service: "",
  content: "sports",
  record_only: false,
};

const PREVIEW: DeskState = {
  ...EMPTY,
  recording: true,
  show: "Buccaneers at Cowboys",
  service: "Prime Video",
  content: "sports",
  state: "REPLACEMENT",
  replacement: "wednesday_night",
  timestamp: 742,
  input_dbfs: -18.4,
  input_name: "USB Optical",
  output_name: "External Headphones",
  events: [
    { t: 510, state: "PROGRAM_TO_REPLACEMENT", decision_source: "auto", replacement: "wednesday_night" },
    { t: 640, state: "REPLACEMENT_TO_PROGRAM", decision_source: "human", replacement: "wednesday_night" },
    { t: 700, state: "PROGRAM_TO_REPLACEMENT", decision_source: "human", replacement: "friends_over" },
  ],
};

function asDeskState(value: unknown): DeskState | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Partial<DeskState>;
  if (typeof row.state !== "string") return null;
  return {
    ...EMPTY,
    state: row.state === "REPLACEMENT" ? "REPLACEMENT" : "PROGRAM",
    auto: row.auto !== false,
    replacement: typeof row.replacement === "string" ? row.replacement : EMPTY.replacement,
    sounds: Array.isArray(row.sounds) && row.sounds.length ? row.sounds.map(String) : EMPTY.sounds,
    timestamp: Number.isFinite(Number(row.timestamp)) ? Number(row.timestamp) : 0,
    input_dbfs: Number.isFinite(Number(row.input_dbfs)) ? Number(row.input_dbfs) : EMPTY.input_dbfs,
    recording: Boolean(row.recording),
    resumable: Boolean(row.resumable),
    input_name: typeof row.input_name === "string" ? row.input_name : "",
    output_name: typeof row.output_name === "string" ? row.output_name : "",
    error: typeof row.error === "string" ? row.error : "",
    events: Array.isArray(row.events) ? row.events : [],
    chunks: Array.isArray(row.chunks) ? row.chunks.map(String) : [],
    show: typeof row.show === "string" ? row.show : "",
    service: typeof row.service === "string" ? row.service : "",
    content: typeof row.content === "string" ? row.content : "sports",
    record_only: Boolean(row.record_only),
    cover_bar: readCoverBar(value),
    audio_score: readAudioScore(value),
    resume_show: typeof row.resume_show === "string" ? row.resume_show : "",
    resume_service: typeof row.resume_service === "string" ? row.resume_service : "",
    resume_content: typeof row.resume_content === "string" ? row.resume_content : "",
    resume_within_min: Number.isFinite(Number(row.resume_within_min)) ? Number(row.resume_within_min) : 30,
    tnf: row.tnf && typeof row.tnf === "object" ? row.tnf : currentTnf(value),
  };
}

function readAudioScore(value: unknown): number | null {
  if (!value || typeof value !== "object") return null;
  const row = value as { audio_score?: number; families?: { audio?: { departure?: number } } };
  if (typeof row.audio_score === "number" && Number.isFinite(row.audio_score)) return row.audio_score;
  const departure = row.families?.audio?.departure;
  return typeof departure === "number" && Number.isFinite(departure) ? departure : null;
}

function readCoverBar(value: unknown): number | null {
  if (!value || typeof value !== "object") return null;
  const bar = (value as { cover_bar?: number }).cover_bar;
  return typeof bar === "number" && Number.isFinite(bar) ? bar : null;
}

const COVER_LINES = [
  { value: 0.3, label: "Careful", hint: "Waits for a strong change" },
  { value: 0.22, label: "Usual", hint: "The installed line" },
  { value: 0.14, label: "Sooner", hint: "Covers more, can cover a play" },
];

function currentTnf(value: unknown): TnfView | undefined {
  if (!value || typeof value !== "object") return undefined;
  const tnf = (value as { tnf?: TnfView }).tnf;
  return tnf && typeof tnf === "object" ? tnf : undefined;
}

function restoreForm(nextState: DeskState, setters: {
  setShow: (v: string) => void;
  setService: (v: string) => void;
  setContent: (v: string) => void;
  setInputName: (v: string) => void;
  setOutputName: (v: string) => void;
  setRecordOnly?: (v: boolean) => void;
}) {
  if (nextState.show) setters.setShow(nextState.show);
  if (nextState.service) setters.setService(nextState.service);
  if (nextState.content) setters.setContent(nextState.content);
  if (nextState.input_name) setters.setInputName(nextState.input_name);
  if (nextState.output_name) setters.setOutputName(nextState.output_name);
  if (setters.setRecordOnly) setters.setRecordOnly(Boolean(nextState.record_only));
}

function CoverLine({
  score,
  bar,
  fallback,
  busy,
  onPick,
}: {
  score: number | null | undefined;
  bar: number | null | undefined;
  fallback: number;
  busy: boolean;
  onPick: (value: number) => void;
}) {
  const chosen = typeof bar === "number";
  const active = chosen ? bar : fallback;
  const text = typeof score === "number" ? score.toFixed(2) : "—";
  return (
    <div className="cover-line">
      <p className="cover-score">
        <strong>{text}</strong>
        <span>right now. The game usually stays under 0.10.</span>
      </p>
      <div className="sound-picks" role="group" aria-label="Cover line">
        {COVER_LINES.map((line) => (
          <button
            key={line.value}
            type="button"
            className={Math.abs(active - line.value) < 0.011 ? "sound-pick on" : "sound-pick"}
            disabled={busy || !chosen}
            title={line.hint}
            onClick={() => onPick(line.value)}
          >
            {line.label} {line.value.toFixed(2)}
          </button>
        ))}
      </div>
      <p className="setup-help">
        {chosen
          ? "Higher means it waits until the sound is further from the game. Show the game still comes back immediately."
          : `This recording stays at ${active.toFixed(2)}. A different line starts with the next engine.`}
      </p>
    </div>
  );
}

function dur(seconds: number) {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
  return `${m}:${String(r).padStart(2, "0")}`;
}

function TnfLabPanel({
  tnf,
  busy,
  recordOnly,
  onCommand,
}: {
  tnf?: TnfView;
  busy: boolean;
  recordOnly: boolean;
  onCommand: (body: { op?: string; mode?: string; return_policy?: string; fail_open_s?: number }) => void;
}) {
  const mode = tnf?.mode || "observe";
  const suggestion = tnf?.suggestion || "unsure";
  const suggestionText =
    suggestion === "probably_ad" ? "Probably ad" : suggestion === "probably_game" ? "Probably game" : "Unsure";
  return (
    <section className={mode === "auto" ? "app-group tnf-lab on" : "app-group tnf-lab"}>
      <p className="app-group-label">TNF Lab</p>
      <div className="app-group-body">
        <p className="tnf-kicker">
          {mode === "auto" ? "Experimental Auto is ON" : mode === "suggest" ? "Suggest only · TV stays on" : "Observe · TV stays on"}
          {recordOnly ? " · Record only blocks cover" : ""}
        </p>
        <div className="tnf-modes" role="group" aria-label="TNF lab mode">
          {(["observe", "suggest", "auto"] as const).map((name) => (
            <button
              key={name}
              type="button"
              className={mode === name ? "on" : ""}
              disabled={busy || (name === "auto" && recordOnly)}
              onClick={() => onCommand({ mode: name, op: "set" })}
            >
              {name === "auto" ? "Experimental Auto" : name === "suggest" ? "Suggest" : "Observe"}
            </button>
          ))}
        </div>
        <p className={suggestion === "probably_ad" ? "tnf-call ad" : "tnf-call"}>
          <strong>{suggestionText}</strong>
          <span>
            {tnf?.last_reason || "waiting"}
            {tnf?.last_score != null ? ` · ${Number(tnf.last_score).toFixed(2)}` : ""}
          </span>
        </p>
        <div className="tnf-modes" role="group" aria-label="Return policy">
          <button
            type="button"
            className={(tnf?.return_policy || "manual") === "manual" ? "on" : ""}
            disabled={busy}
            onClick={() => onCommand({ return_policy: "manual", op: "set" })}
          >
            Start: machine · Return: you
          </button>
          <button
            type="button"
            className={tnf?.return_policy === "machine" ? "on" : ""}
            disabled={busy}
            onClick={() => onCommand({ return_policy: "machine", op: "set" })}
          >
            Return: machine
          </button>
        </div>
        <label className="tnf-cap">
          Fail-open after
          <input
            type="number"
            min={30}
            max={600}
            value={tnf?.fail_open_s || 180}
            disabled={busy}
            onChange={(event) => onCommand({ fail_open_s: Number(event.target.value), op: "set" })}
          />
          seconds
        </label>
        <p className="tnf-stats">
          Cover {tnf?.cover_elapsed_s != null ? `${tnf.cover_elapsed_s}s` : "off"}
          {" · "}starts {tnf?.suggested_starts ?? 0}
          {" · "}machine covers {tnf?.machine_covers ?? 0}
          {" · "}rescues {tnf?.manual_rescues ?? 0}
          {" · "}fingerprint {tnf?.fingerprint || "not_run"}
        </p>
        <ul className="tnf-log">
          {(tnf?.transitions || []).length === 0 ? <li>No lab transitions yet.</li> : null}
          {(tnf?.transitions || []).map((row, index) => (
            <li key={`${row.t}-${index}`}>
              {row.t ?? "—"} · {row.kind} · {row.reason}
            </li>
          ))}
        </ul>
        <button type="button" className="tnf-kill" disabled={busy} onClick={() => onCommand({ op: "kill" })}>
          STOP AUTO / PLAY TV
        </button>
        {!tnf ? <p className="tnf-kicker">Lab state appears after the engine restarts.</p> : null}
      </div>
    </section>
  );
}

export function SportsDashboard() {
  const [testMode, setTestMode] = useState(false);
  const [desk, setDesk] = useState<DeskState>(EMPTY);
  const [ready, setReady] = useState(false);
  const [bootError, setBootError] = useState("");
  const [inputs, setInputs] = useState<Device[]>([]);
  const [outputs, setOutputs] = useState<Device[]>([]);
  const [show, setShow] = useState("");
  const [service, setService] = useState("");
  const [content, setContent] = useState("");
  const [inputName, setInputName] = useState("");
  const [outputName, setOutputName] = useState("");
  const [recordOnly, setRecordOnly] = useState(false);
  const [busy, setBusy] = useState(false);
  const [playing, setPlaying] = useState<string | null>(null);
  const setupReady =
    Boolean(service.trim()) &&
    Boolean(content.trim()) &&
    Boolean(show.trim()) &&
    Boolean(inputName.trim()) &&
    Boolean(outputName.trim()) &&
    inputs.some((row) => row.name === inputName) &&
    outputs.some((row) => row.name === outputName);

  const applyState = useCallback((next: DeskState) => {
    setDesk(next);
  }, []);

  const boot = useCallback(async () => {
    setBootError("");
    try {
      const res = await fetch("/api/live/boot", { method: "POST" });
      const payload = (await res.json().catch(() => null)) as {
        ok?: boolean;
        error?: string;
        devices?: { inputs?: Device[]; outputs?: Device[] };
        state?: unknown;
      } | null;
      if (!res.ok || !payload || payload.ok === false) {
        setBootError(payload?.error || "Could not get ready.");
        setReady(false);
        return;
      }
      const nextInputs = payload.devices?.inputs ?? [];
      const nextOutputs = payload.devices?.outputs ?? [];
      setInputs(nextInputs);
      setOutputs(nextOutputs);
      const nextState = asDeskState(payload.state);
      if (nextState) {
        applyState(nextState);
        // Restore last show/devices so refresh can jump back without retyping.
        restoreForm(nextState, {
          setShow,
          setService,
          setContent,
          setInputName,
          setOutputName,
          setRecordOnly,
        });
      }
      setReady(true);
    } catch {
      setBootError("Could not get ready on this Mac.");
      setReady(false);
    }
  }, [applyState]);

  useEffect(() => {
    const startInTest = isTestQuery();
    setTestMode(startInTest);
    syncModeQuery(startInTest);
    if (startInTest) {
      setReady(true);
      return;
    }
    void boot();
  }, [boot]);

  useEffect(() => {
    if (!testMode) return;
    let cancelled = false;
    let timer = 0;
    const arm = () =>
      window.setTimeout(() => {
        if (cancelled) return;
        const switchToLive = window.confirm(
          "Test mode has been on for over 1 minute.\n\nSwitch back to Live?",
        );
        if (switchToLive) {
          setTestMode(false);
          syncModeQuery(false);
          setDesk((current) => (current.recording ? EMPTY : current));
          void boot();
          return;
        }
        timer = arm();
      }, 60_000);
    timer = arm();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [testMode, boot]);

  const changeMode = useCallback(
    (nextTest: boolean) => {
      if (nextTest === testMode) return;
      if (nextTest && desk.recording && !testMode) {
        window.alert("Stop the live session before switching to Test.");
        return;
      }
      if (!nextTest && testMode && desk.recording) {
        setDesk(EMPTY);
      }
      setTestMode(nextTest);
      syncModeQuery(nextTest);
      if (!nextTest && !ready) void boot();
      if (!nextTest && ready && !desk.recording) void boot();
    },
    [boot, desk.recording, ready, testMode],
  );

  useEffect(() => {
    if (!ready || testMode) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const res = await fetch("/api/live/state", { cache: "no-store" });
        if (!res.ok) return;
        const next = asDeskState(await res.json().catch(() => null));
        if (!cancelled && next) applyState(next);
      } catch {
        // keep last good frame
      }
    };
    void tick();
    const timer = setInterval(() => void tick(), 500);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [ready, applyState, testMode]);

  const refreshDevices = useCallback(async () => {
    try {
      const res = await fetch("/api/live/devices", { cache: "no-store" });
      if (!res.ok) return;
      const payload = (await res.json().catch(() => null)) as {
        inputs?: Device[];
        outputs?: Device[];
      } | null;
      if (!payload) return;
      const nextInputs = payload.inputs ?? [];
      const nextOutputs = payload.outputs ?? [];
      setInputs(nextInputs);
      setOutputs(nextOutputs);
      setInputName((current) => (nextInputs.some((row) => row.name === current) ? current : ""));
      setOutputName((current) => (nextOutputs.some((row) => row.name === current) ? current : ""));
    } catch {
      // keep last list
    }
  }, []);

  useEffect(() => {
    if (!ready || desk.recording || testMode) return;
    void refreshDevices();
    const timer = setInterval(() => void refreshDevices(), 8000);
    return () => clearInterval(timer);
  }, [ready, desk.recording, refreshDevices, testMode]);

  // In Test mode, still list devices so setup can be completed.
  useEffect(() => {
    if (!ready || !testMode || desk.recording) return;
    void refreshDevices();
    const timer = setInterval(() => void refreshDevices(), 2500);
    return () => clearInterval(timer);
  }, [ready, testMode, desk.recording, refreshDevices]);

  const post = useCallback(
    async (path: string, body: unknown = {}) => {
      if (testMode) {
        if (path === "/override") {
          const action = String((body as { action?: string }).action || "");
          setDesk((current) => {
            const next = { ...current };
            if (action === "play") next.state = "PROGRAM";
            if (action === "mute") next.state = "REPLACEMENT";
            if (action === "auto") next.auto = !current.auto;
            if (action.startsWith("sound_")) next.replacement = action.slice(6);
            return next;
          });
        }
        if (path === "/tnf") {
          const command = body as { op?: string; mode?: string; return_policy?: string; fail_open_s?: number };
          setDesk((current) => {
            const tnf = { ...(current.tnf || {}), mode: current.tnf?.mode || "observe" };
            if (command.op === "kill") {
              tnf.mode = "observe";
              tnf.covering = false;
              tnf.last_reason = "kill";
            } else {
              if (command.mode) tnf.mode = command.mode;
              if (command.return_policy) tnf.return_policy = command.return_policy;
              if (command.fail_open_s) tnf.fail_open_s = command.fail_open_s;
            }
            return { ...current, tnf, state: command.op === "kill" || tnf.mode !== "auto" ? current.state : current.state };
          });
        }
        if (path === "/stop") {
          setDesk(EMPTY);
        }
        return desk;
      }
      setBusy(true);
      try {
        const res = await fetch(`/api/live${path}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const payload = asDeskState(await res.json().catch(() => null));
        if (payload) applyState(payload);
        return payload;
      } catch {
        return null;
      } finally {
        setBusy(false);
      }
    },
    [applyState, testMode, desk],
  );

  const start = async (fresh = false, recordOnlyChoice = recordOnly) => {
    if (!setupReady || busy) return;
    setRecordOnly(recordOnlyChoice);
    if (testMode) {
      setDesk({
        ...PREVIEW,
        show: show.trim(),
        service: service.trim(),
        content: content.trim(),
        input_name: inputName,
        output_name: outputName,
        recording: true,
      });
      setBootError("");
      return;
    }
    const payload = await post("/start", {
      show: show.trim(),
      service: service.trim(),
      content: content.trim(),
      input: inputName,
      output: outputName,
      record_only: recordOnlyChoice,
      fresh,
    });
    if (payload?.error) setBootError(payload.error);
    else setBootError("");
  };

  const commercial = desk.state === "REPLACEMENT";
  const recordingOnly = Boolean(desk.record_only);
  const sameSitting =
    Boolean(desk.resumable) &&
    show.trim().toLowerCase() === (desk.resume_show || "").trim().toLowerCase() &&
    service.trim().toLowerCase() === (desk.resume_service || "").trim().toLowerCase() &&
    content.trim().toLowerCase() === (desk.resume_content || "sports").trim().toLowerCase();
  const resumeMinutes = desk.resume_within_min || 30;
  const title = desk.show || show;
  const where = desk.service || service;
  const breaks = useMemo(() => {
    const rows = (desk.events ?? [])
      .filter((row) => row.state === "PROGRAM_TO_REPLACEMENT" || row.state === "REPLACEMENT_TO_PROGRAM")
      .slice()
      .sort((a, b) => (a.t ?? 0) - (b.t ?? 0));
    const spans: { start: number; end: number; live: boolean; sound: string }[] = [];
    let open: { start: number; end: number; live: boolean; sound: string } | null = null;
    for (const row of rows) {
      const t = row.t ?? 0;
      if (row.state === "PROGRAM_TO_REPLACEMENT") {
        if (open) spans.push({ ...open, end: t, live: false });
        open = { start: t, end: desk.timestamp, live: true, sound: row.replacement ?? desk.replacement };
      } else if (open) {
        spans.push({ ...open, end: t, live: false });
        open = null;
      }
    }
    if (open) spans.push(open);
    return spans.reverse();
  }, [desk.events, desk.timestamp, desk.replacement]);
  const openBreak = breaks.find((span) => span.live) ?? null;
  const lastBreak = breaks.find((span) => !span.live) ?? null;
  const timeNote = recordingOnly
    ? null
    : openBreak
      ? `Break ${dur(desk.timestamp - openBreak.start)}`
      : lastBreak
        ? `${dur(desk.timestamp - lastBreak.end)} since break`
        : null;

  if (!ready) {
    return (
      <main className="desk light app-shell">
        <header className="app-header">
          <div className="app-brand">
            <BrandMark tone="color" className="brand-hero" />
            <p className="masthead-sub">Take Down Big Audio</p>
          </div>
          <ModeToggle testMode={testMode} onChange={changeMode} />
        </header>
        <div className="app-scroll">
          <section className="app-group">
            <div className="app-group-body center">
              <h1 className="app-title">Getting ready</h1>
              <p className="lead">One moment while OHush wakes up on this Mac.</p>
              {bootError ? (
                <>
                  <p className="desk-error">{bootError}</p>
                  <IconTip tip="Try again" onClick={() => void boot()}>
                    {Icons.refresh}
                  </IconTip>
                </>
              ) : (
                <p className="soft">Starting…</p>
              )}
            </div>
          </section>
        </div>
      </main>
    );
  }

  if (!desk.recording) {
    return (
      <main className={testMode ? "desk light app-shell test-mode" : "desk light app-shell"}>
        <header className="app-header">
          <div className="app-brand">
            <BrandMark tone="color" className="brand-hero" />
            <p className="masthead-sub">Take Down Big Audio</p>
          </div>
          <ModeToggle testMode={testMode} onChange={changeMode} />
        </header>
        {testMode ? <p className="preview-banner">Test mode · nothing is recorded</p> : null}

        <div className="app-scroll setup-layout">
          <section className="app-group setup-card">
            <h2 className="setup-title">Content</h2>

            <div className="setup-block">
              <p className="setup-sub">Provider</p>
              <ServicePicker value={service} onChange={setService} />
            </div>

            <div className="setup-block setup-type-name">
              <div className="setup-block">
                <p className="setup-sub">Type</p>
                <div className="kind-grid" role="group" aria-label="Type">
                  {KINDS.map((kind) => (
                    <IconTip
                      key={kind.id}
                      tip={kind.tip}
                      active={content === kind.id}
                      className={content === kind.id ? "pick-on" : "pick-off"}
                      onClick={() => setContent(kind.id)}
                    >
                      <span className="kind-chip">
                        {kind.icon}
                        <span className="kind-label">{kind.label}</span>
                      </span>
                    </IconTip>
                  ))}
                </div>
              </div>

              <div className="setup-block">
                <p className="setup-sub">Name</p>
                <label className="field tight">
                  <input
                    value={show}
                    onChange={(event) => setShow(event.target.value)}
                    placeholder="e.g. Buccaneers at Cowboys"
                    autoFocus
                  />
                </label>
              </div>
            </div>
          </section>

          <section className="app-group setup-card setup-listening">
            <div className="setup-title-row">
              <h2 className="setup-title">Listening</h2>
              <IconTip tip="Refresh devices" className="refresh-inline" onClick={() => void refreshDevices()}>
                {Icons.refresh}
              </IconTip>
            </div>
            <div className="setup-block setup-listening-body">
              <p className="setup-help">
                Mute the TV speakers. Run optical into the USB box. Send Mac audio to the soundbar with aux.
              </p>
              <label className="field">
                <span className="field-with-icon">
                  <span className="field-icon">{Icons.mic}</span>
                  Input
                </span>
                <select value={inputName} onChange={(event) => setInputName(event.target.value)}>
                  <option value="" disabled>
                    Choose input…
                  </option>
                  {inputs.map((device) => (
                    <option key={device.index} value={device.name}>
                      {device.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span className="field-with-icon">
                  <span className="field-icon">{Icons.speaker}</span>
                  Output
                </span>
                <select value={outputName} onChange={(event) => setOutputName(event.target.value)}>
                  <option value="" disabled>
                    Choose output…
                  </option>
                  {outputs.map((device) => (
                    <option key={device.index} value={device.name}>
                      {device.name}
                    </option>
                  ))}
                </select>
              </label>
              {(bootError || desk.error) && <p className="desk-error">{bootError || desk.error}</p>}
              <div className="setup-start">
                {sameSitting ? (
                  <p className="setup-hint">
                    This show is still open for {resumeMinutes} minutes. Keep that recording, or start a new one.
                    A hole is marked if it was off.
                  </p>
                ) : desk.resumable ? (
                  <p className="setup-hint">The name changed, so this start is a new recording.</p>
                ) : !setupReady ? (
                  <p className="setup-hint">
                    {[
                      !service.trim() && "provider",
                      !content.trim() && "type",
                      !show.trim() && "name",
                      !inputName.trim() && "input",
                      !outputName.trim() && "output",
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                ) : null}
                <button
                  type="button"
                  className="start-ohush"
                  disabled={busy || !setupReady}
                  onClick={() => void start(false, true)}
                >
                  <span className="start-ohush-icon">{Icons.start}</span>
                  {sameSitting ? "Keep recording" : "Record only"}
                </button>
                <button
                  type="button"
                  className="start-secondary"
                  disabled={busy || !setupReady}
                  onClick={() => void start(false, false)}
                >
                  Best model
                </button>
                {sameSitting ? (
                  <button
                    type="button"
                    className="start-secondary"
                    disabled={busy}
                    onClick={() => void start(true)}
                  >
                    New recording
                  </button>
                ) : null}
              </div>
            </div>
          </section>
        </div>
      </main>
    );
  }

  return (
    <main
      className={[
        "desk light app-shell live",
        commercial ? "break" : "",
        testMode ? "test-mode" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <header className="app-header live-header">
        <div className="app-brand compact">
          <BrandMark tone="color" className="brand-bar" />
        </div>
        <div className="site-meta">
          <p className="meta-title">{title}</p>
          <p className="meta-sub">
            {where}
            {recordingOnly ? <span> · Record only</span> : <span> · Best model</span>}
            {timeNote ? <span className="mono"> · {timeNote}</span> : null}
          </p>
        </div>
      </header>

      {testMode ? <p className="preview-banner">Test mode · nothing is recorded</p> : null}
      {recordingOnly ? (
        <p className="preview-banner">Record only · TV audio passes through · no ad cover</p>
      ) : null}

      <div className="app-scroll live-layout">
        <div className="live-col">
          <section className="app-group">
            <p className="app-group-label">Now Hearing</p>
            <div className="app-group-body">
              <div className={commercial && !recordingOnly ? "status-line break" : "status-line game"}>
                <strong>{recordingOnly ? "Recording" : commercial ? "Commercial break" : "The show"}</strong>
                <span>
                  {recordingOnly
                    ? title
                    : commercial
                      ? (SOUND_LABEL[desk.replacement] ?? desk.replacement)
                      : title}
                </span>
              </div>
              <LiveMeter dbfs={desk.input_dbfs} recording={!testMode} label="TV signal" compact />
            </div>
          </section>

          <section className="app-group">
            <p className="app-group-label">Session</p>
            <div className="app-group-body">
              {recordingOnly ? (
                <p className="setup-help">The television stays on the speakers. The optical audio is being saved.</p>
              ) : (
                <CoverLine
                  score={desk.audio_score}
                  bar={desk.cover_bar}
                  fallback={desk.tnf?.mode === "auto" ? 0.14 : 0.22}
                  busy={busy}
                  onPick={(value) => void post("/mode", { record_only: false, cover_bar: value })}
                />
              )}
            </div>
          </section>
        </div>

        <div className="live-col">
          {recordingOnly ? null : (
          <section className="app-group">
            <p className="app-group-label">Cover sound</p>
            <div className="app-group-body sound-picks">
              {(desk.sounds.length ? desk.sounds : Object.keys(SOUND_LABEL)).map((name) => (
                <button
                  key={name}
                  type="button"
                  className={desk.replacement === name ? "sound-pick on" : "sound-pick"}
                  disabled={busy}
                  onClick={() => void post("/override", { action: `sound_${name}` })}
                >
                  {SOUND_LABEL[name] ?? name}
                </button>
              ))}
            </div>
          </section>
          )}

          <section className="app-group">
            {desk.chunks.length ? (
              <details className="live-more flat">
                <summary>Replay</summary>
                <div className="app-group-body">
                  <ul className="replay-list">
                    {desk.chunks.map((name) => (
                      <li key={name}>
                        <IconTip tip={`Play ${name}`} onClick={() => setPlaying(name)}>
                          {Icons.replay}
                        </IconTip>
                        <span className="soft">{name.replace("audio_", "Part ").replace(".wav", "")}</span>
                        {playing === name ? <audio controls autoPlay src={`http://127.0.0.1:8770/media/${name}`} /> : null}
                      </li>
                    ))}
                  </ul>
                </div>
              </details>
            ) : null}
          </section>
        </div>
      </div>

      <footer className="app-dock">
        <button
          type="button"
          className={recordingOnly ? "live-action show" : "live-action pass"}
          disabled={busy || testMode}
          onClick={() => void post("/mode", { record_only: true })}
        >
          Record only
        </button>
        <button
          type="button"
          className={recordingOnly ? "live-action pass" : "live-action ad"}
          disabled={busy || testMode}
          onClick={() => void post("/mode", { record_only: false })}
        >
          Best model
        </button>
        {recordingOnly ? null : (
          <button
            type="button"
            className="live-action show"
            disabled={busy}
            onClick={() => void post("/override", { action: "play" })}
          >
            Show the game
          </button>
        )}
        <button
          type="button"
          className="live-action pass"
          disabled={busy}
          onClick={() => {
            if (window.confirm("End this recording? Audio already saved stays.")) void post("/stop", {});
          }}
        >
          End recording
        </button>
      </footer>
    </main>
  );
}
