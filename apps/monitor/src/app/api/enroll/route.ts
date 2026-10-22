import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { repoRoot } from "@/lib/labeling";

export const runtime = "nodejs";

const CONDITIONS = ["clear", "laugh", "loud", "crowd", "song", "not_them", "news", "other_show", "skip"] as const;

function dir() {
  return path.join(repoRoot(), "docs/ohush/research/VOICE_ENROLL_001");
}

function readQueue() {
  return JSON.parse(fs.readFileSync(path.join(dir(), "queue.json"), "utf8")) as {
    items: { id: string; session: string; play_start: number; duration: number }[];
  };
}

function readLabels() {
  const log = path.join(dir(), "labels.jsonl");
  if (!fs.existsSync(log)) return [];
  const byId = new Map<string, Record<string, unknown>>();
  for (const line of fs.readFileSync(log, "utf8").split("\n")) {
    if (!line.trim()) continue;
    const row = JSON.parse(line) as { id?: string };
    if (row.id) byId.set(row.id, row);
  }
  return [...byId.values()];
}

export async function GET() {
  const queue = readQueue();
  return NextResponse.json({ ...queue, labels: readLabels() });
}

export async function POST(req: NextRequest) {
  const body = (await req.json()) as { id?: string; who?: string; condition?: string };
  const condition = String(body.condition ?? "");
  if (!CONDITIONS.includes(condition as (typeof CONDITIONS)[number])) {
    return NextResponse.json({ error: "unknown condition" }, { status: 400 });
  }
  const item = readQueue().items.find((row) => row.id === body.id);
  if (!item) return NextResponse.json({ error: "unknown clip" }, { status: 400 });
  const who = String(body.who ?? "").trim().slice(0, 80);
  const named = condition === "news" || condition === "other_show" || condition === "skip" ? "" : who;
  if (!named && condition !== "not_them" && condition !== "news" && condition !== "other_show" && condition !== "skip") {
    return NextResponse.json({ error: "a name is required" }, { status: 400 });
  }
  const row = {
    id: item.id,
    session: item.session,
    play_start: item.play_start,
    duration: item.duration,
    who: named,
    condition,
    adjudicator: "owner",
    at: new Date().toISOString(),
  };
  fs.mkdirSync(dir(), { recursive: true });
  fs.appendFileSync(path.join(dir(), "labels.jsonl"), JSON.stringify(row) + "\n", "utf8");
  return NextResponse.json({ ok: true, id: item.id });
}
