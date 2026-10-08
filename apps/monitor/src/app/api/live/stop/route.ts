import { NextResponse } from "next/server";
import { liveFetch } from "@/lib/liveEngine";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST() {
  const { res, json } = await liveFetch("/stop", {
    method: "POST",
    body: "{}",
  });
  return NextResponse.json(json, { status: res.status });
}
