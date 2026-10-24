import { NextRequest, NextResponse } from "next/server";
import { PHONE_COOKIE, localHost, phoneCode, sameCode } from "@/lib/phoneAccess";
import { publicHost } from "@/lib/publicSite";

export function middleware(request: NextRequest) {
  const host = request.headers.get("host") || "";
  if (publicHost(host)) {
    const path = request.nextUrl.pathname;
    if (path.startsWith("/_next") || path === "/crowd" || path.startsWith("/api/crowd") || path === "/favicon.ico") {
      return NextResponse.next();
    }
    const dest = request.nextUrl.clone();
    dest.pathname = "/crowd";
    dest.search = "";
    return NextResponse.redirect(dest);
  }
  if (localHost(host)) return NextResponse.next();
  const path = request.nextUrl.pathname;
  if (path.startsWith("/_next") || path === "/phone/enter" || path === "/api/phone/enter") {
    return NextResponse.next();
  }
  const code = phoneCode();
  const cookie = request.cookies.get(PHONE_COOKIE)?.value || "";
  if (code && sameCode(cookie, code)) return NextResponse.next();
  const enter = request.nextUrl.clone();
  enter.pathname = "/phone/enter";
  enter.search = "";
  if (path.startsWith("/phone") || path.startsWith("/loud") || path.startsWith("/review") || path.startsWith("/breaks") || path.startsWith("/crowd")) {
    enter.searchParams.set("next", path);
  }
  return NextResponse.redirect(enter);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
