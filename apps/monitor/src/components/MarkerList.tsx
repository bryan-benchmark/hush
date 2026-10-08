"use client";

import type { LiveMarker } from "@/lib/live";

type Props = {
  markers: LiveMarker[];
};

function label(type: string) {
  if (type === "ad_start") return "AD";
  if (type === "content_start") return "CONTENT";
  if (type === "note") return "NOTE";
  return type.toUpperCase();
}

export function MarkerList({ markers }: Props) {
  const items = [...markers].reverse().slice(0, 12);

  if (items.length === 0) {
    return (
      <p className="markers-empty">
        No markers yet. Hit Ad start when a commercial begins.
      </p>
    );
  }

  return (
    <ul className="markers">
      {items.map((m, i) => (
        <li key={`${m.wall_time}-${i}`} className={`marker ${m.type}`.trim()}>
          <span className="marker-type">{label(m.type)}</span>
          <span className="marker-time">{m.elapsed_seconds.toFixed(1)}s</span>
          {m.note ? <span className="marker-note">{m.note}</span> : null}
        </li>
      ))}
    </ul>
  );
}
