import { render, screen } from "@testing-library/react";

import { ConnectForm } from "@/components/portfolio/connect-form";

const refresh = jest.fn();

jest.mock("next/navigation", () => ({
  useRouter: () => ({ refresh }),
}));

jest.mock("@/hooks/use-mutation", () => ({
  useMutation: () => ({
    trigger: jest.fn(),
    isMutating: false,
    error: null,
  }),
}));

describe("ConnectForm", () => {
  it("shows read-only MEXC permission and local fixture guidance without credentials", () => {
    render(<ConnectForm token="token" exchange="mexc" />);

    expect(screen.getByText("Use read-only MEXC permissions only.")).toBeInTheDocument();
    expect(
      screen.getByText("Miraj uses mocked/redacted fixtures for Phase 2A local verification.")
    ).toBeInTheDocument();
    expect(screen.queryByText(/api_key/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/api_secret/i)).not.toBeInTheDocument();
  });
});
