jest.mock("@/components/logout-button", () => ({ LogoutButton: () => null }));

import { navItems } from "./sidebar";

describe("primary navigation", () => {
  it("links Decision Desk to the protected collector workspace", () => {
    expect(navItems.find((item) => item.label === "Decision Desk")?.href).toBe("/desk");
  });
});
