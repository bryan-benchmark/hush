import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { repoRoot } from "@/lib/labeling";

export const runtime = "nodejs";

function dir() {
  return path.join(repoRoot(), "docs/ohush/research/BROADCAST_DEEP_LABEL_001");
}

type QueueRow = {
  clip: string;
  session: string;
  t0: number;
  t1: number;
  play_start: number;
  duration: number;
  why: string;
  priority: number;
  caption: string;
  rank: number;
};

type Draft = {
  clip: string;
  kind?: string;
  phase?: string;
  setting?: string;
  speaker?: string;
  bucket?: string;
  note?: string;
  confidence?: string;
  ask?: string;
};

export type Judgment = {
  bucket: string;
  kind: string;
  phase: string;
  setting: string;
  speaker: string;
  note: string;
  saved_at: string;
};

function readQueue(): QueueRow[] {
  const text = fs.readFileSync(path.join(dir(), "queue.jsonl"), "utf8");
  return text
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => JSON.parse(line) as QueueRow);
}

function readKey(): Record<string, Draft> {
  const file = path.join(dir(), "key.jsonl");
  if (!fs.existsSync(file)) return {};
  const out: Record<string, Draft> = {};
  for (const line of fs.readFileSync(file, "utf8").split("\n")) {
    if (!line.trim()) continue;
    const row = JSON.parse(line) as Draft;
    if (row.clip) out[row.clip] = row;
  }
  return out;
}

function readJudgments(): Record<string, Judgment> {
  const file = path.join(dir(), "judgments.json");
  if (!fs.existsSync(file)) return {};
  return JSON.parse(fs.readFileSync(file, "utf8")) as Record<string, Judgment>;
}

function writeJudgments(notes: Record<string, Judgment>) {
  fs.writeFileSync(path.join(dir(), "judgments.json"), JSON.stringify(notes, null, 2) + "\n", "utf8");
}

export async function GET() {
  const items = readQueue();
  const key = readKey();
  const judgments = readJudgments();
  return NextResponse.json({
    instructions:
      "Label phase + speaker on desk clips. Dry VO anchors are contrast only. Agent hints are optional — your save wins.",
    items: items.map((item) => ({
      id: item.clip,
      session: item.session,
      play_start: item.play_start,
      duration: item.duration,
      t0: item.t0,
      t1: item.t1,
      why: item.why,
      caption: item.caption,
      rank: item.rank,
      priority: item.priority,
      draft: key[item.clip] ?? null,
      saved: judgments[item.clip] ?? null,
    })),
    saved: Object.keys(judgments).length,
    total: items.length,
  });
}

export async function POST(req: NextRequest) {
  const body = (await req.json()) as {
    id?: string;
    bucket?: string;
    kind?: string;
    phase?: string;
    setting?: string;
    speaker?: string;
    note?: string;
  };
  const items = readQueue();
  const item = items.find((row) => row.clip === body.id);
  if (!item) return NextResponse.json({ error: "unknown clip" }, { status: 400 });

  const bucket = String(body.bucket ?? "").trim();
  const kind = String(body.kind ?? "").trim();
  const phase = String(body.phase ?? "").trim();
  const setting = String(body.setting ?? "").trim();
  const speaker = String(body.speaker ?? "").trim().slice(0, 200);
  const note = String(body.note ?? "").trim().slice(0, 800);

  if (!bucket || !kind) {
    return NextResponse.json({ error: "bucket and kind are required" }, { status: 400 });
  }
  if (!["broadcast", "non_broadcast", "unsure"].includes(bucket)) {
    return NextResponse.json({ error: "bad bucket" }, { status: 400 });
  }

  const notes = readJudgments();
  notes[item.clip] = {
    bucket,
    kind,
    phase,
    setting,
    speaker,
    note,
    saved_at: new Date().toISOString(),
  };
  writeJudgments(notes);
  return NextResponse.json({ ok: true, id: item.clip, saved: Object.keys(notes).length, total: items.length });
}
