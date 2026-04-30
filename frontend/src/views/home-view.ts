// <ss-home-view
//    .hass=${hass}
//    .config=${splitsmartConfig}
//    .expenses=${expenses}
//    .settlements=${settlements}
//    .balances=${balances}
//    .pairwise=${pairwise}
// ></ss-home-view>
//
// Home view:
//   - Hero headline: "You owe X £Y" / "X owes you £Y" (two-person
//     case), "Your net balance: £Y" (N>=3).
//   - Per-user balance strip.
//   - Quick-action buttons: Add expense, Settle up, Ledger.
//   - Staging "Coming in M5" placeholder tile (decision 10).
//   - Last-expense compact row-card tile at the bottom when history exists.
//   - Empty-state handling (decision 12): 'No expenses yet' on first
//     install; 'You're all square' when balances are all zero.

import { LitElement, html, css, type PropertyValues } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { baseStyles, typography } from '../styles';
import { formatAbs } from '../util/currency';
import { formatRelativeDate } from '../util/date';
import type { Expense, Settlement, SplitsmartConfig } from '../types';
import '../components/balance-strip';
import '../components/row-card';
import '../components/button';
import '../components/icon';
import '../components/empty-state';
import '../components/placeholder-tile';

@customElement('ss-home-view')
export class SsHomeView extends LitElement {
  @property({ attribute: false })
  config: SplitsmartConfig | null = null;

  @property({ attribute: false })
  expenses: Expense[] = [];

  @property({ attribute: false })
  settlements: Settlement[] = [];

  @property({ attribute: false })
  balances: Record<string, number> = {};

  @property({ attribute: false })
  pairwise: Record<string, number> = {};

  @property({ type: String })
  locale = 'en-GB';

  /**
   * Pending-row count for the current user, read by the root from
   * sensor.splitsmart_pending_count_<user>. `null` when the sensor
   * isn't available yet (first paint, integration mid-load).
   */
  @property({ attribute: false })
  pendingCount: number | null = null;

  private _navigate(route: string) {
    this.dispatchEvent(
      new CustomEvent('ss-navigate', {
        detail: { route },
        bubbles: true,
        composed: true,
      }),
    );
  }

  private _zeroBalances(): boolean {
    if (!this.config) return true;
    return this.config.participants
      .filter((p) => p.active)
      .every((p) => Math.round((this.balances[p.user_id] ?? 0) * 100) === 0);
  }

  private _latestSettlement(): Settlement | null {
    if (this.settlements.length === 0) return null;
    return this.settlements
      .slice()
      .sort((a, b) => b.date.localeCompare(a.date))[0] ?? null;
  }

  private _latestExpense(): Expense | null {
    if (this.expenses.length === 0) return null;
    return this.expenses
      .slice()
      .sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''))[0] ?? null;
  }

  private _headline() {
    if (!this.config) return html``;
    const home = this.config.home_currency;
    const meId = this.config.current_user_id;
    const activeOthers = this.config.participants.filter(
      (p) => p.active && p.user_id !== meId,
    );

    // Two-person household — phrase as 'You owe X' or 'X owes you'.
    if (activeOthers.length === 1) {
      const other = activeOthers[0]!;
      const net = Math.round((this.balances[meId] ?? 0) * 100) / 100;
      if (net > 0) {
        return html`
          <div class="ss-text-display hero">
            <span class="name">${other.display_name}</span> owes you
            <span class="ss-mono-display credit">${formatAbs(net, home, this.locale)}</span>
          </div>
        `;
      }
      if (net < 0) {
        return html`
          <div class="ss-text-display hero">
            You owe <span class="name">${other.display_name}</span>
            <span class="ss-mono-display debit">${formatAbs(net, home, this.locale)}</span>
          </div>
        `;
      }
      return html`
        <div class="ss-text-display hero">You're all square.</div>
      `;
    }

    // N >= 3 participants — show the caller's net.
    const net = Math.round((this.balances[meId] ?? 0) * 100) / 100;
    const label =
      net > 0
        ? html`Your net: <span class="ss-mono-display credit"
            >+${formatAbs(net, home, this.locale)}</span
          >`
        : net < 0
          ? html`Your net: <span class="ss-mono-display debit"
              >-${formatAbs(net, home, this.locale)}</span
            >`
          : html`You're all square.`;
    return html`<div class="ss-text-display hero">${label}</div>`;
  }

  private _emptyState() {
    const firstInstall = this.expenses.length === 0 && this.settlements.length === 0;
    if (firstInstall) {
      return html`
        <ss-empty-state
          icon="mdi:plus-circle-outline"
          heading="No expenses yet"
          caption="Add your first expense to get started."
        >
          <ss-button
            slot="action"
            variant="primary"
            @click=${() => this._navigate('add')}
            >Add expense</ss-button
          >
          <ss-button
            slot="action"
            variant="secondary"
            @click=${() => this._navigate('settle')}
            >Settle up</ss-button
          >
        </ss-empty-state>
      `;
    }

    const latest = this._latestSettlement();
    const caption = latest
      ? `Last settled ${formatRelativeDate(latest.date, new Date(), this.locale)}.`
      : 'All balances are zero.';
    return html`
      <ss-empty-state
        icon="mdi:check-circle-outline"
        heading="You're all square"
        caption=${caption}
      >
        <ss-button
          slot="action"
          variant="primary"
          @click=${() => this._navigate('add')}
          >Add expense</ss-button
        >
      </ss-empty-state>
    `;
  }

  private _lastExpenseTile() {
    const last = this._latestExpense();
    if (!last || !this.config) return html``;
    return html`
      <div class="section">
        <div class="ss-text-caption section-label">Latest expense</div>
        <ss-row-card
          .expense=${last}
          .participants=${this.config.participants}
          .homeCurrency=${this.config.home_currency}
          .locale=${this.locale}
          variant="compact"
        ></ss-row-card>
      </div>
    `;
  }

  protected updated(_changed: PropertyValues) {
    // Reserved for subscription rebinding in step 11.
  }

  render() {
    if (!this.config) {
      return html`<div class="loading ss-text-caption">Loading…</div>`;
    }

    const showEmpty = this._zeroBalances() && this.expenses.length === 0;

    return html`
      <div class="container">
        ${showEmpty ? this._emptyState() : html`${this._headline()}`}
        ${!showEmpty
          ? html`
              <ss-balance-strip
                .participants=${this.config.participants}
                .balances=${this.balances}
                .homeCurrency=${this.config.home_currency}
                .locale=${this.locale}
              ></ss-balance-strip>
            `
          : ''}

        <div class="actions">
          <ss-button variant="primary" @click=${() => this._navigate('add')}>
            Add expense
          </ss-button>
          <ss-button variant="secondary" @click=${() => this._navigate('settle')}>
            Settle up
          </ss-button>
          <ss-button variant="secondary" @click=${() => this._navigate('ledger')}>
            Ledger
          </ss-button>
        </div>

        <div
          class="import-tile"
          role="button"
          tabindex="0"
          @click=${() => this._navigate('import')}
          @keydown=${(e: KeyboardEvent) => e.key === 'Enter' && this._navigate('import')}
        >
          <div class="import-tile-left">
            <span class="import-icon" aria-hidden="true">↑</span>
            <div>
              <div class="ss-text-body import-title">Import statement</div>
              <div class="ss-text-caption import-caption">
                ${this.pendingCount !== null && this.pendingCount > 0
                  ? `${this.pendingCount} row${this.pendingCount !== 1 ? 's' : ''} pending review`
                  : 'Upload a bank CSV, OFX, or XLSX file'}
              </div>
            </div>
          </div>
          ${this.pendingCount !== null && this.pendingCount > 0
            ? html`<span class="pending-badge ss-text-caption">${this.pendingCount}</span>`
            : ''}
        </div>

        ${this._lastExpenseTile()}
      </div>
    `;
  }

  static styles = [
    baseStyles,
    typography,
    css`
      .container {
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-5);
        padding: var(--ss-space-4);
      }
      .hero {
        color: var(--primary-text-color, #1a1a1a);
        line-height: 1.25;
      }
      .hero .name {
        font-weight: 600;
      }
      .credit {
        color: var(--ss-credit-color);
      }
      .debit {
        color: var(--ss-debit-color);
      }
      .actions {
        display: flex;
        flex-wrap: wrap;
        gap: var(--ss-space-3);
      }
      .section {
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-2);
      }
      .section-label {
        color: var(--secondary-text-color, #5a5a5a);
        text-transform: uppercase;
        letter-spacing: 0.5px;
      }
      .loading {
        padding: var(--ss-space-4);
        color: var(--secondary-text-color, #5a5a5a);
      }
      .import-tile {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--ss-space-3);
        padding: var(--ss-space-3) var(--ss-space-4);
        background: var(--secondary-background-color, #f5f5f5);
        border-radius: 10px;
        cursor: pointer;
        min-height: var(--ss-touch-min);
        transition: background-color var(--ss-duration-fast) var(--ss-easing-standard);
      }
      .import-tile:hover {
        background: color-mix(in srgb, var(--ss-accent-color) 10%, var(--secondary-background-color, #f5f5f5));
      }
      .import-tile:focus-visible {
        outline: 2px solid var(--primary-color, #03a9f4);
        outline-offset: 2px;
      }
      .import-tile-left {
        display: flex;
        align-items: center;
        gap: var(--ss-space-3);
      }
      .import-icon {
        font-size: 22px;
        color: var(--ss-accent-color);
        line-height: 1;
      }
      .import-title {
        font-weight: 500;
      }
      .import-caption {
        color: var(--secondary-text-color, #5a5a5a);
      }
      .pending-badge {
        background: var(--ss-accent-color);
        color: var(--text-primary-color, #ffffff);
        border-radius: 10px;
        padding: 2px var(--ss-space-2);
        font-weight: 600;
        min-width: 22px;
        text-align: center;
      }
    `,
  ];
}

declare global {
  interface HTMLElementTagNameMap {
    'ss-home-view': SsHomeView;
  }
}
