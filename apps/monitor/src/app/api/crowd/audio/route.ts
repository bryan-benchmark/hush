import { NextRequest, NextResponse } from "next/server";
import { clipAudio, readSession, SESSION_COOKIE } from "@/lib/crowdCloud";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function ranged(buf: Buffer, range: string | null) {
  const total = buf.length;
  const headers: Record<string, string> = {
    "Content-Type": "audio/mpeg",
    "Accept-Ranges": "bytes",
    "Cache-Control": "private, max-age=300",
  };
  if (!range) {
    return new NextResponse(new Uint8Array(buf), { status: 200, headers: { ...headers, "Content-Length": String(total) } });
  }
  const match = /^bytes=(\d*)-(\d*)$/.exec(range.trim());
  if (!match) return new NextResponse(new Uint8Array(buf), { status: 200, headers: { ...headers, "Content-Length": String(total) } });
  const start = match[1] === "" ? 0 : Number(match[1]);
  const end = match[2] === "" ? total - 1 : Number(match[2]);
  if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end >= total || start > end) {
    return new NextResponse(null, { status: 416, headers: { ...headers, "Content-Range": `bytes */${total}` } });
  }
  const slice = buf.subarray(start, end + 1);
  return new NextResponse(new Uint8Array(slice), {
    status: 206,
    headers: {
      ...headers,
      "Content-Length": String(slice.length),
      "Content-Range": `bytes ${start}-${end}/${total}`,
    },
  });
}

export async function GET(req: NextRequest) {
  const session = await readSession(req.cookies.get(SESSION_COOKIE)?.value || "");
  if (!session) return NextResponse.json({ error: "name" }, { status: 401 });
  const id = req.nextUrl.searchParams.get("id") || "";
  const audio = await clipAudio(id);
  if (!audio) return NextResponse.json({ error: "unknown clip" }, { status: 404 });
  return ranged(audio, req.headers.get("range"));
}
