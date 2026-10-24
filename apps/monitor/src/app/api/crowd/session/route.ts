import { NextRequest, NextResponse } from "next/server";
import { closeSession, openSession, SESSION_COOKIE } from "@/lib/crowdCloud";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => ({}))) as { idToken?: string };
  if (!body.idToken) return NextResponse.json({ error: "Sign in again." }, { status: 400 });
  try {
    const session = await openSession(body.idToken);
    const res = NextResponse.json({ ok: true, name: session.name });
    res.cookies.set(SESSION_COOKIE, session.token, {
      httpOnly: true,
      sameSite: "lax",
      secure: true,
      path: "/",
      maxAge: session.maxAge,
    });
    return res;
  } catch {
    return NextResponse.json({ error: "That sign-in did not stick. Try again." }, { status: 401 });
  }
}

export async function DELETE(req: NextRequest) {
  const token = req.cookies.get(SESSION_COOKIE)?.value || "";
  await closeSession(token);
  const res = NextResponse.json({ ok: true });
  res.cookies.set(SESSION_COOKIE, "", { httpOnly: true, sameSite: "lax", secure: true, path: "/", maxAge: 0 });
  return res;
}
