"use client";

import { useSyncExternalStore } from "react";

// Times are stored in UTC and shown in the *viewer's* time zone. The server can't know
// that zone (on Vercel it's UTC), so formatting has to happen in the browser.
//
// useSyncExternalStore gives the server a different value (null) than the browser,
// without a hydration mismatch: React renders the fallback first, then the local time.

const FORMATS = {
  date: { weekday: "short", month: "short", day: "numeric", year: "numeric" },
  datetime: { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" },
  time: { hour: "numeric", minute: "2-digit" },
} satisfies Record<string, Intl.DateTimeFormatOptions>;

const noSubscribe = () => () => {};

export function LocalTime({ iso, format = "datetime" }: { iso: string; format?: keyof typeof FORMATS }) {
  const text = useSyncExternalStore(
    noSubscribe,
    () => new Intl.DateTimeFormat(undefined, FORMATS[format]).format(new Date(iso)),
    () => null,
  );
  // Server render shows a neutral placeholder; the browser swaps in the local time at once.
  return <time dateTime={iso}>{text ?? "…"}</time>;
}
