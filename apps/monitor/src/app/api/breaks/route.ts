import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { repoRoot } from "@/lib/labeling";
import { normalizeRegions, type StoredRegion } from "@/lib/listenNote";

export const runtime = "nodejs";

function dir() {
  return path.join(repoRoot(), "docs/ohush/research/BREAK_LISTEN_001");
}

type Clip = {
  id: string;
  session: string;
  play_start: number;
  duration: number;
  mark_s: number;
  caption: string;
};

function readQueue(): Clip[] {
  const text = fs.readFileSync(path.join(dir(), "queue.jsonl"), "utf8");
  return text
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => JSON.parse(line) as Clip);
}

function readNotes(): Record<string, { note?: string; regions?: StoredRegion[] }> {
  const file = path.join(dir(), "judgments.json");
  if (!fs.existsSync(file)) return {};
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

export async function GET() {
  const items = readQueue();
  const notes = readNotes();
  const saved = items.flatMap((item) => {
    const prior = notes[item.id];
    if (!prior?.regions?.length) return [];
    return [{ id: item.id, regions: prior.regions }];
  });
  return NextResponse.json({ items, saved });
}

export async function POST(req: NextRequest) {
  const body = (await req.json()) as { id?: string; regions?: { start_s?: number; end_s?: number; what?: string; who?: string }[] };
  const items = readQueue();
  const item = items.find((row) => row.id === body.id);
  if (!item) return NextResponse.json({ error: "unknown clip" }, { status: 400 });
  const normalized = normalizeRegions(body.regions ?? [], item.duration);
  if (!normalized.ok) return NextResponse.json({ error: normalized.error }, { status: 400 });
  const notes = readNotes();
  notes[item.id] = {
    note: normalized.regions.map((region) => region.what).join("\n"),
    regions: normalized.regions,
  };
  fs.mkdirSync(dir(), { recursive: true });
  fs.writeFileSync(path.join(dir(), "judgments.json"), JSON.stringify(notes, null, 2) + "\n", "utf8");
  return NextResponse.json({ ok: true, id: item.id });
}
