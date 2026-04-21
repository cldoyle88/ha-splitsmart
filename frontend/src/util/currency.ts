// Currency and number formatting helpers.
//
// Always goes through Intl.NumberFormat so currency symbols render
// correctly in every locale HA supports. formatAmount is the sole
// public function for human-facing amounts; formatSignedAmount prefixes
// a minus for negative numbers and strips trailing .00 when irrelevant.

const CACHE = new Map<string, Intl.NumberFormat>();

function formatter(locale: string, currency: string): Intl.NumberFormat {
  const key = `${locale}|${currency}`;
  let f = CACHE.get(key);
  if (f) return f;
  f = new Intl.NumberFormat(locale, {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  CACHE.set(key, f);
  return f;
}

/** Format an amount as a localised currency string. */
export function formatAmount(
  amount: number,
  currency: string,
  locale = 'en-GB',
): string {
  if (!Number.isFinite(amount)) return '—';
  return formatter(locale, currency).format(amount);
}

/** Format an absolute amount — always positive output, useful for
 *  'you owe X £45' phrasing where the sign lives in the caption. */
export function formatAbs(amount: number, currency: string, locale = 'en-GB'): string {
  return formatAmount(Math.abs(amount), currency, locale);
}

/** Parse a user-entered numeric string into a Decimal-safe number.
 *  Accepts '1234.56', '1,234.56', '£1,234.56'. Returns null on empty
 *  / non-numeric input so callers can validate upstream. */
export function parseAmount(input: string): number | null {
  if (input == null) return null;
  const cleaned = String(input)
    .replace(/[\s\u00A0]/g, '')
    .replace(/^[^0-9-.]+/, '')
    .replace(/,/g, '');
  if (!cleaned || cleaned === '-' || cleaned === '.') return null;
  const n = Number(cleaned);
  return Number.isFinite(n) ? Math.round(n * 100) / 100 : null;
}

/** Resolve a hass.locale? into an Intl locale string with 'en-GB' fallback. */
export function resolveLocale(lang?: string | null): string {
  if (!lang) return 'en-GB';
  return lang;
}
