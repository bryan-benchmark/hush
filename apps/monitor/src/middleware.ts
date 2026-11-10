import { NextRequest, NextResponse } from "next/server";
import { PHONE_COOKIE, localHost, phoneCode, sameCode } from "@/lib/phoneAccess";
import { FARM_COOKIE, farmCode, sameFarmCode } from "@/lib/farmAccess";
import { isPublicSite } from "@/lib/publicSite";

export function middleware(request: NextRequest) {
  const host = request.headers.get("host") || "";
  const forwarded = request.headers.get("x-forwarded-host") || "";
  const path = request.nextUrl.pathname;

  if (isPublicSite(host, forwarded)) {
    if (
      path.startsWith("/_next") ||
      path === "/favicon.ico" ||
      path === "/crowd" ||
      path.startsWith("/api/crowd")
    ) {
      return NextResponse.next();
    }

    // Solo /farm on ohush.co — password gate (OHUSH_FARM_CODE or OHUSH_PHONE_CODE).
    const farmPath =
      path === "/farm" ||
      path.startsWith("/farm/") ||
      path.startsWith("/api/farm");
    if (farmPath) {
      if (path === "/farm/enter" || path === "/api/farm/enter") {
        return NextResponse.next();
      }
      const code = farmCode();
      const cookie = request.cookies.get(FARM_COOKIE)?.value || "";
      if (code && sameFarmCode(cookie, code)) return NextResponse.next();
      const enter = request.nextUrl.clone();
      enter.pathname = "/farm/enter";
      enter.search = "";
      enter.searchParams.set("next", path.startsWith("/api/farm") ? "/farm" : path);
      return NextResponse.redirect(enter);
    }

    const dest = request.nextUrl.clone();
    dest.pathname = "/crowd";
    dest.search = "";
    return NextResponse.redirect(dest);
  }

  if (localHost(host)) return NextResponse.next();

  if (path.startsWith("/_next") || path === "/phone/enter" || path === "/api/phone/enter") {
    return NextResponse.next();
  }
  const code = phoneCode();
  const cookie = request.cookies.get(PHONE_COOKIE)?.value || "";
  if (code && sameCode(cookie, code)) return NextResponse.next();
  const enter = request.nextUrl.clone();
  enter.pathname = "/phone/enter";
  enter.search = "";
  if (
    path.startsWith("/phone") ||
    path.startsWith("/loud") ||
    path.startsWith("/review") ||
    path.startsWith("/breaks") ||
    path.startsWith("/crowd") ||
    path.startsWith("/farm") ||
    path.startsWith("/api/farm")
  ) {
    enter.searchParams.set("next", path.startsWith("/api/farm") ? "/farm" : path);
  }
  return NextResponse.redirect(enter);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
