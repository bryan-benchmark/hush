"use client";

import { useEffect, useState } from "react";

type Row = { session: string; acoustic: boolean; vision: boolean; combined: boolean };

type Status = {
  updated_utc?: string;
  accepted_sessions?: number;
  channels_ready?: { acoustic: number; vision: number; combined: number; of: number };
  sessions?: Row[];
  verdict_queue?: { pending?: number; done?: number; episodes?: number; in_chunk?: number };
  scorecard?: { program_muted_s?: number | null; commercial_coverage?: number | null; broken?: boolean | null };
  shadow?: { keep?: boolean | null; drop_s?: number | null; reason?: string | null };
  job?: {
    phase?: string;
    session?: string;
    session_i?: number;
    session_of?: number;
    hop_i?: number;
    hop_of?: number;
    t?: number;
    model?: string;
    note?: string;
    updated_utc?: string;
  };
  services?: Record<string, boolean>;
  links?: { verdict?: string; farm?: string; local_viewer?: string };
};

function mark(ok: boolean | undefined) {
  return ok ? "yes" : "—";
}

export default function LabStatusPage() {
  const [data, setData] = useState<Status | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    let dead = false;
    async function load() {
      try {
        const res = await fetch("/api/lab-status", { cache: "no-store" });
        if (!res.ok) throw new Error(`status ${res.status}`);
        const body = (await res.json()) as Status;
        if (!dead) {
          setData(body);
          setErr("");
        }
      } catch (e) {
        if (!dead) setErr(e instanceof Error ? e.message : String(e));
      }
    }
    void load();
    const id = window.setInterval(() => void load(), 4000);
    return () => {
      dead = true;
      window.clearInterval(id);
    };
  }, []);

  const ch = data?.channels_ready;
  const q = data?.verdict_queue;
  const sc = data?.scorecard;
  const job = data?.job || {};
  const hopPct =
    job.hop_i && job.hop_of ? Math.round((100 * Number(job.hop_i)) / Number(job.hop_of)) : null;

  return (
    <main className="shell identity-shell">
      <div className="atmosphere" aria-hidden="true" />
      <header className="top">
        <p className="tag">Lab</p>
        <h1 className="identity-ask">Status</h1>
        <p className="identity-note">
          Vision + ASR + acoustic on farm takes. Disagrees go to{" "}
          <a href={data?.links?.verdict || "/verdict"}>verdict</a>.
        </p>
      </header>

      {err ? <p className="device">{err}</p> : null}

      <section className="identity-card" style={{ display: "grid", gap: "0.85rem" }}>
        <div>
          <p className="tag">Now</p>
          <p style={{ margin: 0, fontSize: "1.05rem" }}>
            {job.phase === "vision" ? (
              <>
                Vision <b>{job.session_i || "?"}/{job.session_of || "?"}</b>
                {job.session ? (
                  <>
                    {" "}
                    · <code>{String(job.session).replace(/^2026/, "")}</code>
                  </>
                ) : null}
                {hopPct != null ? <> · hop {hopPct}%</> : null}
                {job.t != null ? <> · t={job.t}s</> : null}
              </>
            ) : job.phase === "idle" || job.note ? (
              <>{job.note || "Idle"}</>
            ) : (
              <>Waiting for lab heartbeat…</>
            )}
          </p>
          <p className="identity-note" style={{ marginBottom: 0 }}>
            Updated {data?.updated_utc || "—"}
            {job.model ? ` · ${job.model}` : ""}
          </p>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: "0.75rem" }}>
          <div>
            <p className="tag">Channels</p>
            <p style={{ margin: 0 }}>
              vision <b>{ch?.vision ?? "—"}</b>/{ch?.of ?? "—"}
              <br />
              acoustic <b>{ch?.acoustic ?? "—"}</b>/{ch?.of ?? "—"}
            </p>
          </div>
          <div>
            <p className="tag">Verdict</p>
            <p style={{ margin: 0 }}>
              pending <b>{q?.pending ?? "—"}</b>
              <br />
              done <b>{q?.done ?? "—"}</b>/{q?.episodes ?? "—"}
            </p>
          </div>
          <div>
            <p className="tag">Live score</p>
            <p style={{ margin: 0 }}>
              muted <b>{sc?.program_muted_s ?? "—"}</b>s
              <br />
              cov <b>{sc?.commercial_coverage ?? "—"}</b>
              {sc?.broken ? " · broken" : ""}
            </p>
          </div>
        </div>

        <div>
          <p className="tag">Services</p>
          <p style={{ margin: 0, fontFamily: "var(--font-mono)", fontSize: "0.85rem" }}>
            viewer {mark(data?.services?.viewer_3020)} · engine {mark(data?.services?.engine_8770)} ·
            monitor {mark(data?.services?.monitor_3010)}
          </p>
        </div>

        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
          <a className="arrow-btn finish" href="/verdict">
            Open verdict
          </a>
          <a className="arrow-btn" href="/farm">
            Farm
          </a>
        </div>
      </section>

      <section className="identity-card" style={{ marginTop: "1rem", overflowX: "auto" }}>
        <p className="tag">Twelve sessions</p>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
          <thead>
            <tr style={{ textAlign: "left" }}>
              <th style={{ padding: "0.35rem 0.4rem" }}>Session</th>
              <th>Ac</th>
              <th>Vi</th>
              <th>Jo</th>
            </tr>
          </thead>
          <tbody>
            {(data?.sessions || []).map((r) => (
              <tr key={r.session} style={{ borderTop: "1px solid rgba(0,0,0,0.08)" }}>
                <td style={{ padding: "0.35rem 0.4rem", fontFamily: "var(--font-mono)" }}>
                  {r.session.replace(/^202611/, "").replace(/^2026/, "")}
                </td>
                <td>{r.acoustic ? "●" : "○"}</td>
                <td>{r.vision ? "●" : "○"}</td>
                <td>{r.combined ? "●" : "○"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="identity-note" style={{ marginBottom: 0 }}>
          Ac acoustic · Vi vision · Jo combined hops
        </p>
      </section>
    </main>
  );
}
