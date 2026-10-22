import { NextRequest, NextResponse } from "next/server";
import { liveFetch } from "@/lib/liveEngine";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  const { res, json } = await liveFetch("/tnf", {
    method: "POST",
    body: JSON.stringify(body),
  });
  return NextResponse.json(json, { status: res.status });
}
