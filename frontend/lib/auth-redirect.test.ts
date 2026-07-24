/// <reference types="jest" />

import { resolveAuthRedirectUrl } from "@/lib/auth-redirect";

describe("resolveAuthRedirectUrl", () => {
  it("keeps relative local dev auth redirects relative to the current loopback origin", () => {
    expect(
      resolveAuthRedirectUrl({
        url: "/",
        baseUrl: "http://127.0.0.1:3023",
        nodeEnv: "development",
      })
    ).toBe("/");
  });

  it("strips a production callback origin during loopback fixture auth", () => {
    expect(
      resolveAuthRedirectUrl({
        url: "https://ta.munafaplus.pk/portfolio?exchange=mexc",
        baseUrl: "http://127.0.0.1:3023",
        nodeEnv: "development",
      })
    ).toBe("/portfolio?exchange=mexc");
  });

  it("does not trust a production baseUrl inherited by the local dev server", () => {
    expect(
      resolveAuthRedirectUrl({
        url: "/",
        baseUrl: "https://ta.munafaplus.pk",
        nodeEnv: "development",
      })
    ).toBe("/");
  });

  it("preserves the default production same-origin redirect behavior", () => {
    expect(
      resolveAuthRedirectUrl({
        url: "/portfolio?exchange=mexc",
        baseUrl: "https://ta.munafaplus.pk",
        nodeEnv: "production",
      })
    ).toBe("https://ta.munafaplus.pk/portfolio?exchange=mexc");

    expect(
      resolveAuthRedirectUrl({
        url: "https://ta.munafaplus.pk/portfolio?exchange=mexc",
        baseUrl: "https://ta.munafaplus.pk",
        nodeEnv: "production",
      })
    ).toBe("https://ta.munafaplus.pk/portfolio?exchange=mexc");
  });
});