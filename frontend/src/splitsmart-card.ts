// Splitsmart Lovelace custom card — M2 entry point.
//
// Owns:
//   - hass (injected by Lovelace on every state change)
//   - _config (from setConfig)
//   - _route  (driven by the hash router)
//   - _splitsmartConfig, _expenses, _settlements (hydrated from the
//     websocket commands; kept fresh via subscribeExpenses deltas)
//
// Views are stateless w.r.t. data — they receive arrays + record
// dictionaries as properties and emit ss-navigate / ss-open-detail /
// ss-toast events upward. This keeps the subscription plumbing in one
// place and the views easy to reason about.

import { LitElement, html, css, type PropertyValues } from 'lit';
import { customElement, property, state } from 'lit/decorators.js';

import {
  getConfig as apiGetConfig,
  listExpenses as apiListExpenses,
  subscribeExpenses,
  type SubscribeEvent,
} from './api';
import { computeBalances, computePairwise } from './util/balances';
import { resolveLocale } from './util/currency';
import { navigate, subscribeRoute, type Route } from './router';
import { baseStyles, installGlobalStyles, typography } from './styles';
import type {
  Expense,
  HomeAssistant,
  Settlement,
  SplitsmartCardConfig,
  SplitsmartConfig,
} from './types';
import './views/home-view';
import './views/ledger-view';
import './views/add-expense-view';
import './views/settle-up-view';
import './views/expense-detail-sheet';
import './views/settlement-detail-sheet';
import './views/rules-view';
import './views/import-view';
import './views/import-wizard-view';
import './views/staging-view';
import './views/staging-detail-sheet';

export const VERSION = '0.1.0-m5';

const SUPPORTED_VIEWS = new Set(['home', 'ledger', 'add', 'settle', 'rules', 'import', 'wizard', 'staging']);

@customElement('splitsmart-card')
export class SplitsmartCard extends LitElement {
  @property({ attribute: false })
  hass?: HomeAssistant;

  @state()
  private _cardConfig: SplitsmartCardConfig = { type: 'custom:splitsmart-card' };

  @state()
  private _route: Route = { view: 'home', query: {} };

  /** Last non-detail route, so closing a detail sheet returns the user
   *  to the Ledger they came from (or home if they deep-linked). */
  @state()
  private _backgroundRoute: Route = { view: 'home', query: {} };

  @state()
  private _splitsmartConfig: SplitsmartConfig | null = null;

  @state()
  private _expenses: Expense[] = [];

  @state()
  private _settlements: Settlement[] = [];

  @state()
  private _loadError: string | null = null;

  private _routeUnsub: (() => void) | null = null;
  private _subUnsub: (() => void) | null = null;
  private _hydrating = false;

  setConfig(config: SplitsmartCardConfig): void {
    if (config.view && !SUPPORTED_VIEWS.has(config.view)) {
      throw new Error(
        `Unknown view '${config.view}'. Supported: home, ledger, add, settle.`,
      );
    }
    this._cardConfig = { ...config };
    // Pin the starting route if a view was configured AND the hash is
    // currently empty or at the default home view.
    if (config.view && !window.location.hash) {
      navigate(config.view);
    }
  }

  /** Lovelace reads this to retrieve the card config (editor etc.). */
  getConfig(): SplitsmartCardConfig {
    return this._cardConfig;
  }

  /** Lovelace layout hint — rough row count the card occupies. */
  getCardSize(): number {
    return 4;
  }

  connectedCallback(): void {
    super.connectedCallback();
    installGlobalStyles();
    this._routeUnsub = subscribeRoute((r) => {
      this._route = r;
      if (r.view !== 'expense' && r.view !== 'settlement') {
        this._backgroundRoute = r;
      }
    });
    this.addEventListener('ss-navigate', this._onNavigate as EventListener);
    this.addEventListener('ss-open-detail', this._onOpenDetail as EventListener);
  }

  disconnectedCallback(): void {
    super.disconnectedCallback();
    this._routeUnsub?.();
    this._subUnsub?.();
    this._routeUnsub = null;
    this._subUnsub = null;
    this.removeEventListener('ss-navigate', this._onNavigate as EventListener);
    this.removeEventListener('ss-open-detail', this._onOpenDetail as EventListener);
  }

  protected firstUpdated(_changed: PropertyValues): void {
    this._maybeHydrate();
  }

  protected updated(changed: PropertyValues): void {
    if (changed.has('hass') && !changed.get('hass') && this.hass) {
      this._maybeHydrate();
    }
    // Keep background route current for views that are not detail overlays.
    if (changed.has('_route')) {
      const r = this._route;
      const isDetail =
        r.view === 'expense' ||
        r.view === 'settlement' ||
        (r.view === 'staging' && !!r.param);
      if (!isDetail) this._backgroundRoute = r;
    }
  }

  private async _maybeHydrate(): Promise<void> {
    if (!this.hass || this._hydrating || this._splitsmartConfig) return;
    this._hydrating = true;
    try {
      const config = await apiGetConfig(this.hass);
      this._splitsmartConfig = config;
      const initial = await apiListExpenses(this.hass);
      this._expenses = initial.expenses;
      this._settlements = initial.settlements;
      this._subUnsub = await subscribeExpenses(this.hass, (ev) => this._onEvent(ev));
    } catch (err: unknown) {
      this._loadError = err instanceof Error ? err.message : String(err);
    } finally {
      this._hydrating = false;
    }
  }

  private _onEvent(ev: SubscribeEvent): void {
    if (ev.kind === 'init') {
      this._expenses = ev.expenses;
      this._settlements = ev.settlements;
      return;
    }
    const nextExpenses = new Map(this._expenses.map((e) => [e.id, e]));
    const nextSettlements = new Map(this._settlements.map((s) => [s.id, s]));

    for (const item of [...ev.added, ...ev.updated]) {
      if (item.kind === 'expense') {
        nextExpenses.set(item.record.id, item.record as Expense);
      } else {
        nextSettlements.set(item.record.id, item.record as Settlement);
      }
    }
    for (const id of ev.deleted) {
      nextExpenses.delete(id);
      nextSettlements.delete(id);
    }
    this._expenses = [...nextExpenses.values()];
    this._settlements = [...nextSettlements.values()];
  }

  private _onNavigate = (e: Event) => {
    const route = (e as CustomEvent<{ route: string }>).detail?.route;
    if (typeof route === 'string') navigate(route);
  };

  private _onOpenDetail = (e: Event) => {
    const id = (e as CustomEvent<{ expense_id?: string; settlement_id?: string }>).detail
      ?.expense_id;
    const sid = (e as CustomEvent<{ settlement_id?: string }>).detail?.settlement_id;
    if (id) navigate(`expense/${id}`);
    else if (sid) navigate(`settlement/${sid}`);
  };

  private _locale(): string {
    return resolveLocale(this.hass?.locale?.language);
  }

  /**
   * Resolve the current user's pending-count sensor from hass.states.
   *
   * The sensor's unique_id encodes the HA user_id but its entity_id is
   * slugged from the display name, which we can't reliably re-derive in
   * the frontend. Instead, the sensor exposes `user_id` as an attribute
   * (see sensor.PendingCountSensor); we scan hass.states for the one
   * matching the current user.
   *
   * Returns `null` when the integration hasn't booted yet or the sensor
   * isn't in hass.states. The placeholder tile falls back to its static
   * caption in that case.
   */
  private _pendingCountForCurrentUser(): number | null {
    if (!this.hass || !this._splitsmartConfig) return null;
    const myId = this._splitsmartConfig.current_user_id;
    for (const [entityId, state] of Object.entries(this.hass.states)) {
      if (!entityId.startsWith('sensor.splitsmart_pending_count_')) continue;
      const attrUserId = (state as { attributes?: Record<string, unknown> }).attributes
        ?.user_id;
      if (attrUserId !== myId) continue;
      const raw = (state as { state?: string }).state;
      if (raw === undefined || raw === 'unavailable' || raw === 'unknown') return null;
      const parsed = Number.parseInt(raw, 10);
      return Number.isFinite(parsed) ? parsed : null;
    }
    return null;
  }

  private _renderView() {
    if (this._loadError) {
      return html`
        <div class="error ss-text-body">
          Could not load Splitsmart: <strong>${this._loadError}</strong>
        </div>
      `;
    }

    const balances = computeBalances(this._expenses, this._settlements);
    const pairwise: Record<string, number> = {};
    for (const [from, row] of Object.entries(
      computePairwise(this._expenses, this._settlements),
    )) {
      for (const [to, amt] of Object.entries(row)) {
        pairwise[`${from}:${to}`] = amt;
      }
    }

    const isDetailOverlay =
      this._route.view === 'expense' ||
      this._route.view === 'settlement' ||
      (this._route.view === 'staging' && !!this._route.param);
    const routeForPrimary = isDetailOverlay ? this._backgroundRoute : this._route;

    const primary = this._renderRoute(routeForPrimary, balances, pairwise);

    if (this._route.view === 'staging' && this._route.param) {
      return html`
        ${primary}
        <ss-staging-detail-sheet
          .hass=${this.hass}
          .config=${this._splitsmartConfig}
          .stagingId=${this._route.param}
          @close=${() => navigate('staging')}
        ></ss-staging-detail-sheet>
      `;
    }

    if (this._route.view === 'expense') {
      const expense = this._expenses.find((e) => e.id === this._route.param) ?? null;
      return html`
        ${primary}
        <ss-expense-detail-sheet
          .hass=${this.hass}
          .config=${this._splitsmartConfig}
          .expense=${expense}
          .locale=${this._locale()}
          @close=${this._onDetailClose}
        ></ss-expense-detail-sheet>
      `;
    }

    if (this._route.view === 'settlement') {
      const settlement =
        this._settlements.find((s) => s.id === this._route.param) ?? null;
      return html`
        ${primary}
        <ss-settlement-detail-sheet
          .hass=${this.hass}
          .config=${this._splitsmartConfig}
          .settlement=${settlement}
          .expenses=${this._expenses}
          .settlements=${this._settlements}
          .locale=${this._locale()}
          @close=${this._onDetailClose}
        ></ss-settlement-detail-sheet>
      `;
    }

    return primary;
  }

  private _onDetailClose = (): void => {
    const back = this._backgroundRoute;
    const qs = Object.entries(back.query)
      .filter(([, v]) => v)
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
      .join('&');
    const param = back.param ? `/${back.param}` : '';
    navigate(qs ? `${back.view}${param}?${qs}` : `${back.view}${param}`);
  };

  private _renderRoute(
    route: Route,
    balances: Record<string, number>,
    pairwise: Record<string, number>,
  ) {
    switch (route.view) {
      case 'ledger':
        return html`
          <ss-ledger-view
            .config=${this._splitsmartConfig}
            .expenses=${this._expenses}
            .settlements=${this._settlements}
            .query=${route.query}
            .locale=${this._locale()}
          ></ss-ledger-view>
        `;
      case 'add':
        return html`
          <ss-add-expense-view
            .hass=${this.hass}
            .config=${this._splitsmartConfig}
            .locale=${this._locale()}
          ></ss-add-expense-view>
        `;
      case 'settle':
        return html`
          <ss-settle-up-view
            .hass=${this.hass}
            .config=${this._splitsmartConfig}
            .expenses=${this._expenses}
            .settlements=${this._settlements}
            .locale=${this._locale()}
          ></ss-settle-up-view>
        `;
      case 'rules':
        return html`
          <ss-rules-view
            .hass=${this.hass}
            .config=${this._splitsmartConfig}
          ></ss-rules-view>
        `;
      case 'import':
        return html`
          <ss-import-view
            .hass=${this.hass}
            .config=${this._splitsmartConfig}
          ></ss-import-view>
        `;
      case 'wizard':
        return html`
          <ss-import-wizard-view
            .hass=${this.hass}
            .config=${this._splitsmartConfig}
            .uploadId=${route.param ?? ''}
          ></ss-import-wizard-view>
        `;
      case 'staging':
        return html`
          <ss-staging-view
            .hass=${this.hass}
            .config=${this._splitsmartConfig}
          ></ss-staging-view>
        `;
      case 'home':
      default:
        return html`
          <ss-home-view
            .config=${this._splitsmartConfig}
            .expenses=${this._expenses}
            .settlements=${this._settlements}
            .balances=${balances}
            .pairwise=${pairwise}
            .locale=${this._locale()}
            .pendingCount=${this._pendingCountForCurrentUser()}
          ></ss-home-view>
        `;
    }
  }

  render() {
    return html`
      <ha-card>
        ${this.hass
          ? this._renderView()
          : html`<div class="loading ss-text-caption">Waiting for Home Assistant…</div>`}
      </ha-card>
    `;
  }

  static styles = [
    baseStyles,
    typography,
    css`
      ha-card {
        background: var(--card-background-color, #ffffff);
        color: var(--primary-text-color, #1a1a1a);
        border-radius: var(--ss-card-radius);
        overflow: hidden;
      }
      .loading {
        padding: var(--ss-space-5);
        color: var(--secondary-text-color, #5a5a5a);
      }
      .error {
        padding: var(--ss-space-5);
        color: var(--error-color, #db4437);
      }
    `,
  ];
}

// Register an entry in the Lovelace "Add Card" gallery. Preview artwork
// is deferred to M7 polish (decision 4 from M2_PLAN.md §8).
window.customCards = window.customCards ?? [];
if (!window.customCards.some((c) => c.type === 'splitsmart-card')) {
  window.customCards.push({
    type: 'splitsmart-card',
    name: 'Splitsmart',
    description: 'Household expense splitting — balances, ledger, add, settle up.',
  });
}

declare global {
  interface HTMLElementTagNameMap {
    'splitsmart-card': SplitsmartCard;
  }
}
