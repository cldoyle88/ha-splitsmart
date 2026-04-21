// Hash-based router for <splitsmart-card>.
//
// Parses ``location.hash`` into a Route and fires a callback whenever
// the hash changes. Supports:
//   #home
//   #ledger
//   #ledger?month=2026-04&category=Groceries
//   #add
//   #settle
//   #expense/ex_01J9X
//   #settlement/sl_01J9X
//
// Anything malformed or unsupported falls back to {view:'home', query:{}}.
// Deep links, the browser back button, and the mobile companion's
// notification-link handler all work unchanged.

export type RouteView =
  | 'home'
  | 'ledger'
  | 'add'
  | 'settle'
  | 'expense'
  | 'settlement';

export interface Route {
  view: RouteView;
  /** Entity id for detail views (expense / settlement). */
  param?: string;
  /** Optional query string parameters parsed from after ?. */
  query: Record<string, string>;
}

const VIEWS: ReadonlySet<RouteView> = new Set([
  'home',
  'ledger',
  'add',
  'settle',
  'expense',
  'settlement',
]);

const DEFAULT_ROUTE: Route = { view: 'home', query: {} };

/** Parse a hash fragment into a Route. Accepts both forms (with and without
 *  the leading `#`). Never throws — malformed input returns the home route. */
export function parseHash(hash: string): Route {
  const raw = (hash.startsWith('#') ? hash.slice(1) : hash).trim();
  if (!raw) return { ...DEFAULT_ROUTE };

  const [pathPart, queryPart = ''] = raw.split('?');
  const [viewSeg, paramSeg] = pathPart!.split('/');

  if (!viewSeg || !VIEWS.has(viewSeg as RouteView)) {
    return { ...DEFAULT_ROUTE };
  }

  const view = viewSeg as RouteView;
  const requiresParam = view === 'expense' || view === 'settlement';
  if (requiresParam && !paramSeg) {
    return { ...DEFAULT_ROUTE };
  }

  const query: Record<string, string> = {};
  if (queryPart) {
    for (const chunk of queryPart.split('&')) {
      if (!chunk) continue;
      const [k, v = ''] = chunk.split('=');
      if (k) query[decodeURIComponent(k)] = decodeURIComponent(v);
    }
  }

  const route: Route = { view, query };
  if (requiresParam) route.param = paramSeg!;
  return route;
}

/** Serialise a Route back into a hash fragment (no leading `#`). */
export function serialise(route: Route): string {
  const param = route.param ? `/${route.param}` : '';
  const entries = Object.entries(route.query ?? {}).filter(([, v]) => v !== '');
  const qs = entries
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
    .join('&');
  return qs ? `${route.view}${param}?${qs}` : `${route.view}${param}`;
}

/**
 * Subscribe to hash changes. Callback is invoked synchronously once with
 * the current route, then every time ``location.hash`` changes. Returns
 * an unsubscribe function.
 */
export function subscribeRoute(cb: (route: Route) => void): () => void {
  const handler = () => cb(parseHash(window.location.hash));
  window.addEventListener('hashchange', handler);
  cb(parseHash(window.location.hash));
  return () => window.removeEventListener('hashchange', handler);
}

/** Programmatic navigation — assigns ``location.hash``. Accepts a Route
 *  or a hash-string shortcut like 'ledger?month=2026-04'. */
export function navigate(to: Route | string): void {
  const hash = typeof to === 'string' ? to : serialise(to);
  window.location.hash = hash;
}
