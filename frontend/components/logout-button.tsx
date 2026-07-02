"use client";

import { LogOut } from "lucide-react";
import { signOut } from "next-auth/react";

import { cn } from "@/lib/utils";

/**
 * LogoutButton — small Client Component island.
 *
 * Rendered inside the (otherwise server-side) `Sidebar`. Uses the client-side
 * `signOut` helper from `next-auth/react` so we avoid importing the server-only
 * auth config into the client bundle.
 */
export function LogoutButton({
  collapsed = false,
  className,
}: {
  collapsed?: boolean;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={() => signOut({ callbackUrl: "/login" })}
      aria-label="Log out"
      title={collapsed ? "Logout" : undefined}
      className={cn(
        "flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm font-medium text-slate-400 transition-colors hover:bg-slate-800 hover:text-slate-100",
        collapsed && "justify-center px-0",
        className
      )}
    >
      <LogOut className="h-4 w-4 shrink-0" />
      {!collapsed && <span>Logout</span>}
    </button>
  );
}

export default LogoutButton;
