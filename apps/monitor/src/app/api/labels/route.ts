import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { labelsPath } from "@/lib/labeling";

export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  const body = await req.json();
  const required = ["session", "file", "candidate_elapsed_seconds", "verdict"];
  for (const k of required) {
    if (body[k] === undefined || body[k] === null || body[k] === "") {
      return NextResponse.json({ error: `missing ${k}` }, { status: 400 });
    }
  }

  const verdict = String(body.verdict);
  if (!["ad_break", "not_break", "unsure"].includes(verdict)) {
    return NextResponse.json({ error: "bad verdict" }, { status: 400 });
  }

  const row = {
    session: String(body.session),
    file: String(body.file),
    candidate_elapsed_seconds: Number(body.candidate_elapsed_seconds),
    session_elapsed_seconds: Number(
      body.session_elapsed_seconds ?? body.candidate_elapsed_seconds,
    ),
    verdict,
    ad_start_seconds:
      body.ad_start_seconds === null || body.ad_start_seconds === undefined
        ? null
        : Number(body.ad_start_seconds),
    ad_end_seconds:
      body.ad_end_seconds === null || body.ad_end_seconds === undefined
        ? null
        : Number(body.ad_end_seconds),
    ad_start_session_seconds:
      body.ad_start_session_seconds === null ||
      body.ad_start_session_seconds === undefined
        ? null
        : Number(body.ad_start_session_seconds),
    ad_end_session_seconds:
      body.ad_end_session_seconds === null ||
      body.ad_end_session_seconds === undefined
        ? null
        : Number(body.ad_end_session_seconds),
    ad_start_wall_time: body.ad_start_wall_time ?? null,
    ad_end_wall_time: body.ad_end_wall_time ?? null,
    note: body.note ? String(body.note) : null,
    labeled_at: new Date().toISOString(),
  };

  if (verdict === "ad_break") {
    if (row.ad_start_seconds === null || row.ad_end_seconds === null) {
      return NextResponse.json(
        { error: "ad_break needs ad_start_seconds and ad_end_seconds" },
        { status: 400 },
      );
    }
    if (row.ad_end_seconds <= row.ad_start_seconds) {
      return NextResponse.json({ error: "end must be after start" }, { status: 400 });
    }
  }

  const p = labelsPath();
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.appendFileSync(p, JSON.stringify(row) + "\n", "utf8");
  return NextResponse.json({ ok: true, label: row });
}

export async function GET() {
  const p = labelsPath();
  if (!fs.existsSync(p)) {
    return NextResponse.json({ labels: [] });
  }
  const labels = fs
    .readFileSync(p, "utf8")
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line));
  return NextResponse.json({ labels });
}
