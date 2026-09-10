/// <reference types="jest" />

jest.mock("next/server", () => ({
  NextResponse: {
    next: () => ({ status: 200 }),
    redirect: (url: URL) => ({
      status: 307,
      headers: new Headers({ location: url.toString() }),
    }),
  },
}));

jest.mock("@/auth", () => ({
  auth: (handler?: unknown) => handler,
}));

import { config, middleware } from "@/middleware";

describe("Decision Desk middleware", () => {
  it("redirects an unauthenticated desk request to login with its local callback URL", async () => {
    const request = {
      auth: null,
      nextUrl: new URL("http://localhost:3001/desk?view=queue"),
      url: "http://localhost:3001/desk?view=queue",
    };

    const response = (await middleware(request as never, {} as never)) as unknown as Response;

    expect(response).toMatchObject({ status: 307 });
    expect(response?.headers.get("location")).toBe(
      "http://localhost:3001/login?callbackUrl=%2Fdesk%3Fview%3Dqueue"
    );
  });

  it("matches only Decision Desk routes so auth and static routes remain public", () => {
    expect(config.matcher).toEqual(["/desk/:path*"]);
  });
});
