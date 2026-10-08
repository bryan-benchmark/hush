import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import {
  extractPeaks,
  extractSessionPeaks,
  extractSessionWaveLanes,
  extractWaveLanes,
  readRunCandidates,
  repoRoot,
  sessionWavPath,
} from "@/lib/labeling";
import { denial } from "@/lib/datasets";

export const runtime = "nodejs";

function serverLog(event: string, detail: Record<string, unknown>) {
  const row = { side: "server", at: new Date().toISOString(), event, ...detail };
  console.log("[hush-audio]", event, detail);
  try {
    const p = path.join(repoRoot(), "experiments/reports/labeler_audio_debug.jsonl");
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.appendFileSync(p, JSON.stringify(row) + "\n", "utf8");
  } catch {
    /* ignore */
  }
}

export async function GET(req: NextRequest) {
  const t0 = Date.now();
  const sp = req.nextUrl.searchParams;
  const session = sp.get("session");
  const mode = sp.get("mode") ?? "chunk";
  const buckets = Number(sp.get("buckets") ?? "320");

  if (!session) {
    return NextResponse.json({ error: "session required" }, { status: 400 });
  }
  const blocked = denial(session, sp.get("unseal"));
  if (blocked) {
    return NextResponse.json(blocked, { status: 403 });
  }

  try {
    if (mode === "break" || mode === "timeline") {
      const start = Number(sp.get("start") ?? "0");
      const duration = Number(sp.get("duration") ?? "180");
      const rich = sp.get("lanes") !== "0";
      serverLog("peaks_extract_begin", { session, mode, start, duration, buckets, rich });
      if (rich) {
        const tExtract = Date.now();
        const lanes = extractSessionWaveLanes(
          session,
          Math.max(0, start),
          duration,
          buckets,
        );
        serverLog("peaks_extract_done", {
          session,
          mode,
          start,
          duration,
          buckets,
          ms: Date.now() - t0,
          extract_ms: Date.now() - tExtract,
          peak_bins: lanes.peak.length,
          rich: true,
          // sub-ms extract ⇒ almost certainly cache hit
          cache_likely: Date.now() - tExtract < 5,
        });
        const hints = hintsFromRun(sp.get("run_id"), sp.get("proposal_id"));
        return NextResponse.json({
          window_start: Math.max(0, start),
          duration,
          sample_rate: lanes.sample_rate,
          peaks: lanes.peak,
          lanes: {
            peak: lanes.peak,
            rms: lanes.rms,
            jump: lanes.jump,
            bright: lanes.bright,
            hi: lanes.hi,
            lo: lanes.lo,
          },
          hints,
        });
      }
      const { peaks, sample_rate } = extractSessionPeaks(
        session,
        Math.max(0, start),
        duration,
        buckets,
      );
      serverLog("peaks_extract_done", {
        session,
        mode,
        start,
        duration,
        buckets,
        ms: Date.now() - t0,
        peak_bins: peaks.length,
      });
      const hints = hintsFromRun(sp.get("run_id"), sp.get("proposal_id"));
      return NextResponse.json({
        window_start: Math.max(0, start),
        duration,
        sample_rate,
        peaks,
        hints,
      });
    }

    const file = sp.get("file");
    const center = Number(sp.get("center") ?? "0");
    const radius = Number(sp.get("radius") ?? "20");
    if (!file || Number.isNaN(center)) {
      return NextResponse.json({ error: "bad params" }, { status: 400 });
    }
    const wavPath = sessionWavPath(session, file);
    const start = Math.max(0, center - radius);
    const duration = radius * 2;
    if (sp.get("lanes") !== "0") {
      const lanes = extractWaveLanes(wavPath, start, duration, buckets);
      return NextResponse.json({
        window_start: start,
        duration,
        sample_rate: lanes.sample_rate,
        peaks: lanes.peak,
        lanes: {
          peak: lanes.peak,
          rms: lanes.rms,
          jump: lanes.jump,
          bright: lanes.bright,
          hi: lanes.hi,
          lo: lanes.lo,
        },
      });
    }
    const { peaks, sample_rate } = extractPeaks(wavPath, start, duration, buckets);
    return NextResponse.json({
      window_start: start,
      duration,
      sample_rate,
      peaks,
    });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "peaks failed" },
      { status: 500 },
    );
  }
}

function hintsFromRun(runId: string | null, proposalId: string | null) {
  if (!runId || !proposalId) return null;
  const row = readRunCandidates(runId).find((c) => c.proposal_id === proposalId);
  if (!row) return null;
  const fades = Array.isArray(row.fades) ? row.fades : [];
  const suggested = row.suggested_out as { elapsed_seconds?: number } | null;
  return {
    source: "python_run",
    fades: fades.map((fade) => {
      const rowFade = fade as { elapsed_seconds?: number };
      return { elapsed: Number(rowFade.elapsed_seconds), depth: 0 };
    }),
    suggested_out:
      suggested && suggested.elapsed_seconds !== undefined
        ? Number(suggested.elapsed_seconds)
        : null,
  };
}
