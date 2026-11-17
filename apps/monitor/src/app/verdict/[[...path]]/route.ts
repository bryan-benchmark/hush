import { NextRequest, NextResponse } from "next/server";
import { verdictOrigin } from "@/lib/verdictOrigin";
import { PUBLISHED_VERDICT_ORIGIN } from "@/lib/verdictOrigin.published";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 60;

const HOP = new Set([
  "host",
  "connection",
  "content-length",
  "transfer-encoding",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailers",
  "upgrade",
  // Don't forward site cookies / encoding to the lab tunnel.
  "cookie",
  "accept-encoding",
]);

function upstreamUrl(parts: string[] | undefined, search: string): string {
  const base = verdictOrigin();
  const suffix = parts?.length ? `/${parts.join("/")}` : "/";
  return `${base}${suffix}${search}`;
}

function filterReqHeaders(src: Headers): Headers {
  const out = new Headers();
  src.forEach((value, key) => {
    if (HOP.has(key.toLowerCase())) return;
    out.set(key, value);
  });
  return out;
}

function filterResHeaders(src: Headers): Headers {
  const out = new Headers();
  src.forEach((value, key) => {
    const k = key.toLowerCase();
    if (HOP.has(k) || k === "content-encoding") return;
    out.set(key, value);
  });
  out.set("Cache-Control", "no-store");
  return out;
}

function offlineHtml(detail?: string): NextResponse {
  const origin = verdictOrigin();
  const published = (PUBLISHED_VERDICT_ORIGIN || "").trim();
  const secret = (process.env.OHUSH_VERDICT_ORIGIN || "").trim();
  const body = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Verdict lab offline</title>
<style>
  body{font:16px/1.45 system-ui,sans-serif;max-width:36rem;margin:3rem auto;padding:0 1rem;color:#1a1a1a}
  code{background:#f2f2f2;padding:.1em .35em;border-radius:4px;word-break:break-all}
  pre{background:#f2f2f2;padding:12px;border-radius:8px;overflow:auto}
  .muted{color:#5a6b78;font-size:13px}
</style></head><body>
  <h1>Verdict lab is offline</h1>
  <p>ohush.co/verdict proxies the Windows lab viewer. The current origin is not reachable.</p>
  <p><code>${origin}</code></p>
  ${detail ? `<p class="muted">${detail}</p>` : ""}
  <p class="muted">Published (git): <code>${published || "—"}</code><br/>Secret env: <code>${secret || "—"}</code></p>
  <p>On the lab PC:</p>
  <pre>python -m tools.windows_lab.farm_episode_viewer --no-open
.\\scripts\\verdict.ps1
# then update apps/monitor/src/lib/verdictOrigin.published.ts + push
# or: .\\scripts\\push_verdict_origin.ps1</pre>
</body></html>`;
  return new NextResponse(body, {
    status: 502,
    headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" },
  });
}

async function proxy(req: NextRequest, parts: string[] | undefined): Promise<NextResponse> {
  const url = upstreamUrl(parts, req.nextUrl.search);
  const headers = filterReqHeaders(req.headers);
  const streaming = req.method !== "GET" && req.method !== "HEAD";

  let upstream: Response;
  try {
    upstream = await fetch(url, {
      method: req.method,
      headers,
      redirect: "manual",
      cache: "no-store",
      ...(streaming ? { body: req.body, duplex: "half" as const } : {}),
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return offlineHtml(msg);
  }

  return new NextResponse(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: filterResHeaders(upstream.headers),
  });
}

type Ctx = { params: Promise<{ path?: string[] }> };

export async function GET(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  return proxy(req, path);
}

export async function POST(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  return proxy(req, path);
}

export async function HEAD(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  return proxy(req, path);
}
