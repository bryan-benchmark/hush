"use client";

import { useState } from "react";
import { BrandMark } from "@/components/BrandMark";
import { LiveMeter } from "@/components/LiveMeter";
import { MarkControls } from "@/components/MarkControls";
import { MarkerList } from "@/components/MarkerList";
import type { useLiveStatus } from "@/hooks/useLiveStatus";
import type { LiveStatus, OperatorMode } from "@/lib/live";

type LiveApi = ReturnType<typeof useLiveStatus>;

const MODES: { id: OperatorMode; label: string }[] = [
  { id: "pass_through", label: "PASS-THROUGH" },
  { id: "manual", label: "MANUAL" },
  { id: "auto", label: "AUTO" },
];

function formatClock(seconds: number) {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
}

function formatRate(rate: number | null) {
  if (rate == null) return "—";
  // Avoid locale-dependent SSR/client hydration mismatches.
  return `${Math.round(rate)} Hz`;
}

function alarms(status: LiveStatus) {
  const rows: { title: string; detail: string }[] = [];
  if (status.input_silent) {
    rows.push({
      title: "INPUT SILENT",
      detail: "Input has stayed under −80 dBFS for 5 seconds.",
    });
  }
  if (status.xruns > 0) {
    const parts = [
      status.ring_overruns ? `ring overruns ${status.ring_overruns}` : "",
      status.ring_underruns ? `ring underruns ${status.ring_underruns}` : "",
      status.input_portaudio_flags
        ? `input portaudio ${status.input_portaudio_flags}`
        : "",
      status.output_portaudio_flags
        ? `output portaudio ${status.output_portaudio_flags}`
        : "",
    ].filter(Boolean);
    rows.push({ title: "AUDIO XRUN", detail: parts.join(" · ") });
  }
  if (status.record_queue_drops > 0) {
    rows.push({
      title: "RECORDING DEGRADED",
      detail: `${status.record_queue_drops} gap${status.record_queue_drops === 1 ? "" : "s"} filled with silence so session time stays intact.`,
    });
  }
  if (status.input_disconnected) {
    rows.push({
      title: "INPUT DEVICE DISCONNECTED",
      detail: "The selected USB input disappeared. Gate returned to PLAY.",
    });
  }
  if (status.output_disconnected) {
    rows.push({
      title: "OUTPUT DEVICE DISCONNECTED",
      detail: "The selected output disappeared. Gate returned to PLAY.",
    });
  }
  if (status.sample_rate_mismatch) {
    rows.push({
      title: "SAMPLE RATE MISMATCH",
      detail: `INPUT ${formatRate(status.input_rate_hz)} · OUTPUT ${formatRate(status.output_rate_hz)}${status.host_resampling ? " · RESAMPLING" : ""}`,
    });
  }
  if (status.engine_stalled) {
    rows.push({
      title: "AUDIO ENGINE STALLED",
      detail: "A callback stopped advancing. Gate returned to PLAY.",
    });
  }
  const known = new Set(rows.map((row) => row.title));
  if (status.error && !known.has(status.error)) {
    rows.push({ title: status.error, detail: "" });
  }
  return rows;
}

function transportLine(status: LiveStatus) {
  if (status.transport === "priming") {
    return `PRIMING ${Math.round(status.buffer_ms)}/${Math.round(status.buffer_target_ms)} ms`;
  }
  if (status.transport === "running") return "RUNNING";
  return "STOPPED";
}

export function LivePanel({ api }: { api: LiveApi }) {
  const { status, connected, devices, actionError } = api;
  const banners = alarms(status);
  const manual = status.mode === "manual" && status.recording;
  const [inputIndex, setInputIndex] = useState<number | null>(null);
  const [outputIndex, setOutputIndex] = useState<number | null>(null);

  const start = () => {
    const input = devices.inputs.find((device) => device.index === inputIndex);
    const output = devices.outputs.find((device) => device.index === outputIndex);
    if (!input || !output) return;
    void api.startSession(input.name, output.name);
  };

  return (
    <main
      className={banners.length ? "shell live-shell alarm" : "shell live-shell"}
      suppressHydrationWarning
    >
      <div className="atmosphere" aria-hidden="true" suppressHydrationWarning />
      <header className="top">
        <BrandMark />
        <p className="tag">live audio · pass-through</p>
      </header>

      {banners.length ? (
        <div className="banners" role="alert">
          {banners.map((banner) => (
            <p key={banner.title} className="banner">
              <strong>{banner.title}</strong>
              {banner.detail ? <span>{banner.detail}</span> : null}
            </p>
          ))}
        </div>
      ) : null}

      {!connected ? (
        <p className="device">
          Start <span className="mono">python recorder.py --live</span> to choose devices.
        </p>
      ) : null}

      <section className="mode-row" aria-label="Operator mode">
        {MODES.map((mode) => (
          <button
            key={mode.id}
            type="button"
            className={status.mode === mode.id ? "mode-btn active" : "mode-btn"}
            disabled={!connected}
            onClick={() => void api.setMode(mode.id)}
          >
            {mode.label}
          </button>
        ))}
      </section>
      <p className="device">
        PASS-THROUGH disables the gate. Audio still runs through the ring.
        {status.mode === "auto"
          ? " AUTO cannot mute. The frozen detector stays offline until discontinuity_causal_v1."
          : " AUTO stays visible and cannot mute until discontinuity_causal_v1."}
      </p>

      {status.standby || !status.recording ? (
        <section className="device-form">
          <label>
            Input
            <select
              value={inputIndex == null ? "" : String(inputIndex)}
              onChange={(event) => {
                const next = event.target.value;
                setInputIndex(next === "" ? null : Number(next));
              }}
            >
              <option value="" disabled>
                USB optical capture
              </option>
              {devices.inputs.map((device) => (
                <option key={`in-${device.index}`} value={device.index}>
                  [{device.index}] {device.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Output
            <select
              value={outputIndex == null ? "" : String(outputIndex)}
              onChange={(event) => {
                const next = event.target.value;
                setOutputIndex(next === "" ? null : Number(next));
              }}
            >
              <option value="" disabled>
                Headphone jack
              </option>
              {devices.outputs.map((device) => (
                <option key={`out-${device.index}`} value={device.index}>
                  [{device.index}] {device.name}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="mode-btn active"
            disabled={!connected || inputIndex == null || outputIndex == null}
            onClick={start}
          >
            Start
          </button>
        </section>
      ) : null}

      <section className="live-grid">
        <Endpoint
          title="Input"
          name={status.input_device_name}
          rate={status.input_rate_hz}
          deviceRate={status.input_default_rate_hz}
          channels={status.input_channels}
          dbfs={status.input_dbfs}
          recording={status.recording}
          healthy={status.recording && !status.input_silent && !status.input_disconnected}
          tag={status.input_disconnected ? "DISCONNECTED" : status.input_silent ? "SILENT" : "GOOD"}
        />
        <Endpoint
          title="Output"
          name={status.output_device_name}
          rate={status.output_rate_hz}
          deviceRate={status.output_default_rate_hz}
          channels={status.output_channels}
          dbfs={status.output_dbfs}
          recording={status.recording && status.gate === "play"}
          healthy={status.recording && !status.output_disconnected && status.gate === "play"}
          tag={
            status.output_disconnected
              ? "DISCONNECTED"
              : status.gate === "mute"
                ? "MUTED"
                : "GOOD"
          }
        />
      </section>

      {status.gate === "mute" ? (
        <p className="sanity">
          While muted, input should keep moving and output should sit at silence.
        </p>
      ) : null}

      <section className="gate-row">
        <div>
          <p className="stat-label">Audio gate</p>
          <p className={status.gate === "mute" ? "stat-value mute" : "stat-value play"}>
            {status.gate === "mute" ? "MUTED" : "PLAYING"}
          </p>
          {status.gate_reason ? (
            <p className="device">Reason {status.gate_reason}</p>
          ) : null}
        </div>
        <div>
          <p className="stat-label">Audio</p>
          <p className={status.transport === "priming" ? "stat-value priming" : "stat-value"}>
            {transportLine(status)}
          </p>
        </div>
        <div className="gate-actions">
          <button type="button" disabled={!manual || status.gate === "mute"} onClick={() => void api.setGate("mute")}>
            MUTE
          </button>
          <button type="button" disabled={!manual || status.gate === "play"} onClick={() => void api.setGate("unmute")}>
            UNMUTE
          </button>
          <button type="button" disabled={!manual} onClick={() => void api.setGate("test_mute")}>
            TEST MUTE 2 SEC
          </button>
        </div>
      </section>

      {actionError ? <p className="mark-error">{actionError}</p> : null}

      <section className="stat-grid">
        <Stat
          label="Buffer"
          value={`${status.buffer_ms.toFixed(0)} ms`}
          detail={
            status.buffer_min_ms == null
              ? "min — / max —"
              : `min ${status.buffer_min_ms.toFixed(0)} / max ${status.buffer_max_ms?.toFixed(0)}`
          }
          bad={false}
        />
        <Stat
          label="Xruns"
          value={String(status.xruns)}
          detail="portaudio + ring"
          bad={status.xruns > 0}
        />
        <Stat
          label="Input portaudio"
          value={String(status.input_portaudio_flags)}
          bad={status.input_portaudio_flags > 0}
        />
        <Stat
          label="Output portaudio"
          value={String(status.output_portaudio_flags)}
          bad={status.output_portaudio_flags > 0}
        />
        <Stat
          label="Ring overruns"
          value={String(status.ring_overruns)}
          bad={status.ring_overruns > 0}
        />
        <Stat
          label="Ring underruns"
          value={String(status.ring_underruns)}
          bad={status.ring_underruns > 0}
        />
        <Stat
          label="Record gaps"
          value={String(status.record_queue_drops)}
          detail={status.recording_integrity}
          bad={status.record_queue_drops > 0}
        />
        <Stat
          label="Reprimes"
          value={String(status.reprime_count)}
          bad={status.reprime_count > 0}
        />
        <Stat
          label="Latency"
          value={
            status.estimated_transport_latency_ms == null
              ? "—"
              : `${status.estimated_transport_latency_ms.toFixed(0)} ms`
          }
          detail={latencyDetail(status)}
          bad={false}
        />
        <Stat
          label="Near zero"
          value={`${Math.round(status.near_zero_fraction * 100)}%`}
          bad={false}
        />
        <Stat label="Session" value={formatClock(status.elapsed_seconds)} bad={false} />
      </section>

      {status.recording ? (
        <button type="button" className="mode-btn" onClick={() => void api.stopSession()}>
          Stop session
        </button>
      ) : null}

      {status.folder ? <p className="folder mono">{status.folder}</p> : null}

      <details className="optional-marks">
        <summary>Optional rough marks</summary>
        <MarkControls disabled={!status.recording} onMark={api.mark} />
        <section className="log">
          <h2>Markers</h2>
          <MarkerList markers={status.markers} />
        </section>
      </details>

      <p className="folder mono">
        <a href="/label">Open ad labeler →</a>
      </p>
    </main>
  );
}

function latencyDetail(status: LiveStatus) {
  if (status.input_stream_latency_ms == null && status.output_stream_latency_ms == null) {
    return "buffer only";
  }
  const buffer = `${status.buffer_ms.toFixed(0)} buffer`;
  const input =
    status.input_stream_latency_ms == null
      ? ""
      : `${status.input_stream_latency_ms.toFixed(0)} in`;
  const output =
    status.output_stream_latency_ms == null
      ? ""
      : `${status.output_stream_latency_ms.toFixed(0)} out`;
  return [buffer, input, output].filter(Boolean).join(" + ");
}

function Endpoint({
  title,
  name,
  rate,
  deviceRate,
  channels,
  dbfs,
  recording,
  healthy,
  tag,
}: {
  title: string;
  name: string | null;
  rate: number | null;
  deviceRate: number | null;
  channels: number | null;
  dbfs: number;
  recording: boolean;
  healthy: boolean;
  tag: string;
}) {
  const rateDiffers =
    rate != null && deviceRate != null && Math.round(rate) !== Math.round(deviceRate);
  return (
    <section className="endpoint">
      <div className="endpoint-head">
        <p className="stat-label">{title}</p>
        <p className={healthy ? "health good" : tag === "MUTED" ? "health mute" : "health bad"}>
          {tag}
        </p>
      </div>
      <p className="endpoint-name">{name ?? "Not selected"}</p>
      <p className="device">
        {formatRate(rate)} / {channels ?? "—"} ch
        {rateDiffers ? ` · device ${formatRate(deviceRate)}` : ""}
      </p>
      <LiveMeter dbfs={dbfs} recording={recording} compact />
    </section>
  );
}

function Stat({
  label,
  value,
  detail,
  bad,
}: {
  label: string;
  value: string;
  detail?: string;
  bad: boolean;
}) {
  return (
    <div className={bad ? "stat bad" : "stat"}>
      <p className="stat-label">{label}</p>
      <p className="stat-value">{value}</p>
      {detail ? <p className="device">{detail}</p> : null}
    </div>
  );
}
