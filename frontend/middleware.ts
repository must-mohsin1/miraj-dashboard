import { NextResponse } from "next/server";

import { auth } from "@/auth";

export const middleware = auth((request) => {
  if (request.auth) {
    return NextResponse.next();
  }

  const callbackUrl = `${request.nextUrl.pathname}${request.nextUrl.search}`;
  const loginUrl = new URL("/login", request.nextUrl.origin);
  loginUrl.searchParams.set("callbackUrl", callbackUrl);

  return NextResponse.redirect(loginUrl);
});

export const config = {
  matcher: ["/desk/:path*"],
};
