import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { repoRoot } from "@/lib/labeling";
import { judgmentFor, normalizeRegions, splitNote, type StoredRegion } from "@/lib/listenNote";

export const runtime = "nodejs";

const JUDGMENTS = new Set(["program", "departure", "commercial", "return", "uncertain"]);

function root() {
  return path.join(repoRoot(), "docs/ohush/swarm/adjudication");
}

function readQueue() {
  return JSON.parse(fs.readFileSync(path.join(root(), "queue_public.json"), "utf8")) as {
    instructions: string;
    items: { id: string; session: string; play_start: number; duration: number }[];
  };
}

type Region = StoredRegion;

function regionsFrom(row: {
  regions?: Region[];
  cuts?: { at_s?: number; start_s?: number; end_s?: number; description?: string; what?: string; who?: string }[];
  description?: string;
  note?: string;
  offset_s?: number | null;
}): Region[] {
  if (Array.isArray(row.regions)) {
    return row.regions
      .filter((region) => region && Number.isFinite(region.start_s) && Number.isFinite(region.end_s) && String(region.what || "").trim())
      .map((region) => {
        const parsed = splitNote(`${region.what || ""} ${region.who || ""}`.trim(), region.start_s, region.end_s, 20);
        return {
          start_s: region.start_s,
          end_s: region.end_s,
          what: String(region.what || "").trim(),
          who: String(region.who || "").trim(),
          tags: Array.isArray(region.tags) && region.tags.length ? region.tags : parsed.tags,
          kind: region.kind === "whole" || region.kind === "splice" ? region.kind : parsed.kind,
        };
      });
  }
  if (Array.isArray(row.cuts)) {
    return row.cuts
      .map((cut) => {
        const start = Number(cut.start_s ?? cut.at_s);
        const end = Number(cut.end_s ?? cut.at_s);
        const what = String(cut.what || cut.description || "").trim();
        const who = String(cut.who || "").trim();
        const parsed = splitNote(`${what} ${who}`.trim(), start, end, 20);
        return { start_s: start, end_s: end, what, who, tags: parsed.tags, kind: parsed.kind };
      })
      .filter((region) => region.what && Number.isFinite(region.start_s) && Number.isFinite(region.end_s));
  }
  const description = row.description || row.note || "";
  if (!description) return [];
  const at = row.offset_s == null ? 10 : 10 + row.offset_s;
  const parsed = splitNote(description, at, at, 20);
  return [{ start_s: at, end_s: at, what: description, who: "", tags: parsed.tags, kind: "splice" }];
}

function readSaved(): { id: string; regions: Region[] }[] {
  const log = path.join(root(), "judgments.jsonl");
  if (!fs.existsSync(log)) return [];
  const byId = new Map<string, { id: string; regions: Region[] }>();
  for (const line of fs.readFileSync(log, "utf8").split("\n")) {
    if (!line.trim()) continue;
    const row = JSON.parse(line) as { id?: string; regions?: Region[]; cuts?: { at_s?: number; description?: string }[]; description?: string; note?: string; offset_s?: number | null };
    if (!row.id) continue;
    byId.set(row.id, { id: row.id, regions: regionsFrom(row) });
  }
  return [...byId.values()];
}

export async function GET() {
  const queue = readQueue();
  const saved = readSaved();
  return NextResponse.json({
    instructions: queue.instructions,
    items: queue.items,
    judged: saved.map((row) => row.id),
    saved,
  });
}

export async function POST(req: NextRequest) {
  const body = (await req.json()) as {
    id?: string;
    judgment?: string;
    description?: string;
    offset_s?: number | null;
    note?: string;
    regions?: { start_s?: number; end_s?: number; what?: string; who?: string }[];
    cuts?: { at_s?: number; description?: string }[];
  };
  const queue = readQueue();
  const item = queue.items.find((row) => row.id === body.id);
  if (!item) {
    return NextResponse.json({ error: "unknown clip" }, { status: 400 });
  }
  let regions: Region[] = [];
  let tags: string[] = [];
  if (Array.isArray(body.regions)) {
    const normalized = normalizeRegions(body.regions, item.duration);
    if (!normalized.ok) return NextResponse.json({ error: normalized.error }, { status: 400 });
    regions = normalized.regions;
    tags = normalized.tags;
  } else if (Array.isArray(body.cuts)) {
    return NextResponse.json({ error: "send regions" }, { status: 400 });
  } else {
    const description = String(body.description ?? body.note ?? "").trim().slice(0, 4000);
    if (!description) {
      return NextResponse.json({ error: "description required" }, { status: 400 });
    }
    const normalized = normalizeRegions([{ start_s: 10, end_s: 10.2, what: description }], item.duration);
    if (!normalized.ok) return NextResponse.json({ error: normalized.error }, { status: 400 });
    regions = normalized.regions;
    tags = normalized.tags;
  }
  const judgment = judgmentFor(tags, JUDGMENTS) ?? (body.judgment && JUDGMENTS.has(body.judgment) ? body.judgment : "dictated");
  const description = regions.map((region) => `${region.start_s.toFixed(2)}–${region.end_s.toFixed(2)}s ${region.what}${region.who ? ` · ${region.who}` : ""}`).join(" | ");
  const boundary = regions.find((region) => region.start_s <= 10.05 && region.end_s >= 9.95) ?? regions[0];
  const row = {
    id: item.id,
    session: item.session,
    play_start: item.play_start,
    judgment,
    tags,
    regions,
    description,
    offset_s: boundary ? Math.round((boundary.start_s - 10) * 100) / 100 : null,
    note: description,
    adjudicator: "owner",
    at: new Date().toISOString(),
  };
  fs.appendFileSync(path.join(root(), "judgments.jsonl"), JSON.stringify(row) + "\n", "utf8");
  return NextResponse.json({ ok: true, id: item.id });
}
