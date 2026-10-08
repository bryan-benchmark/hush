import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { readJsonl, truthPath } from "@/lib/labeling";
import { denial, labelVisible } from "@/lib/datasets";

export const runtime = "nodejs";

const EVENT_CLASSES = new Set(["commercial", "network_promo", "sponsorship", "other"]);
const ACTIONS = new Set(["mute", "play", "unsure"]);
const CONFIDENCE = new Set(["certain", "unsure"]);

export async function GET(req: NextRequest) {
  const session = req.nextUrl.searchParams.get("session");
  const unseal = req.nextUrl.searchParams.get("unseal");
  const rows = readJsonl(truthPath()).filter((row) => {
    if (session && row.session !== session) return false;
    return labelVisible(String(row.session), unseal, false);
  });
  return NextResponse.json({ truth_events: resolveTruth(rows) });
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  if (!body.retract) {
    const required = ["session", "start_seconds", "end_seconds"];
    for (const key of required) {
      if (body[key] === undefined || body[key] === null || body[key] === "") {
        return NextResponse.json({ error: `missing ${key}` }, { status: 400 });
      }
    }
  } else if (!body.session) {
    return NextResponse.json({ error: "missing session" }, { status: 400 });
  }
  const blocked = denial(String(body.session), req.nextUrl.searchParams.get("unseal"));
  if (blocked) {
    return NextResponse.json(blocked, { status: 403 });
  }
  if (body.run_id || body.proposal_id) {
    return NextResponse.json(
      { error: "truth cannot cite a detector run or proposal" },
      { status: 400 },
    );
  }
  if (body.retract) {
    const supersedes = body.supersedes ? String(body.supersedes) : "";
    if (!supersedes) {
      return NextResponse.json({ error: "retract requires supersedes" }, { status: 400 });
    }
    const row = {
      gold_id: `gold_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`,
      session: String(body.session),
      supersedes,
      retracted: true,
      event: "retracted",
      note: body.note ? String(body.note) : "retracted",
      reviewer: body.reviewer ? String(body.reviewer) : null,
      created_at: new Date().toISOString(),
    };
    const p = truthPath();
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.appendFileSync(p, JSON.stringify(row) + "\n", "utf8");
    return NextResponse.json({ ok: true, truth_event: row });
  }
  const start = Number(body.start_seconds);
  const end = Number(body.end_seconds);
  if (!(end > start)) {
    return NextResponse.json({ error: "end must be after start" }, { status: 400 });
  }
  const eventClass = String(body.event_class ?? "commercial");
  const action = String(body.desired_action ?? "mute");
  const confidence = String(body.confidence ?? "certain");
  if (!EVENT_CLASSES.has(eventClass) || !ACTIONS.has(action) || !CONFIDENCE.has(confidence)) {
    return NextResponse.json({ error: "bad event_class, desired_action, or confidence" }, { status: 400 });
  }
  const rate = Number(body.sample_rate_hz ?? 48000);
  const countsAsBreak = eventClass === "commercial" && action === "mute" && confidence === "certain";
  const row = {
    gold_id: `gold_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`,
    session: String(body.session),
    start_seconds: start,
    end_seconds: end,
    start_sample: Math.round(start * rate),
    end_sample: Math.round(end * rate),
    event: countsAsBreak ? "ad_break" : eventClass,
    event_class: eventClass,
    desired_action: action,
    confidence,
    reviewer: body.reviewer ? String(body.reviewer) : null,
    note: body.note ? String(body.note) : null,
    created_at: new Date().toISOString(),
    supersedes: body.supersedes ? String(body.supersedes) : null,
  };
  const p = truthPath();
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.appendFileSync(p, JSON.stringify(row) + "\n", "utf8");
  return NextResponse.json({ ok: true, truth_event: row });
}

function resolveTruth(rows: Array<Record<string, unknown>>) {
  const superseded = new Set(rows.map((row) => row.supersedes).filter((id) => typeof id === "string" && id));
  const latest = new Map<string, Record<string, unknown>>();
  for (const row of rows) latest.set(String(row.gold_id), row);
  return [...latest.values()].filter(
    (row) => !superseded.has(row.gold_id) && row.retracted !== true && row.event !== "retracted",
  );
}
