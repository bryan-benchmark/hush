import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { repoRoot } from "@/lib/labeling";
import { normalizeRegions, type StoredRegion } from "@/lib/listenNote";

export const runtime = "nodejs";

function dir() {
  return path.join(repoRoot(), "docs/ohush/research/LABEL_AUDIT_001");
}

type Clip = { id: string; session: string; play_start: number; duration: number };

function readQueue(): Clip[] {
  const text = fs.readFileSync(path.join(dir(), "queue.jsonl"), "utf8");
  return text
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => {
      const row = JSON.parse(line) as { clip: string; session: string; t0: number; t1: number };
      const start = Math.max(0, Number(row.t0));
      const end = Number(row.t1);
      return {
        id: row.clip,
        session: row.session,
        play_start: Math.round(start * 1000) / 1000,
        duration: Math.max(0.2, Math.round((end - start) * 1000) / 1000),
      };
    });
}

function readNotes(): Record<string, { note?: string; regions?: StoredRegion[] }> {
  const file = path.join(dir(), "judgments.json");
  if (!fs.existsSync(file)) return {};
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function writeNotes(notes: Record<string, { note?: string; regions?: StoredRegion[] }>) {
  fs.writeFileSync(path.join(dir(), "judgments.json"), JSON.stringify(notes, null, 2) + "\n", "utf8");
}

export async function GET() {
  const items = readQueue();
  const notes = readNotes();
  const saved = items.flatMap((item) => {
    const prior = notes[item.id];
    if (!prior) return [];
    if (Array.isArray(prior.regions) && prior.regions.length) return [{ id: item.id, regions: prior.regions }];
    const note = String(prior.note || "").trim();
    if (!note) return [];
    return [
      {
        id: item.id,
        regions: [
          {
            start_s: 0,
            end_s: Math.round(item.duration * 100) / 100,
            what: note,
            who: "",
            tags: ["whole"],
            kind: "whole" as const,
          },
        ],
      },
    ];
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
  writeNotes(notes);
  return NextResponse.json({ ok: true, id: item.id });
}
