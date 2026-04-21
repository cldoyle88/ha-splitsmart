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

export const VERSION = '0.1.0-m2';

const SUPPORTED_VIEWS = new Set(['home', 'ledger', 'add', 'settle']);

@customElement('splitsmart-card')
export class SplitsmartCard extends LitElement {
  @property({ attribute: false })
  hass?: HomeAssistant;

  @state()
  private _cardConfig: SplitsmartCardConfig = { type: 'custom:splitsmart-card' };

  @state()
  private _route: Route = { view: 'home', query: {} };

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
    });
    this.addEventListener('ss-navigate', this._onNavigate as EventListener);
  }

  disconnectedCallback(): void {
    super.disconnectedCallback();
    this._routeUnsub?.();
    this._subUnsub?.();
    this._routeUnsub = null;
    this._subUnsub = null;
    this.removeEventListener('ss-navigate', this._onNavigate as EventListener);
  }

  protected firstUpdated(_changed: PropertyValues): void {
    this._maybeHydrate();
  }

  protected updated(changed: PropertyValues): void {
    if (changed.has('hass') && !changed.get('hass') && this.hass) {
      this._maybeHydrate();
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

  private _locale(): string {
    return resolveLocale(this.hass?.locale?.language);
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

    switch (this._route.view) {
      case 'ledger':
        return html`
          <ss-ledger-view
            .config=${this._splitsmartConfig}
            .expenses=${this._expenses}
            .settlements=${this._settlements}
            .query=${this._route.query}
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
