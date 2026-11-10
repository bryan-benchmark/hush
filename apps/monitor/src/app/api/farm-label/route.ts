import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";

export const runtime = "nodejs";

function dataRoot() {
  return process.env.OHUSH_DATA_ROOT || "C:\\OHushData";
}

function dir() {
  return path.join(dataRoot(), "indexes", "farm_labels");
}

type QueueRow = {
  clip: string;
  session: string;
  session_dir: string;
  audio_rel?: string;
  t0: number;
  t1: number;
  play_start: number;
  duration: number;
  why: string;
  priority: number;
  caption: string;
  rank: number;
  slot?: string;
  channel?: string;
};

type Draft = {
  clip: string;
  bucket?: string;
  kind?: string;
  confidence?: string;
  ask?: string;
  note?: string;
  slot?: string;
};

export type Judgment = {
  bucket: string;
  kind: string;
  note: string;
  slot: string;
  saved_at: string;
};

function readQueue(): QueueRow[] {
  const file = path.join(dir(), "queue.jsonl");
  if (!fs.existsSync(file)) return [];
  return fs
    .readFileSync(file, "utf8")
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
  fs.mkdirSync(dir(), { recursive: true });
  fs.writeFileSync(path.join(dir(), "judgments.json"), JSON.stringify(notes, null, 2) + "\n", "utf8");
}

export async function GET() {
  const items = readQueue();
  const key = readKey();
  const judgments = readJudgments();
  return NextResponse.json({
    instructions:
      "Farm coverage labels. paid_ad = standalone spot. program = the show. show_promo = network promo. program_mention = host keeps talking through a sponsor. uncertain = not enough. Agent hints optional — your save wins. Never merges into football optical gold.",
    items: items.map((item) => ({
      id: item.clip,
      session: item.session,
      session_dir: item.session_dir,
      audio_rel: item.audio_rel || "audio.wav",
      play_start: item.play_start,
      duration: item.duration,
      t0: item.t0,
      t1: item.t1,
      why: item.why,
      caption: item.caption,
      rank: item.rank,
      priority: item.priority,
      slot: item.slot || "",
      channel: item.channel || "",
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
    note?: string;
    slot?: string;
  };
  const items = readQueue();
  const item = items.find((row) => row.clip === body.id);
  if (!item) return NextResponse.json({ error: "unknown clip" }, { status: 400 });

  const bucket = String(body.bucket ?? "").trim();
  const kind = String(body.kind ?? "").trim();
  const note = String(body.note ?? "").trim().slice(0, 800);
  const slot = String(body.slot ?? item.slot ?? "").trim();

  if (!bucket || !kind) {
    return NextResponse.json({ error: "bucket and kind are required" }, { status: 400 });
  }
  if (!["paid_ad", "program", "show_promo", "program_mention", "uncertain"].includes(bucket)) {
    return NextResponse.json({ error: "bad bucket" }, { status: 400 });
  }

  const notes = readJudgments();
  notes[item.clip] = {
    bucket,
    kind,
    note,
    slot,
    saved_at: new Date().toISOString(),
  };
  writeJudgments(notes);
  return NextResponse.json({ ok: true, id: item.clip, saved: Object.keys(notes).length, total: items.length });
}
