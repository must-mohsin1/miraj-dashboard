const UTC_MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

/**
 * Format an ISO timestamp deterministically for server-rendered portfolio UI.
 *
 * Do not use the host or browser locale here: client-locale formatting can
 * render different text during hydration than the server rendered HTML.
 */
export function formatUtcDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  const month = UTC_MONTHS[date.getUTCMonth()];
  const day = date.getUTCDate();
  const year = date.getUTCFullYear();
  const hours = String(date.getUTCHours()).padStart(2, "0");
  const minutes = String(date.getUTCMinutes()).padStart(2, "0");

  return `${month} ${day}, ${year}, ${hours}:${minutes} UTC`;
}
