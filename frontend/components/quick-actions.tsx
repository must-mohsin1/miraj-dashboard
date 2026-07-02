import Link from "next/link";
import { Search, TrendingUp } from "lucide-react";

import { Button } from "@/components/ui/button";

/**
 * QuickActions — presentational component.
 *
 * Two primary entry points from the home page: jump to the full macro
 * dashboard, or open the pair scanner. Rendered as `Button` + `next/link`
 * (via `asChild`) so the shadcn button styles are applied to a real anchor,
 * giving correct client-side navigation.
 */
export function QuickActions() {
  return (
    <div className="flex flex-wrap gap-3">
      <Button asChild size="lg">
        <Link href="/macro">
          <TrendingUp className="h-4 w-4" />
          Open Macro Dashboard
        </Link>
      </Button>
      <Button asChild size="lg" variant="outline">
        <Link href="/scanner">
          <Search className="h-4 w-4" />
          Scan a Pair
        </Link>
      </Button>
    </div>
  );
}

export default QuickActions;
