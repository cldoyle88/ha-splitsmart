// Date helpers for row labels and filters.
//
// Relative buckets (Today / Yesterday / Tuesday / 15 Apr / 15 Apr 2025)
// match the Guardian-ish prose style used across the UI. Tests pin to
// a frozen date so the boundary logic is stable across days.

const MS_PER_DAY = 24 * 60 * 60 * 1000;

function startOfDay(d: Date): Date {
  const out = new Date(d);
  out.setHours(0, 0, 0, 0);
  return out;
}

/** Parse a YYYY-MM-DD string into a local-time Date at midnight. */
export function parseDate(iso: string): Date {
  const [y, m, d] = iso.split('-').map((s) => parseInt(s, 10));
  return new Date(y!, (m ?? 1) - 1, d ?? 1);
}

/**
 * Human-friendly day label relative to ``now``:
 * - Today / Yesterday.
 * - Weekday name for the rest of the current week.
 * - "15 Apr" within the last 12 months.
 * - "15 Apr 2025" earlier than that.
 */
export function formatRelativeDate(
  iso: string,
  now: Date = new Date(),
  locale = 'en-GB',
): string {
  const target = startOfDay(parseDate(iso));
  const today = startOfDay(now);
  const diffDays = Math.round((today.getTime() - target.getTime()) / MS_PER_DAY);

  if (diffDays === 0) return 'Today';
  if (diffDays === 1) return 'Yesterday';
  if (diffDays >= 2 && diffDays < 7) {
    return target.toLocaleDateString(locale, { weekday: 'long' });
  }

  const sameYear = target.getFullYear() === today.getFullYear();
  const recent =
    target.getTime() >= today.getTime() - 365 * MS_PER_DAY &&
    target.getTime() <= today.getTime();

  if (sameYear || recent) {
    return target.toLocaleDateString(locale, { day: 'numeric', month: 'short' });
  }
  return target.toLocaleDateString(locale, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });
}

/** "April 2026" from a YYYY-MM string. */
export function formatMonthLabel(yyyymm: string, locale = 'en-GB'): string {
  const [y, m] = yyyymm.split('-').map((s) => parseInt(s, 10));
  const d = new Date(y!, (m ?? 1) - 1, 1);
  return d.toLocaleDateString(locale, { month: 'long', year: 'numeric' });
}

/** Return the last N months in reverse-chronological order as YYYY-MM. */
export function recentMonths(count = 12, now: Date = new Date()): string[] {
  const out: string[] = [];
  const d = new Date(now.getFullYear(), now.getMonth(), 1);
  for (let i = 0; i < count; i++) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    out.push(`${y}-${m}`);
    d.setMonth(d.getMonth() - 1);
  }
  return out;
}

/** Current month as YYYY-MM. */
export function currentMonth(now: Date = new Date()): string {
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, '0');
  return `${y}-${m}`;
}
