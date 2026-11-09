import { NextRequest, NextResponse } from "next/server";
import { PHONE_COOKIE, phoneCode, sameCode } from "@/lib/phoneAccess";

export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => ({}))) as { code?: string };
  const expected = phoneCode();
  const given = String(body.code || "").trim();
  if (!expected || !sameCode(given, expected)) {
    return NextResponse.json({ error: "The code does not match." }, { status: 401 });
  }
  const res = NextResponse.json({ ok: true });
  res.cookies.set(PHONE_COOKIE, expected, {
    httpOnly: true,
    sameSite: "lax",
    secure: req.nextUrl.protocol === "https:",
    path: "/",
    maxAge: 60 * 60 * 24 * 60,
  });
  return res;
}
