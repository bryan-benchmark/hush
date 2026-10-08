"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { BrandMark } from "@/components/BrandMark";
import { LiveMeter } from "@/components/LiveMeter";

const SOUND_LABEL: Record<string, string> = {
  silence: "Silence",
  stadium: "Crowd",
  rain: "Rain",
  fireplace: "Fire",
  pink: "Pink",
  brown: "Brown",
};

const SERVICES = ["Prime Video", "Netflix", "YouTube TV", "Hulu", "Cable / antenna", "Other"];
const KINDS = [
  { id: "sports", label: "Live sports" },
  { id: "scripted", label: "A show" },
  { id: "other", label: "Something else" },
];

type DeskState = {
  state: "PROGRAM" | "REPLACEMENT";
  auto: boolean;
  replacement: string;
  sounds: string[];
  timestamp: number;
  input_dbfs: number;
  recording: boolean;
  input_name: string;
  output_name: string;
  error: string;
  events: { t?: number; state?: string; decision_source?: string; replacement?: string; human_override?: boolean }[];
  chunks: string[];
  show?: string;
  service?: string;
  content?: string;
};

type Device = { index: number; name: string };

const EMPTY: DeskState = {
  state: "PROGRAM",
  auto: true,
  replacement: "stadium",
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
};

function clock(seconds: number) {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
}

function pickDefault(devices: Device[], prefer: RegExp) {
  return devices.find((row) => prefer.test(row.name))?.name || devices[0]?.name || "";
}

export function SportsDashboard() {
  const [desk, setDesk] = useState<DeskState>(EMPTY);
  const [ready, setReady] = useState(false);
  const [bootError, setBootError] = useState("");
  const [inputs, setInputs] = useState<Device[]>([]);
  const [outputs, setOutputs] = useState<Device[]>([]);
  const [show, setShow] = useState("Buccaneers at Cowboys");
  const [service, setService] = useState("Prime Video");
  const [content, setContent] = useState("sports");
  const [inputName, setInputName] = useState("");
  const [outputName, setOutputName] = useState("");
  const [busy, setBusy] = useState(false);
  const [playing, setPlaying] = useState<string | null>(null);

  const applyState = useCallback((next: DeskState) => {
    setDesk({
      ...EMPTY,
      ...next,
      events: next.events ?? [],
      chunks: next.chunks ?? [],
      sounds: next.sounds?.length ? next.sounds : EMPTY.sounds,
    });
  }, []);

  const boot = useCallback(async () => {
    setBootError("");
    try {
      const res = await fetch("/api/live/boot", { method: "POST" });
      const payload = (await res.json()) as {
        ok?: boolean;
        error?: string;
        devices?: { inputs?: Device[]; outputs?: Device[] };
        state?: DeskState;
      };
      if (!res.ok || payload.ok === false) {
        setBootError(payload.error || "Could not get ready.");
        setReady(false);
        return;
      }
      const nextInputs = payload.devices?.inputs ?? [];
      const nextOutputs = payload.devices?.outputs ?? [];
      setInputs(nextInputs);
      setOutputs(nextOutputs);
      setInputName((current) => current || pickDefault(nextInputs, /usb|optical|capture/i));
      setOutputName((current) => current || pickDefault(nextOutputs, /headphone|external|airpods/i));
      if (payload.state) applyState(payload.state);
      if (payload.state?.show) setShow(payload.state.show);
      if (payload.state?.service) setService(payload.state.service);
      if (payload.state?.content) setContent(payload.state.content);
      setReady(true);
    } catch {
      setBootError("Could not get ready on this Mac.");
      setReady(false);
    }
  }, [applyState]);

  useEffect(() => {
    void boot();
  }, [boot]);

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const res = await fetch("/api/live/state", { cache: "no-store" });
        if (!res.ok) return;
        const next = (await res.json()) as DeskState;
        if (!cancelled) applyState(next);
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
  }, [ready, applyState]);

  const refreshDevices = useCallback(async () => {
    try {
      const res = await fetch("/api/live/devices", { cache: "no-store" });
      if (!res.ok) return;
      const payload = (await res.json()) as { inputs?: Device[]; outputs?: Device[] };
      const nextInputs = payload.inputs ?? [];
      const nextOutputs = payload.outputs ?? [];
      setInputs(nextInputs);
      setOutputs(nextOutputs);
      setInputName((current) =>
        nextInputs.some((row) => row.name === current)
          ? current
          : pickDefault(nextInputs, /usb|optical|capture/i),
      );
      setOutputName((current) =>
        nextOutputs.some((row) => row.name === current)
          ? current
          : pickDefault(nextOutputs, /headphone|external|airpods|usb/i),
      );
    } catch {
      // keep last list
    }
  }, []);

  useEffect(() => {
    if (!ready || desk.recording) return;
    void refreshDevices();
    const timer = setInterval(() => void refreshDevices(), 1500);
    return () => clearInterval(timer);
  }, [ready, desk.recording, refreshDevices]);

  const post = useCallback(
    async (path: string, body: unknown = {}) => {
      setBusy(true);
      try {
        const res = await fetch(`/api/live${path}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const payload = (await res.json().catch(() => null)) as DeskState | null;
        if (payload) applyState(payload);
        return payload;
      } finally {
        setBusy(false);
      }
    },
    [applyState],
  );

  const start = async () => {
    const payload = await post("/start", {
      show,
      service,
      content,
      input: inputName,
      output: outputName,
    });
    if (payload?.error) setBootError(payload.error);
    else setBootError("");
  };

  const commercial = desk.state === "REPLACEMENT";
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

  if (!ready) {
    return (
      <main className="desk light">
        <header className="masthead">
          <div className="masthead-brand">
            <BrandMark tone="color" className="brand-hero" />
            <p className="masthead-sub">Take Down Big Audio</p>
          </div>
        </header>
        <section className="panel">
          <h1>Getting ready</h1>
          <p className="lead">One moment while OHush wakes up on this Mac.</p>
          {bootError ? (
            <>
              <p className="desk-error">{bootError}</p>
              <button className="btn primary" onClick={() => void boot()}>
                Try again
              </button>
            </>
          ) : (
            <p className="soft">Starting…</p>
          )}
        </section>
      </main>
    );
  }

  if (!desk.recording) {
    return (
      <main className="desk light">
        <header className="masthead">
          <div className="masthead-brand">
            <BrandMark tone="color" className="brand-hero" />
            <p className="masthead-sub">Take Down Big Audio</p>
          </div>
        </header>

        <section className="panel">
          <h1>What are you watching?</h1>
          <label className="field">
            <span>Title</span>
            <input
              value={show}
              onChange={(event) => setShow(event.target.value)}
              placeholder="Buccaneers at Cowboys"
              autoFocus
            />
          </label>
          <label className="field">
            <span>Where</span>
            <select value={service} onChange={(event) => setService(event.target.value)}>
              {SERVICES.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <div className="chip-row" role="group" aria-label="Kind of show">
            {KINDS.map((kind) => (
              <button
                key={kind.id}
                type="button"
                className={content === kind.id ? "chip on" : "chip"}
                onClick={() => setContent(kind.id)}
              >
                {kind.label}
              </button>
            ))}
          </div>

          <hr className="rule" />

          <h2>How should we listen?</h2>
          <p className="lead">
            Turn the TV speakers down. Leave optical into the USB box. Send this Mac to your soundbar over aux — or
            whatever output appears when you plug it in.
          </p>
          <label className="field">
            <span>From the TV</span>
            <select value={inputName} onChange={(event) => setInputName(event.target.value)}>
              {inputs.map((device) => (
                <option key={device.index} value={device.name}>
                  {device.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Hear it on</span>
            <select value={outputName} onChange={(event) => setOutputName(event.target.value)}>
              {outputs.map((device) => (
                <option key={device.index} value={device.name}>
                  {device.name}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="text-btn" onClick={() => void refreshDevices()}>
            Refresh devices
          </button>
          {(bootError || desk.error) && <p className="desk-error">{bootError || desk.error}</p>}
          <button
            className="btn primary wide"
            disabled={busy || !show.trim() || !inputName || !outputName}
            onClick={() => void start()}
          >
            Start watching
          </button>
        </section>
      </main>
    );
  }

  return (
    <main className={commercial ? "desk light live break" : "desk light live"}>
      <header className="site-bar">
        <BrandMark tone="color" className="brand-bar" />
        <div className="site-meta">
          <p className="meta-title">{title}</p>
          <p className="meta-sub">
            {where}
            <span className="mono"> · {clock(desk.timestamp)}</span>
          </p>
        </div>
      </header>

      <section className={commercial ? "status break" : "status game"}>
        <p className="status-kicker">{commercial ? "Commercial break" : "Now playing"}</p>
        <h1>{commercial ? SOUND_LABEL[desk.replacement] ?? desk.replacement : title}</h1>
        <p className="lead">{desk.auto ? "Ads swap automatically. You can always override." : "You’re driving every swap."}</p>
      </section>

      <div className="action-dock">
        <button className="btn show" disabled={busy} onClick={() => void post("/override", { action: "play" })}>
          Back to the show
        </button>
        <button className="btn ad" disabled={busy} onClick={() => void post("/override", { action: "mute" })}>
          Cover this ad
        </button>
      </div>

      <section className="panel">
        <h2>During ads, play</h2>
        <div className="chip-row sounds">
          {(desk.sounds.length ? desk.sounds : Object.keys(SOUND_LABEL)).map((name) => (
            <button
              key={name}
              type="button"
              className={desk.replacement === name ? "chip on" : "chip"}
              disabled={busy}
              onClick={() => void post("/override", { action: `sound_${name}` })}
            >
              {SOUND_LABEL[name] ?? name}
            </button>
          ))}
        </div>
        <div className="rate-block">
          <span>How’s this sound?</span>
          <div className="chip-row">
            {[1, 2, 3, 4, 5].map((score) => (
              <button
                key={score}
                type="button"
                className="chip"
                disabled={busy}
                onClick={() => void post("/override", { action: `rate${score}` })}
              >
                {score}
              </button>
            ))}
          </div>
          <div className="chip-row">
            <button type="button" className="chip" disabled={busy} onClick={() => void post("/override", { action: "want_yes" })}>
              Keep every break
            </button>
            <button type="button" className="chip" disabled={busy} onClick={() => void post("/override", { action: "want_no" })}>
              Not every break
            </button>
          </div>
        </div>
      </section>

      <section className="panel">
        <LiveMeter dbfs={desk.input_dbfs} recording label="TV signal" />
        <div className="chip-row" style={{ marginTop: "1rem" }}>
          <button
            type="button"
            className="chip"
            disabled={busy}
            onClick={() =>
              void (async () => {
                await post("/label", { verdict: "program", about: desk.timestamp });
                await post("/override", { action: "play" });
              })()
            }
          >
            That was the show
          </button>
          <button
            type="button"
            className="chip"
            disabled={busy}
            onClick={() =>
              void (async () => {
                await post("/label", { verdict: "commercial", about: desk.timestamp });
                if (!commercial) await post("/override", { action: "mute" });
              })()
            }
          >
            That was an ad
          </button>
          <button type="button" className="chip" disabled={busy} onClick={() => void post("/override", { action: "auto" })}>
            {desk.auto ? "Pause auto" : "Resume auto"}
          </button>
          <button
            type="button"
            className="chip danger"
            disabled={busy}
            onClick={() => {
              if (window.confirm("Stop watching and end this recording?")) void post("/stop", {});
            }}
          >
            End session
          </button>
        </div>
      </section>

      <section className="panel">
        <h2>Breaks tonight</h2>
        <ol className="break-list">
          {breaks.length === 0 ? <li className="soft">No ads marked yet. Cover one anytime.</li> : null}
          {breaks.map((span) => (
            <li key={`${span.start}-${span.live}`}>
              <div>
                <strong>
                  {clock(span.start)} – {span.live ? "now" : clock(span.end)}
                </strong>
                <span>{SOUND_LABEL[span.sound] ?? span.sound}</span>
              </div>
              <div className="chip-row">
                <button type="button" className="chip" disabled={busy} onClick={() => void post("/label", { verdict: "program", about: span.start })}>
                  Was show
                </button>
                <button type="button" className="chip" disabled={busy} onClick={() => void post("/label", { verdict: "commercial", about: span.start })}>
                  Was ad
                </button>
              </div>
            </li>
          ))}
        </ol>
      </section>

      {desk.chunks.length ? (
        <section className="panel">
          <h2>Replay</h2>
          <ul className="replay-list">
            {desk.chunks.map((name) => (
              <li key={name}>
                <button type="button" className="chip" onClick={() => setPlaying(name)}>
                  {name.replace("audio_", "Part ").replace(".wav", "")}
                </button>
                {playing === name ? <audio controls autoPlay src={`http://127.0.0.1:8770/media/${name}`} /> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </main>
  );
}
