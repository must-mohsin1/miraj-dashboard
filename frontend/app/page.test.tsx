import { render, screen } from "@testing-library/react";
import Home from "./page";

describe("Home page", () => {
  it("renders the dashboard title and description", () => {
    render(<Home />);
    expect(screen.getByText(/Miraj Dashboard/i)).toBeInTheDocument();
    expect(screen.getByText(/Next.js frontend scaffold is ready./i)).toBeInTheDocument();
  });

  it("has an accessible sample input", () => {
    render(<Home />);
    expect(screen.getByLabelText(/Sample input/i)).toBeInTheDocument();
  });

  it("renders the dialog trigger button", () => {
    render(<Home />);
    expect(screen.getByRole("button", { name: /Open dialog/i })).toBeInTheDocument();
  });

  it("renders the tabs and table headers", () => {
    render(<Home />);
    expect(screen.getByRole("tab", { name: /Table/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Empty/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /Asset/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /Price/i })).toBeInTheDocument();
  });
});
