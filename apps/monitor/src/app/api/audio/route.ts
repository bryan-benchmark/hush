import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import {
  extractSessionRangeCached,
  extractWavSlice,
  rangeCacheStats,
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
    /* ignore log IO */
  }
}

function wavResponse(
  buf: Buffer,
  req: NextRequest,
  extra: Record<string, string> = {},
  meta: Record<string, unknown> = {},
) {
  const total = buf.length;
  const range = req.headers.get("range");
  const baseHeaders: Record<string, string> = {
    "Content-Type": "audio/wav",
    "Accept-Ranges": "bytes",
    "Cache-Control": "private, max-age=300",
    ...extra,
  };

  if (range) {
    const m = /^bytes=(\d*)-(\d*)$/.exec(range.trim());
    if (m) {
      const start = m[1] === "" ? 0 : Number(m[1]);
      let end = m[2] === "" ? total - 1 : Number(m[2]);
      if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end >= total || start > end) {
        serverLog("audio_range_416", { ...meta, range, total });
        return new NextResponse(null, {
          status: 416,
          headers: {
            ...baseHeaders,
            "Content-Range": `bytes */${total}`,
          },
        });
      }
      // Cap single range chunk so first paint is snappy; browser will request more.
      const maxChunk = 512 * 1024;
      if (end - start + 1 > maxChunk) end = start + maxChunk - 1;
      const slice = buf.subarray(start, end + 1);
      serverLog("audio_range_206", {
        ...meta,
        range,
        total_bytes: total,
        send_bytes: slice.length,
        start,
        end,
      });
      return new NextResponse(new Uint8Array(slice), {
        status: 206,
        headers: {
          ...baseHeaders,
          "Content-Length": String(slice.length),
          "Content-Range": `bytes ${start}-${end}/${total}`,
        },
      });
    }
  }

  serverLog("audio_full_200", { ...meta, total_bytes: total, range: range ?? null });
  return new NextResponse(new Uint8Array(buf), {
    headers: {
      ...baseHeaders,
      "Content-Length": String(total),
    },
  });
}

export async function GET(req: NextRequest) {
  const t0 = Date.now();
  const sp = req.nextUrl.searchParams;
  const session = sp.get("session");
  const mode = sp.get("mode") ?? "chunk";

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
      if (Number.isNaN(start) || Number.isNaN(duration)) {
        return NextResponse.json({ error: "bad start/duration" }, { status: 400 });
      }
      const startQ = Math.round(Math.max(0, start) * 10) / 10;
      const durQ = Math.round(duration * 10) / 10;
      serverLog("audio_extract_begin", {
        session,
        mode,
        start: startQ,
        duration: durQ,
        range: req.headers.get("range"),
        cache: rangeCacheStats(),
      });
      const { buf, cacheHit, key } = extractSessionRangeCached(session, startQ, durQ);
      const extract_ms = Date.now() - t0;
      serverLog("audio_extract_done", {
        session,
        mode,
        start: startQ,
        duration: durQ,
        extract_ms,
        cacheHit,
        key,
        bytes: buf.length,
        mb: Number((buf.length / (1024 * 1024)).toFixed(2)),
        friction: !cacheHit && extract_ms > 1500 ? "slow_extract" : null,
      });
      return wavResponse(
        buf,
        req,
        {
          "X-Window-Start": String(startQ),
          "X-Window-Duration": String(durQ),
          "X-Cache": cacheHit ? "HIT" : "MISS",
        },
        { session, mode, start: startQ, duration: durQ, extract_ms, cacheHit },
      );
    }

    const file = sp.get("file");
    const center = Number(sp.get("center") ?? "0");
    const radius = Number(sp.get("radius") ?? "30");
    if (!file || Number.isNaN(center)) {
      return NextResponse.json(
        { error: "file and center required for chunk mode" },
        { status: 400 },
      );
    }
    const wavPath = sessionWavPath(session, file);
    const start = Math.max(0, center - radius);
    const duration = radius * 2;
    serverLog("audio_extract_begin", { session, mode: "chunk", file, start, duration });
    const buf = extractWavSlice(wavPath, start, duration);
    const extract_ms = Date.now() - t0;
    serverLog("audio_extract_done", {
      session,
      mode: "chunk",
      file,
      start,
      duration,
      extract_ms,
      bytes: buf.length,
    });
    return wavResponse(
      buf,
      req,
      {
        "X-Window-Start": String(start),
        "X-Window-Duration": String(duration),
      },
      { session, mode: "chunk", file, start, duration, extract_ms },
    );
  } catch (e) {
    serverLog("audio_error", { error: e instanceof Error ? e.message : String(e) });
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "extract failed" },
      { status: 500 },
    );
  }
}
