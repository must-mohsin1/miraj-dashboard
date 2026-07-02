import Link from "next/link";
import {
  Home,
  TrendingUp,
  Search,
  BarChart3,
  Briefcase,
  History,
  Settings,
  ChevronLeft,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { LogoutButton } from "@/components/logout-button";

/**
 * Sidebar navigation — Server Component.
 *
 * Renders the primary navigation for the dashboard. It is driven entirely by
 * props (no client hooks of its own); the active route + collapsed state are
 * owned by the `AppShell` client wrapper and passed down here.
 */

export interface NavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

export const navItems: NavItem[] = [
  { href: "/", label: "Home", icon: Home },
  { href: "/macro", label: "Macro Dashboard", icon: TrendingUp },
  { href: "/scanner", label: "Scanner", icon: Search },
  { href: "/analysis", label: "Analysis", icon: BarChart3 },
  { href: "/portfolio", label: "Portfolio", icon: Briefcase },
  { href: "/history", label: "History", icon: History },
  { href: "/settings", label: "Settings", icon: Settings },
];

function isActivePath(activePath: string, href: string): boolean {
  if (href === "/") return activePath === "/";
  return activePath === href || activePath.startsWith(`${href}/`);
}

export function Sidebar({
  activePath,
  email,
  collapsed,
  onToggle,
}: {
  activePath: string;
  email?: string | null;
  collapsed: boolean;
  onToggle: () => void;
}) {
  return (
    <aside
      className={cn(
        "flex h-screen shrink-0 flex-col border-r border-slate-800 bg-slate-900 transition-[width] duration-200 ease-in-out",
        collapsed ? "w-16" : "w-64"
      )}
    >
      {/* Brand + collapse toggle */}
      <div className="flex h-14 items-center justify-between gap-2 border-b border-slate-800 px-3">
        {!collapsed && (
          <span className="truncate text-sm font-semibold text-slate-100">
            Crypto Analysis
          </span>
        )}
        <button
          type="button"
          onClick={onToggle}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="inline-flex h-7 w-7 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-slate-800 hover:text-slate-100"
        >
          <ChevronLeft
            className={cn("h-4 w-4 transition-transform", collapsed && "rotate-180")}
          />
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-1 overflow-y-auto p-2" aria-label="Primary">
        {navItems.map(({ href, label, icon: Icon }) => {
          const active = isActivePath(activePath, href);
          return (
            <Link
              key={href}
              href={href}
              title={collapsed ? label : undefined}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                collapsed && "justify-center px-0",
                active
                  ? "bg-emerald-600/10 text-emerald-400"
                  : "text-slate-400 hover:bg-slate-800 hover:text-slate-100"
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {!collapsed && <span className="truncate">{label}</span>}
            </Link>
          );
        })}
      </nav>

      {/* User + logout */}
      <div className="border-t border-slate-800 p-3">
        {!collapsed && (
          <p className="mb-2 truncate text-xs text-slate-500">
            Signed in as{" "}
            <span className="text-slate-300">{email ?? "user"}</span>
          </p>
        )}
        <LogoutButton collapsed={collapsed} />
      </div>
    </aside>
  );
}

export default Sidebar;
