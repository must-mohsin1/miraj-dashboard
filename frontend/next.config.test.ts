import nextConfig from "./next.config";

describe("Next API proxy", () => {
  it("forwards browser API requests to the backend service", async () => {
    expect(nextConfig.rewrites).toBeDefined();

    const rewrites = await nextConfig.rewrites!();
    expect(rewrites).toContainEqual({
      source: "/api/v1/:path*",
      destination: "http://localhost:8000/api/v1/:path*",
    });
    expect(rewrites).not.toContainEqual(
      expect.objectContaining({ source: "/api/auth/:path*" })
    );
  });
});
