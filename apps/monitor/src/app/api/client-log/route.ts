import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { repoRoot } from "@/lib/labeling";

export const runtime = "nodejs";

function logPath() {
  return path.join(repoRoot(), "experiments/reports/labeler_audio_debug.jsonl");
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const row = {
      side: "client",
      at: new Date().toISOString(),
      ...body,
    };
    const p = logPath();
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.appendFileSync(p, JSON.stringify(row) + "\n", "utf8");
    return NextResponse.json({ ok: true });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "log failed" },
      { status: 500 },
    );
  }
}
