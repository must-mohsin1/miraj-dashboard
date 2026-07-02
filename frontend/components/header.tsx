import { cn } from "@/lib/utils";

/**
 * Header — Server Component.
 *
 * A slim top bar showing the application title on the left and the current
 * page name on the right. The current page name is computed by the `AppShell`
 * wrapper (which has access to the route via `usePathname()`) and passed in as
 * a prop so this component remains a pure, server-rendered function of props.
 */

export function Header({
  pageTitle,
  className,
}: {
  pageTitle: string;
  className?: string;
}) {
  return (
    <header
      className={cn(
        "flex h-14 shrink-0 items-center justify-between border-b border-slate-800 bg-slate-900 px-6",
        className
      )}
    >
      <div className="flex items-center gap-2">
        <span className="text-base font-semibold tracking-tight text-slate-100">
          Crypto Analysis
        </span>
      </div>
      <nav className="text-sm text-slate-400" aria-label="Breadcrumb">
        <span className="font-medium text-slate-300">{pageTitle}</span>
      </nav>
    </header>
  );
}

export default Header;
