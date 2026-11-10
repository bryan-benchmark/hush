import { NextRequest, NextResponse } from "next/server";
import { FARM_COOKIE, farmCode, sameFarmCode } from "@/lib/farmAccess";

export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => ({}))) as { code?: string };
  const expected = farmCode();
  const given = String(body.code || "").trim();
  if (!expected || !sameFarmCode(given, expected)) {
    return NextResponse.json({ error: "The password does not match." }, { status: 401 });
  }
  const res = NextResponse.json({ ok: true });
  res.cookies.set(FARM_COOKIE, expected, {
    httpOnly: true,
    sameSite: "lax",
    secure: req.nextUrl.protocol === "https:",
    path: "/",
    maxAge: 60 * 60 * 24 * 60,
  });
  return res;
}
