import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { repoRoot } from "@/lib/labeling";

export const runtime = "nodejs";

export async function GET(req: NextRequest) {
  const runId = req.nextUrl.searchParams.get("run_id");
  if (!runId || runId.includes("/") || runId.includes("..")) {
    return NextResponse.json({ error: "run_id required" }, { status: 400 });
  }
  const p = path.join(repoRoot(), "experiments/queues", `${runId}_debug.json`);
  if (!fs.existsSync(p)) {
    return NextResponse.json({ items: [], missing: true });
  }
  const queue = JSON.parse(fs.readFileSync(p, "utf8")) as {
    purpose?: string;
    items?: Array<Record<string, unknown>>;
  };
  return NextResponse.json({
    purpose: queue.purpose ?? "debug_queue_not_evaluation_set",
    items: queue.items ?? [],
  });
}
