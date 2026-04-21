// <ss-ledger-view
//    .config=${cfg}
//    .expenses=${expenses}
//    .settlements=${settlements}
//    .query=${routeQuery}
// ></ss-ledger-view>
//
// Reverse-chronological list of shared expenses with settlements
// interleaved on their date. Filter chips for month + category live
// inline here; when Staging and Rules views reuse the same pill-filter
// pattern in M5 we extract <ss-filter-chip> per the M2 plan §5.

// TODO(M5): extract to components/filter-chip.ts when Staging and Rules views
// reuse the pill-filter pattern.

import { LitElement, html, css } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { baseStyles, typography } from '../styles';
import { formatAmount } from '../util/currency';
import { currentMonth, formatMonthLabel, recentMonths } from '../util/date';
import type { Expense, Settlement, SplitsmartConfig } from '../types';
import '../components/row-card';
import '../components/empty-state';
import '../components/button';
import '../components/user-avatar';

interface TimelineEntry {
  kind: 'expense' | 'settlement';
  date: string;
  record: Expense | Settlement;
}

const ALL_MONTHS = '__all__';

@customElement('ss-ledger-view')
export class SsLedgerView extends LitElement {
  @property({ attribute: false })
  config: SplitsmartConfig | null = null;

  @property({ attribute: false })
  expenses: Expense[] = [];

  @property({ attribute: false })
  settlements: Settlement[] = [];

  /** Route query: { month?, category? } drives the filter chips. */
  @property({ attribute: false })
  query: Record<string, string> = {};

  @property({ type: String })
  locale = 'en-GB';

  private _navigate(to: string) {
    this.dispatchEvent(
      new CustomEvent('ss-navigate', {
        detail: { route: to },
        bubbles: true,
        composed: true,
      }),
    );
  }

  private _setQuery(next: Record<string, string>): void {
    const merged: Record<string, string> = { ...this.query, ...next };
    // Strip empties so the hash stays clean.
    const entries = Object.entries(merged).filter(([, v]) => v && v !== ALL_MONTHS);
    const qs = entries
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
      .join('&');
    this._navigate(qs ? `ledger?${qs}` : 'ledger');
  }

  private _selectedMonth(): string {
    return this.query.month || currentMonth();
  }

  private _availableMonths(): string[] {
    const months = new Set<string>();
    for (const e of this.expenses) {
      if (e.date) months.add(e.date.slice(0, 7));
    }
    for (const s of this.settlements) {
      if (s.date) months.add(s.date.slice(0, 7));
    }
    // Ensure the current month is selectable even before any history exists.
    months.add(currentMonth());
    // Always include the last 12 months for a consistent picker.
    for (const m of recentMonths(12)) months.add(m);
    return Array.from(months).sort().reverse();
  }

  private _filter(): TimelineEntry[] {
    const selectedMonth = this._selectedMonth();
    const selectedCategory = this.query.category ?? '';
    const selectedPaidBy = this.query.paid_by ?? '';
    const entries: TimelineEntry[] = [];

    for (const e of this.expenses) {
      if (selectedMonth !== ALL_MONTHS && !e.date.startsWith(selectedMonth)) continue;
      if (
        selectedCategory &&
        !(e.categories ?? []).some((c) => c.name === selectedCategory)
      )
        continue;
      if (selectedPaidBy && e.paid_by !== selectedPaidBy) continue;
      entries.push({ kind: 'expense', date: e.date, record: e });
    }

    if (!selectedCategory && !selectedPaidBy) {
      for (const s of this.settlements) {
        if (selectedMonth !== ALL_MONTHS && !s.date.startsWith(selectedMonth)) continue;
        entries.push({ kind: 'settlement', date: s.date, record: s });
      }
    }

    entries.sort((a, b) => b.date.localeCompare(a.date));
    return entries;
  }

  private _renderFilters() {
    if (!this.config) return html``;
    const months = this._availableMonths();
    const selectedMonth = this._selectedMonth();
    const categories = this.config.categories;
    const selectedCategory = this.query.category ?? '';

    return html`
      <div class="filters">
        <div class="chip-group" role="listbox" aria-label="Month">
          ${months.map(
            (m) => html`
              <button
                class="chip ${m === selectedMonth ? 'active' : ''} ss-focus-ring ss-text-button"
                type="button"
                role="option"
                aria-selected=${m === selectedMonth ? 'true' : 'false'}
                @click=${() => this._setQuery({ month: m })}
              >
                ${formatMonthLabel(m, this.locale)}
              </button>
            `,
          )}
          <button
            class="chip ${selectedMonth === ALL_MONTHS ? 'active' : ''} ss-focus-ring ss-text-button"
            type="button"
            @click=${() => this._setQuery({ month: ALL_MONTHS })}
          >
            All
          </button>
        </div>
        <div class="chip-group" role="listbox" aria-label="Category">
          <button
            class="chip ${selectedCategory === '' ? 'active' : ''} ss-focus-ring ss-text-button"
            type="button"
            @click=${() => this._setQuery({ category: '' })}
          >
            All categories
          </button>
          ${categories.map(
            (c) => html`
              <button
                class="chip ${selectedCategory === c ? 'active' : ''} ss-focus-ring ss-text-button"
                type="button"
                @click=${() => this._setQuery({ category: c })}
              >
                ${c}
              </button>
            `,
          )}
        </div>
      </div>
    `;
  }

  private _renderSettlementRow(s: Settlement) {
    if (!this.config) return html``;
    const fromUser = this.config.participants.find((p) => p.user_id === s.from_user);
    const toUser = this.config.participants.find((p) => p.user_id === s.to_user);
    const amount = formatAmount(s.home_amount, this.config.home_currency, this.locale);
    return html`
      <div
        class="settlement-row ss-focus-ring"
        role="button"
        tabindex="0"
        @click=${() =>
          this.dispatchEvent(
            new CustomEvent('ss-navigate', {
              detail: { route: `settlement/${s.id}` },
              bubbles: true,
              composed: true,
            }),
          )}
        @keydown=${(ev: KeyboardEvent) => {
          if (ev.key === 'Enter' || ev.key === ' ') {
            ev.preventDefault();
            this.dispatchEvent(
              new CustomEvent('ss-navigate', {
                detail: { route: `settlement/${s.id}` },
                bubbles: true,
                composed: true,
              }),
            );
          }
        }}
      >
        <div class="settlement-icon">⇄</div>
        <div class="settlement-copy">
          <div class="ss-text-body">
            ${fromUser?.display_name ?? s.from_user} → ${toUser?.display_name ?? s.to_user}
          </div>
          <div class="ss-text-caption">Settlement${s.notes ? ` · ${s.notes}` : ''}</div>
        </div>
        <div class="ss-mono-amount amount settled">${amount}</div>
      </div>
    `;
  }

  private _renderGroupedTimeline(entries: TimelineEntry[]) {
    if (!this.config) return html``;
    const groups = new Map<string, TimelineEntry[]>();
    for (const entry of entries) {
      const bucket = groups.get(entry.date) ?? [];
      bucket.push(entry);
      groups.set(entry.date, bucket);
    }
    return Array.from(groups.entries()).map(
      ([date, items]) => html`
        <section class="day">
          <header class="ss-text-caption date-header">
            ${new Date(date).toLocaleDateString(this.locale, {
              weekday: 'short',
              day: 'numeric',
              month: 'short',
            })}
          </header>
          <div class="rows">
            ${items.map((item) =>
              item.kind === 'expense'
                ? html`<ss-row-card
                    .expense=${item.record as Expense}
                    .participants=${this.config!.participants}
                    .homeCurrency=${this.config!.home_currency}
                    .locale=${this.locale}
                  ></ss-row-card>`
                : this._renderSettlementRow(item.record as Settlement),
            )}
          </div>
        </section>
      `,
    );
  }

  render() {
    if (!this.config) return html`<div class="ss-text-caption loading">Loading…</div>`;

    const entries = this._filter();

    return html`
      <div class="container">
        <header class="page-header">
          <ss-button variant="secondary" @click=${() => this._navigate('home')}>
            Back
          </ss-button>
          <div class="ss-text-title">Ledger</div>
          <ss-button variant="primary" @click=${() => this._navigate('add')}>
            Add expense
          </ss-button>
        </header>

        ${this._renderFilters()}
        ${entries.length === 0
          ? html`
              <ss-empty-state
                icon="mdi:filter-outline"
                heading="No expenses match"
                caption="Try widening the month or clearing the category filter."
              >
                <ss-button
                  slot="action"
                  variant="secondary"
                  @click=${() => this._setQuery({ month: ALL_MONTHS, category: '' })}
                >
                  Clear filters
                </ss-button>
              </ss-empty-state>
            `
          : html`<div class="timeline">${this._renderGroupedTimeline(entries)}</div>`}
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
        gap: var(--ss-space-4);
        padding: var(--ss-space-4);
      }
      .page-header {
        display: flex;
        align-items: center;
        gap: var(--ss-space-3);
      }
      .page-header .ss-text-title {
        flex: 1;
      }
      .filters {
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-2);
      }
      .chip-group {
        display: flex;
        flex-wrap: wrap;
        gap: var(--ss-space-2);
        padding: 0;
      }
      .chip {
        min-height: 36px;
        padding: var(--ss-space-2) var(--ss-space-3);
        border-radius: 999px;
        border: 1px solid var(--divider-color, #e0e0e0);
        background-color: var(--card-background-color, #ffffff);
        color: var(--primary-text-color, #1a1a1a);
        cursor: pointer;
        transition: background-color var(--ss-duration-fast) var(--ss-easing-standard);
      }
      .chip:hover {
        background-color: var(--secondary-background-color, #f5f5f5);
      }
      .chip.active {
        background-color: var(--ss-accent-color);
        color: var(--text-primary-color, #ffffff);
        border-color: transparent;
      }
      .chip:focus-visible {
        outline: 2px solid var(--primary-color, #03a9f4);
        outline-offset: 2px;
      }
      .timeline {
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-4);
      }
      .day {
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-2);
      }
      .date-header {
        color: var(--secondary-text-color, #5a5a5a);
        text-transform: uppercase;
        letter-spacing: 0.5px;
      }
      .rows {
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-2);
      }
      .settlement-row {
        display: flex;
        align-items: center;
        gap: var(--ss-space-3);
        padding: var(--ss-space-3) var(--ss-space-4);
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: var(--ss-card-radius);
        background-color: var(--secondary-background-color, #f5f5f5);
        cursor: pointer;
        min-height: var(--ss-touch-min);
      }
      .settlement-row:focus-visible,
      .settlement-row:hover {
        background-color: var(--card-background-color, #ffffff);
      }
      .settlement-row:focus-visible {
        outline: 2px solid var(--primary-color, #03a9f4);
        outline-offset: 2px;
      }
      .settlement-icon {
        font-family: var(--ss-font-mono);
        font-size: 20px;
        color: var(--secondary-text-color, #5a5a5a);
      }
      .settlement-copy {
        flex: 1;
        min-width: 0;
      }
      .amount.settled {
        color: var(--ss-credit-color);
      }
      .loading {
        padding: var(--ss-space-4);
        color: var(--secondary-text-color, #5a5a5a);
      }
    `,
  ];
}

declare global {
  interface HTMLElementTagNameMap {
    'ss-ledger-view': SsLedgerView;
  }
}
