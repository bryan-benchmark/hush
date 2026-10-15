"use client";

type Props = {
  dbfs: number;
  recording: boolean;
  label?: string;
  compact?: boolean;
};

function levelFromDbfs(dbfs: number) {
  return Math.max(0, Math.min(1, (dbfs + 60) / 60));
}

export function LiveMeter({ dbfs, recording, label, compact }: Props) {
  const levelDb = Number.isFinite(dbfs) ? dbfs : -100;
  const level = levelFromDbfs(levelDb);
  const pct = `${(level * 100).toFixed(1)}%`;
  const hot = levelDb > -3;
  const silent = levelDb <= -95;
  const tone = hot ? "#ff5a3c" : silent ? "#a894b8" : "#3dd68c";

  return (
    <div
      className={compact ? "meter meter-compact" : "meter"}
      aria-label={`${label ? `${label} ` : ""}Peak ${levelDb.toFixed(1)} dBFS`}
    >
      {label ? <p className="meter-label">{label}</p> : null}
      <div className="meter-track">
        <div
          className="meter-fill"
          style={{
            width: pct,
            background: tone,
            boxShadow: recording && !silent ? `0 0 28px ${tone}55` : "none",
          }}
        />
        <div className="meter-ticks" aria-hidden="true">
          <span>-60</span>
          <span>-40</span>
          <span>-20</span>
          <span>0</span>
        </div>
      </div>
      <div className="meter-readout">
        <span className="meter-db" style={{ color: tone }}>
          {levelDb.toFixed(1)}
        </span>
        <span className="meter-unit">dBFS</span>
      </div>
    </div>
  );
}
