import { NextResponse } from "next/server";
import fs from "fs";
import path from "path";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function dataRoot() {
  return process.env.OHUSH_DATA_ROOT || "C:\\OHushData";
}

function readJson(p: string): Record<string, unknown> | null {
  try {
    if (!fs.existsSync(p)) return null;
    return JSON.parse(fs.readFileSync(p, "utf8")) as Record<string, unknown>;
  } catch {
    return null;
  }
}

function acceptedSessions(farmAccepted: string): string[] {
  if (!fs.existsSync(farmAccepted)) return [];
  const out: string[] = [];
  const seen = new Set<string>();
  for (const line of fs.readFileSync(farmAccepted, "utf8").split(/\r?\n/)) {
    if (!line.trim()) continue;
    try {
      const s = String((JSON.parse(line) as { session?: string }).session || "");
      if (s && !seen.has(s)) {
        seen.add(s);
        out.push(s);
      }
    } catch {
      /* skip */
    }
  }
  return out;
}

function synthesize() {
  const root = dataRoot();
  const audit = path.join(root, "indexes", "farm_labels", "audit");
  const farmAccepted = path.join(
    root,
    "gpu_lab",
    "audio_learn",
    "broadcast_labels",
    "farm_accepted.jsonl",
  );
  const sessions = acceptedSessions(farmAccepted);
  const rows = sessions.map((session) => {
    const d = path.join(audit, session);
    return {
      session,
      acoustic: fs.existsSync(path.join(d, "hops_acoustic.jsonl")),
      vision: fs.existsSync(path.join(d, "hops_vision.jsonl")),
      combined: fs.existsSync(path.join(d, "hops.jsonl")),
    };
  });
  const score = readJson(path.join(root, "indexes", "farm_labels", "LIVE_SCORECARD.json"));
  const agg = (score?.aggregate || {}) as Record<string, unknown>;
  const shadowRaw = readJson(path.join(audit, "EPISODE_YOU_SHADOW_REFIT.json"));
  const verdict = (shadowRaw?.verdict || {}) as Record<string, unknown>;
  const human = readJson(path.join(audit, "EPISODE_HUMAN_FRAMES.json"));
  const triage = readJson(path.join(audit, "EPISODE_TRIAGE.json"));
  const done = Object.keys(((human?.done as Record<string, unknown>) || {})).length;
  let episodes = 0;
  for (const s of ((triage?.sessions as Array<{ episodes?: unknown[] }>) || [])) {
    episodes += (s.episodes || []).length;
  }
  const saved = readJson(path.join(audit, "LAB_STATUS.json"));
  return {
    updated_utc: new Date().toISOString(),
    accepted_sessions: sessions.length,
    channels_ready: {
      acoustic: rows.filter((r) => r.acoustic).length,
      vision: rows.filter((r) => r.vision).length,
      combined: rows.filter((r) => r.combined).length,
      of: sessions.length,
    },
    sessions: rows,
    verdict_queue: {
      pending: Math.max(0, episodes - done),
      done,
      episodes,
    },
    scorecard: {
      program_muted_s: agg.program_muted_s ?? null,
      commercial_coverage: agg.commercial_coverage ?? null,
      broken: agg.broken ?? null,
    },
    shadow: {
      keep: verdict.keep ?? null,
      drop_s: verdict.program_muted_drop_s ?? null,
      reason: verdict.reason ?? null,
    },
    job: (saved?.job as Record<string, unknown>) || {},
    services: (saved?.services as Record<string, unknown>) || {},
    links: {
      verdict: "/verdict",
      farm: "/farm",
      local_viewer: "http://127.0.0.1:3020/",
    },
    source: saved ? "lab_status+fs" : "fs",
  };
}

export async function GET() {
  const root = dataRoot();
  const saved = readJson(path.join(root, "indexes", "farm_labels", "audit", "LAB_STATUS.json"));
  const live = synthesize();
  // Prefer fresh FS channel counts; keep job progress from the writer if newer.
  const merged = {
    ...live,
    job: {
      ...(live.job || {}),
      ...((saved?.job as Record<string, unknown>) || {}),
    },
    services: {
      ...(live.services || {}),
      ...((saved?.services as Record<string, unknown>) || {}),
    },
  };
  return NextResponse.json(merged, {
    headers: { "Cache-Control": "no-store" },
  });
}
