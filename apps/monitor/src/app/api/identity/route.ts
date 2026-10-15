import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { repoRoot } from "@/lib/labeling";

export const runtime = "nodejs";

type Choice = { id: string; label: string };
type Clip = { id: string; choices: Choice[] };
type Answer = { choice: string; text?: string };

function manifestPath() {
  return path.join(repoRoot(), "experiments/identity_probes/manifest.json");
}

function answersPath() {
  return path.join(repoRoot(), "experiments/identity_probes/answers.jsonl");
}

function readManifest() {
  return JSON.parse(fs.readFileSync(manifestPath(), "utf8")) as { clips: Clip[] };
}

function latestAnswers() {
  const p = answersPath();
  if (!fs.existsSync(p)) return {} as Record<string, Answer>;
  const latest: Record<string, Answer> = {};
  for (const line of fs.readFileSync(p, "utf8").split("\n")) {
    if (!line.trim()) continue;
    const row = JSON.parse(line) as { id?: string; choice?: string; text?: string };
    if (row.id && row.choice) {
      latest[row.id] = row.text ? { choice: row.choice, text: row.text } : { choice: row.choice };
    }
  }
  return latest;
}

export async function GET() {
  const manifest = readManifest();
  return NextResponse.json({ ...manifest, answers: latestAnswers() });
}

export async function POST(req: NextRequest) {
  const body = (await req.json()) as { id?: string; choice?: string; text?: string };
  const id = body.id ?? "";
  const choice = body.choice ?? "";
  const text = (body.text ?? "").trim().slice(0, 400);
  const clip = readManifest().clips.find((row) => row.id === id);
  const known = clip?.choices.some((row) => row.id === choice) ?? false;
  if (!clip || (choice !== "said" && !known) || (choice === "said" && !text)) {
    return NextResponse.json({ error: "unknown clip or choice" }, { status: 400 });
  }
  const row = {
    id,
    choice,
    ...(choice === "said" ? { text } : {}),
    at: new Date().toISOString(),
  };
  fs.appendFileSync(answersPath(), JSON.stringify(row) + "\n", "utf8");
  return NextResponse.json({ ok: true, answers: latestAnswers() });
}
