import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { repoRoot } from "@/lib/labeling";

export const runtime = "nodejs";

function rosterRoot() {
  return path.join(repoRoot(), "docs/ohush/research/VOICE_ROSTER_001");
}

function readQueue() {
  return JSON.parse(fs.readFileSync(path.join(rosterRoot(), "queue_public.json"), "utf8")) as {
    instructions: string;
    missing_sessions: string[];
    items: {
      id: string;
      session: string;
      play_start: number;
      duration: number;
      rank: number;
      heard_seconds: number;
      session_label: string;
      n_in_session: number;
    }[];
  };
}

type Person = { start_s: number; end_s: number; who: string; what: string };

function readNames(): { id: string; who: string; what: string; people: Person[]; session: string; play_start: number | null }[] {
  const log = path.join(rosterRoot(), "names.jsonl");
  if (!fs.existsSync(log)) return [];
  const byId = new Map<string, { id: string; who: string; what: string; people: Person[]; session: string; play_start: number | null }>();
  for (const line of fs.readFileSync(log, "utf8").split("\n")) {
    if (!line.trim()) continue;
    const row = JSON.parse(line) as { id?: string; who?: string; what?: string; people?: Person[]; session?: string; play_start?: number };
    if (!row.id) continue;
    const people = Array.isArray(row.people)
      ? row.people
          .filter((person) => person && (person.who || person.what) && Number.isFinite(person.start_s) && Number.isFinite(person.end_s))
          .map((person) => ({ start_s: person.start_s, end_s: person.end_s, who: person.who || "", what: person.what || "" }))
      : [];
    byId.set(row.id, {
      id: row.id,
      who: row.who || "",
      what: row.what || "",
      people,
      session: row.session || "",
      play_start: Number.isFinite(row.play_start) ? Number(row.play_start) : null,
    });
  }
  return [...byId.values()];
}

export async function GET() {
  const queue = readQueue();
  return NextResponse.json({
    instructions: queue.instructions,
    missing_sessions: queue.missing_sessions,
    items: queue.items,
    named: readNames(),
  });
}

export async function POST(req: NextRequest) {
  const body = (await req.json()) as {
    id?: string;
    who?: string;
    what?: string;
    people?: { start_s?: number; end_s?: number; who?: string; what?: string }[];
  };
  const queue = readQueue();
  const item = queue.items.find((row) => row.id === body.id);
  if (!item) {
    return NextResponse.json({ error: "unknown voice" }, { status: 400 });
  }
  const what = String(body.what ?? "").trim().slice(0, 200);
  const people: Person[] = [];
  if (Array.isArray(body.people)) {
    for (const person of body.people) {
      const start = Number(person.start_s);
      const end = Number(person.end_s);
      const name = String(person.who ?? "").trim().slice(0, 200);
      const desc = String(person.what ?? "").trim().slice(0, 200);
      if ((!name && !desc) || !Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end > item.duration + 0.05 || end - start < 0.15) {
        return NextResponse.json({ error: "each box needs a span and a description" }, { status: 400 });
      }
      people.push({ start_s: Math.round(start * 100) / 100, end_s: Math.round(end * 100) / 100, who: name, what: desc });
    }
    people.sort((a, b) => a.start_s - b.start_s);
  }
  const who = people.length
    ? people.map((person) => person.who).filter(Boolean).join(" · ")
    : Array.isArray(body.people)
      ? ""
      : what === "Not a broadcaster"
        ? "not a broadcaster"
        : String(body.who ?? "").trim().slice(0, 200);
  const described = people.length ? people.map((person) => person.what || person.who).join(" · ") : what;
  if (!who && !described && !Array.isArray(body.people)) {
    return NextResponse.json({ error: "a name is required" }, { status: 400 });
  }
  const key = JSON.parse(fs.readFileSync(path.join(rosterRoot(), "queue_key.json"), "utf8")) as {
    id: string;
    session: string;
    cluster_id: string;
    heard_seconds: number;
    play_start: number;
  }[];
  const secret = key.find((row) => row.id === item.id);
  const row = {
    id: item.id,
    session: item.session,
    who,
    what: described || what,
    people,
    play_start: item.play_start,
    duration: item.duration,
    heard_seconds: item.heard_seconds,
    cluster_id: secret?.cluster_id ?? null,
    role: people.some((person) => person.who) || (what === "Broadcaster" && Boolean(who)) ? "broadcaster" : "not_broadcaster",
    note: "Times are seconds into this clip. The words are what you typed.",
    adjudicator: "owner",
    at: new Date().toISOString(),
  };
  fs.appendFileSync(path.join(rosterRoot(), "names.jsonl"), JSON.stringify(row) + "\n", "utf8");
  const namedPeople = people.filter((person) => person.who);
  const enroll = namedPeople.length ? namedPeople : !people.length && who && row.role === "broadcaster" ? [{ start_s: 0, end_s: item.duration, who, what }] : [];
  if (enroll.length) {
    const ledger = path.join(repoRoot(), "docs/ohush/research/UNIVERSAL_V4_SPEAKER_ENROLLMENT_001/verified.jsonl");
    for (const person of enroll) {
      fs.appendFileSync(
        ledger,
        JSON.stringify({
          ...row,
          who: person.who,
          clip_start_s: person.start_s,
          clip_end_s: person.end_s,
          absolute_start_s: Math.round((item.play_start + person.start_s) * 100) / 100,
          absolute_end_s: Math.round((item.play_start + person.end_s) * 100) / 100,
        }) + "\n",
        "utf8",
      );
    }
  }
  return NextResponse.json({ ok: true, id: item.id });
}
