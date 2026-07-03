"use client";

import { OrderTicket } from "@/components/trading/order-ticket";
import { PositionManager } from "@/components/trading/position-manager";
import { OpenOrdersTable } from "@/components/trading/open-orders-table";

/**
 * TradingDashboard — client wrapper that lays out the three trading widgets.
 *
 * Renders OrderTicket + PositionManager side-by-side on desktop, with the
 * OpenOrdersTable full-width below.
 */

interface TradingDashboardProps {
  token: string | null;
  exchange: string;
  tradingEnabled: boolean;
}

export function TradingDashboard({
  token,
  exchange,
  tradingEnabled,
}: TradingDashboardProps) {
  return (
    <div className="flex flex-col gap-6">
      {/* Top row: order ticket + position manager */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <OrderTicket
          exchange={exchange}
          token={token}
          tradingEnabled={tradingEnabled}
        />
        <PositionManager
          exchange={exchange}
          token={token}
          tradingEnabled={tradingEnabled}
        />
      </div>

      {/* Bottom row: open orders table */}
      <OpenOrdersTable
        exchange={exchange}
        token={token}
        tradingEnabled={tradingEnabled}
      />
    </div>
  );
}

export default TradingDashboard;
