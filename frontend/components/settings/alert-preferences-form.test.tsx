import { render, screen } from "@testing-library/react";

import { AlertPreferencesForm } from "./alert-preferences-form";

describe("AlertPreferencesForm notification capabilities", () => {
  it("states that only Telegram can be configured in the dashboard and shows delivery state", () => {
    render(
      <AlertPreferencesForm
        token={null}
        channels={[
          {
            id: 1,
            user_id: 1,
            channel_type: "telegram",
            config: { chat_id: "-1001234567890" },
            enabled: true,
            created_at: "2026-07-17T00:00:00Z",
            updated_at: "2026-07-17T00:00:00Z",
          },
        ]}
        pairSettings={[]}
        fetchError={false}
      />
    );

    expect(
      screen.getByText(
        "Telegram can be configured in this dashboard today. Discord signal delivery has been removed because it produced stale, unusable alerts. Email delivery is coming soon and cannot be configured here."
      )
    ).toBeInTheDocument();
    expect(screen.getByText("Configured — enabled")).toBeInTheDocument();
    expect(screen.getByText("Not configured")).toBeInTheDocument();
    expect(screen.queryByText(/^Discord$/)).not.toBeInTheDocument();
  });

  it("labels leftover Discord channels as retired so they can be deleted", () => {
    render(
      <AlertPreferencesForm
        token={null}
        channels={[
          {
            id: 2,
            user_id: 1,
            channel_type: "discord",
            config: { webhook_url: "https://discord.com/api/webhooks/xxx" },
            enabled: true,
            created_at: "2026-07-17T00:00:00Z",
            updated_at: "2026-07-17T00:00:00Z",
          },
        ]}
        pairSettings={[]}
        fetchError={false}
      />
    );

    expect(screen.getByText("discord")).toBeInTheDocument();
    expect(
      screen.getByText("Retired — Discord signals are no longer delivered")
    ).toBeInTheDocument();
  });
});
