import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { readJsonl, reviewsPath } from "@/lib/labeling";
import { denial } from "@/lib/datasets";

export const runtime = "nodejs";

const VERDICTS = new Set(["ad_break", "not_break", "unsure"]);
const TAGS = new Set([
  "silence_false",
  "music_swell",
  "station_id",
  "in_early",
  "in_late",
  "out_early",
  "out_late",
  "missed_break",
  "other",
]);

export async function GET(req: NextRequest) {
  const runId = req.nextUrl.searchParams.get("run_id");
  const rows = readJsonl(reviewsPath()).filter((row) => !runId || row.run_id === runId);
  return NextResponse.json({ reviews: rows });
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const required = ["run_id", "proposal_id", "verdict"];
  for (const key of required) {
    if (body[key] === undefined || body[key] === null || body[key] === "") {
      return NextResponse.json({ error: `missing ${key}` }, { status: 400 });
    }
  }
  const verdict = String(body.verdict);
  if (!VERDICTS.has(verdict)) {
    return NextResponse.json({ error: "bad verdict" }, { status: 400 });
  }
  if (body.session) {
    const blocked = denial(String(body.session), req.nextUrl.searchParams.get("unseal"));
    if (blocked) return NextResponse.json(blocked, { status: 403 });
  }
  const errorTag = body.error_tag ? String(body.error_tag) : null;
  if (errorTag && !TAGS.has(errorTag)) {
    return NextResponse.json({ error: "bad error_tag" }, { status: 400 });
  }
  const num = (value: unknown) =>
    value === null || value === undefined || value === "" ? null : Number(value);
  const row = {
    review_id: `review_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`,
    run_id: String(body.run_id),
    proposal_id: String(body.proposal_id),
    params_hash: body.params_hash ? String(body.params_hash) : null,
    session: body.session ? String(body.session) : null,
    verdict,
    suggested_in_seconds: num(body.suggested_in_seconds),
    suggested_out_seconds: num(body.suggested_out_seconds),
    human_in_seconds: num(body.human_in_seconds),
    human_out_seconds: num(body.human_out_seconds),
    in_drag_delta_seconds: num(body.in_drag_delta_seconds),
    out_drag_delta_seconds: num(body.out_drag_delta_seconds),
    error_tag: errorTag,
    note: body.note ? String(body.note) : null,
    reviewer: body.reviewer ? String(body.reviewer) : null,
    created_at: new Date().toISOString(),
    supersedes: body.supersedes ? String(body.supersedes) : null,
  };
  const p = reviewsPath();
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.appendFileSync(p, JSON.stringify(row) + "\n", "utf8");
  return NextResponse.json({ ok: true, review: row });
}
