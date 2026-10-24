import { NextRequest, NextResponse } from "next/server";
import { castVote, crowdState, type Action } from "@/lib/crowd";
import { cloudState, cloudVote, readSession, SESSION_COOKIE } from "@/lib/crowdCloud";
import { publicHost } from "@/lib/publicSite";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const NAME = "ohush_crowd";

function cloud(req: NextRequest) {
  return publicHost(req.headers.get("host") || "") || process.env.OHUSH_PUBLIC_SITE === "1";
}

async function account(req: NextRequest) {
  return readSession(req.cookies.get(SESSION_COOKIE)?.value || "");
}

export async function GET(req: NextRequest) {
  if (cloud(req)) {
    const session = await account(req);
    if (!session) return NextResponse.json({ error: "name" }, { status: 401 });
    return NextResponse.json(await cloudState(session.uid, session.name));
  }
  const name = (req.cookies.get(NAME)?.value || "").trim();
  if (!name) return NextResponse.json({ error: "name" }, { status: 401 });
  return NextResponse.json(crowdState(name));
}

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => ({}))) as { id?: string; action?: string; note?: string };
  const action = body.action === "on" || body.action === "off" ? (body.action as Action) : null;
  if (!body.id || !action) return NextResponse.json({ error: "Say whether you would leave it on." }, { status: 400 });
  if (cloud(req)) {
    const session = await account(req);
    if (!session) return NextResponse.json({ error: "name" }, { status: 401 });
    const result = await cloudVote(session.uid, session.name, body.id, action, String(body.note || ""));
    if ("error" in result) return NextResponse.json(result, { status: 400 });
    return NextResponse.json(result);
  }
  const name = (req.cookies.get(NAME)?.value || "").trim();
  if (!name) return NextResponse.json({ error: "name" }, { status: 401 });
  const result = castVote(name, body.id, action, String(body.note || ""));
  if ("error" in result) return NextResponse.json(result, { status: 400 });
  return NextResponse.json(result);
}
