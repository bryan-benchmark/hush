"use client";

import { useEffect, useState } from "react";
import { LiveMeter } from "@/components/LiveMeter";
import { LivePanel } from "@/components/LivePanel";
import { MarkControls } from "@/components/MarkControls";
import { MarkerList } from "@/components/MarkerList";
import { BrandMark } from "@/components/BrandMark";
import { useLiveStatus } from "@/hooks/useLiveStatus";

function formatElapsed(seconds: number) {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  if (h > 0) {
    return `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
  }
  return `${m}:${String(r).padStart(2, "0")}`;
}

export function MonitorApp() {
  const api = useLiveStatus();
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return <div className="shell" suppressHydrationWarning aria-busy="true" />;
  }

  if (api.connected && api.status.pipeline === "live") {
    return <LivePanel api={api} />;
  }
  const { status, connected, mark } = api;
  const live = connected && status.recording;

  return (
    <main className="shell" suppressHydrationWarning>
      <div className="atmosphere" aria-hidden="true" suppressHydrationWarning />

      <header className="top">
        <BrandMark />
        <p className="tag">research monitor · record first, label later</p>
      </header>

      <section className="hero">
        <div className="status-line">
          <span className={live ? "pill on" : "pill off"}>
            {live ? "Recording" : connected ? "Idle" : "Waiting for recorder"}
          </span>
          <span className="elapsed mono">
            {formatElapsed(status.elapsed_seconds)}
          </span>
        </div>

        <LiveMeter dbfs={status.dbfs} recording={live} />

        <p className="device">
          {status.device_name
            ? `[${status.device_index}] ${status.device_name} · ${status.sample_rate_hz} Hz · ${status.channels} ch · chunk ${String(status.chunk).padStart(4, "0")}`
            : "Start the Python recorder to stream levels here."}
        </p>
        <p className="device">
          Watch the meter. Rough commercial marks are optional — we can
          pinpoint boundaries later from the WAV.
        </p>
      </section>

      <details className="optional-marks">
        <summary>Optional rough marks (skip for now)</summary>
        <MarkControls disabled={!live} onMark={mark} />
        <section className="log">
          <h2>Markers</h2>
          <MarkerList markers={status.markers} />
        </section>
      </details>

      {status.folder ? (
        <p className="folder mono">{status.folder}</p>
      ) : null}

      <p className="folder mono">
        <a href="/label">Open ad labeler →</a>
      </p>
    </main>
  );
}
