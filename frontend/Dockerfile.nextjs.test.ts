import { readFile } from "node:fs/promises";
import path from "node:path";

describe("Next Docker build", () => {
  it("sets the internal API origin before compiling rewrites", async () => {
    const dockerfile = await readFile(
      path.join(process.cwd(), "Dockerfile.nextjs"),
      "utf8"
    );

    expect(dockerfile).toContain("ENV API_URL=http://web:8000");
    expect(dockerfile).toContain("ENV NEXT_PUBLIC_API_URL=");
  });
});
