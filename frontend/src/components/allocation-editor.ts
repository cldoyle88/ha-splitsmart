// <ss-allocation-editor
//    .categories=${['Groceries', ...]}
//    .total=${82.40}
//    .value=${[{name, home_amount}, ...]}
//    mode="amount" | "percent"
//    currency="GBP"
//    @ss-change=${...}>
//
// Multi-row editor for multi-category expenses. 'amount' mode lets
// users type home-currency numbers; 'percent' mode types percentages
// and the editor computes amounts (last row absorbs rounding drift).
// Emits ss-change with {value, valid, remainder} every edit so the
// parent form can show the live remainder indicator and gate Save.

import { LitElement, html, css } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { baseStyles, typography } from '../styles';
import { formatAmount, parseAmount } from '../util/currency';
import './category-picker';
import './amount-input';
import './button';
import './icon';

export type AllocMode = 'amount' | 'percent';

export interface AllocationRow {
  name: string;
  home_amount: number;
  /** Internal: typed percent when mode='percent'. Not serialised. */
  _percent?: number;
}

const ROUND = (n: number) => Math.round(n * 100) / 100;

@customElement('ss-allocation-editor')
export class SsAllocationEditor extends LitElement {
  @property({ attribute: false })
  categories: string[] = [];

  @property({ type: Number })
  total = 0;

  @property({ attribute: false })
  value: AllocationRow[] = [];

  @property({ type: String })
  mode: AllocMode = 'amount';

  @property({ type: String })
  currency = 'GBP';

  private _setMode(next: AllocMode): void {
    if (next === this.mode) return;
    this.mode = next;
    // Reset percents from amounts when switching to percent mode.
    if (next === 'percent' && this.total > 0) {
      this.value = this.value.map((r) => ({
        ...r,
        _percent: ROUND((r.home_amount / this.total) * 100),
      }));
    }
    this._emit();
  }

  private _updateRow(index: number, patch: Partial<AllocationRow>): void {
    const next = this.value.map((r, i) => (i === index ? { ...r, ...patch } : r));
    if (this.mode === 'percent') {
      this._recomputeAmountsFromPercents(next);
    }
    this.value = next;
    this._emit();
  }

  private _recomputeAmountsFromPercents(rows: AllocationRow[]): void {
    if (this.total <= 0) return;
    let runningAmount = 0;
    for (let i = 0; i < rows.length - 1; i++) {
      const pct = Number(rows[i]!._percent ?? 0);
      const amt = ROUND((this.total * pct) / 100);
      rows[i]!.home_amount = amt;
      runningAmount += amt;
    }
    // Last row absorbs rounding drift.
    if (rows.length > 0) {
      rows[rows.length - 1]!.home_amount = ROUND(this.total - runningAmount);
    }
  }

  private _addRow(): void {
    const used = new Set(this.value.map((r) => r.name));
    const next = this.categories.find((c) => !used.has(c)) ?? this.categories[0] ?? '';
    const rows: AllocationRow[] = [...this.value, { name: next, home_amount: 0, _percent: 0 }];
    this.value = rows;
    this._emit();
  }

  private _removeRow(index: number): void {
    this.value = this.value.filter((_, i) => i !== index);
    this._emit();
  }

  private _sum(): number {
    return ROUND(this.value.reduce((acc, r) => acc + (Number(r.home_amount) || 0), 0));
  }

  private _emit(): void {
    const sum = this._sum();
    const remainder = ROUND(this.total - sum);
    const valid =
      this.value.length > 0 &&
      Math.abs(remainder) < 0.01 &&
      this.value.every((r) => r.name && r.home_amount >= 0);
    this.dispatchEvent(
      new CustomEvent('ss-change', {
        detail: { value: this.value, valid, remainder },
        bubbles: true,
        composed: true,
      }),
    );
  }

  render() {
    const sum = this._sum();
    const remainder = ROUND(this.total - sum);
    const remainderState =
      Math.abs(remainder) < 0.01 ? 'ok' : remainder > 0 ? 'under' : 'over';

    return html`
      <div class="container">
        <div class="mode-row">
          <div class="ss-text-caption label">Enter as</div>
          <div class="mode-toggle">
            <button
              class="mode ${this.mode === 'amount' ? 'active' : ''} ss-focus-ring ss-text-button"
              type="button"
              @click=${() => this._setMode('amount')}
            >
              Amount
            </button>
            <button
              class="mode ${this.mode === 'percent' ? 'active' : ''} ss-focus-ring ss-text-button"
              type="button"
              @click=${() => this._setMode('percent')}
            >
              %
            </button>
          </div>
        </div>

        <ul class="rows">
          ${this.value.map(
            (row, i) => html`
              <li class="row">
                <ss-category-picker
                  class="cat"
                  .options=${this.categories}
                  .value=${row.name}
                  @ss-change=${(e: CustomEvent) =>
                    this._updateRow(i, { name: e.detail.value })}
                ></ss-category-picker>
                ${this.mode === 'amount'
                  ? html`
                      <ss-amount-input
                        class="amt"
                        .value=${row.home_amount}
                        .currency=${this.currency}
                        @ss-change=${(e: CustomEvent) =>
                          this._updateRow(i, {
                            home_amount: Number(e.detail.value) || 0,
                          })}
                      ></ss-amount-input>
                    `
                  : html`
                      <div class="pct-wrap">
                        <input
                          class="pct-input ss-mono-amount ss-focus-ring"
                          type="text"
                          inputmode="decimal"
                          .value=${String(row._percent ?? 0)}
                          @input=${(e: Event) =>
                            this._updateRow(i, {
                              _percent: parseAmount((e.target as HTMLInputElement).value) ?? 0,
                            })}
                        />
                        <span class="ss-text-caption">%</span>
                        <span class="ss-text-caption computed"
                          >= ${formatAmount(row.home_amount, this.currency)}</span
                        >
                      </div>
                    `}
                <button
                  class="remove ss-focus-ring"
                  type="button"
                  aria-label="Remove row"
                  @click=${() => this._removeRow(i)}
                >
                  <ss-icon name="mdi:close" .size=${18}></ss-icon>
                </button>
              </li>
            `,
          )}
        </ul>

        <ss-button variant="secondary" @click=${() => this._addRow()}>
          + Add category
        </ss-button>

        <div class="remainder state-${remainderState}">
          <span class="ss-text-caption">Total</span>
          <span class="ss-mono-amount">${formatAmount(sum, this.currency)}</span>
          <span class="sep"></span>
          <span class="ss-text-caption"
            >${Math.abs(remainder) < 0.01
              ? 'Balanced ✓'
              : remainder > 0
                ? `${formatAmount(remainder, this.currency)} remaining`
                : `${formatAmount(Math.abs(remainder), this.currency)} over`}</span
          >
        </div>
      </div>
    `;
  }

  static styles = [
    baseStyles,
    typography,
    css`
      :host {
        display: block;
      }
      .container {
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-3);
      }
      .mode-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--ss-space-3);
      }
      .label {
        color: var(--secondary-text-color, #5a5a5a);
      }
      .mode-toggle {
        display: flex;
        gap: var(--ss-space-1);
      }
      .mode {
        min-height: 36px;
        padding: var(--ss-space-2) var(--ss-space-3);
        border-radius: 999px;
        border: 1px solid var(--divider-color, #e0e0e0);
        background-color: var(--card-background-color, #ffffff);
        cursor: pointer;
      }
      .mode.active {
        background-color: var(--ss-accent-color);
        color: var(--text-primary-color, #ffffff);
        border-color: transparent;
      }
      .rows {
        list-style: none;
        padding: 0;
        margin: 0;
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-2);
      }
      .row {
        display: grid;
        grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr) auto;
        gap: var(--ss-space-2);
        align-items: center;
      }
      .pct-wrap {
        display: flex;
        align-items: center;
        gap: var(--ss-space-2);
        padding: var(--ss-space-2) var(--ss-space-3);
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 8px;
        background-color: var(--card-background-color, #ffffff);
      }
      .pct-input {
        width: 60px;
        border: none;
        outline: none;
        background: transparent;
        color: var(--primary-text-color, #1a1a1a);
        font-variant-numeric: tabular-nums;
        text-align: right;
      }
      .computed {
        color: var(--secondary-text-color, #5a5a5a);
      }
      .remove {
        min-width: var(--ss-touch-min);
        min-height: var(--ss-touch-min);
        border: none;
        background: transparent;
        color: var(--secondary-text-color, #5a5a5a);
        cursor: pointer;
        border-radius: 50%;
      }
      .remove:hover {
        background-color: var(--secondary-background-color, #f5f5f5);
      }
      .remainder {
        display: flex;
        align-items: center;
        gap: var(--ss-space-3);
        padding: var(--ss-space-2) var(--ss-space-3);
        border-radius: 8px;
        background-color: var(--secondary-background-color, #f5f5f5);
      }
      .remainder .sep {
        flex: 1;
      }
      .remainder.state-ok {
        background-color: color-mix(in srgb, var(--ss-credit-color) 15%, transparent);
      }
      .remainder.state-under,
      .remainder.state-over {
        background-color: color-mix(in srgb, var(--warning-color, #ffa600) 15%, transparent);
      }
    `,
  ];
}

declare global {
  interface HTMLElementTagNameMap {
    'ss-allocation-editor': SsAllocationEditor;
  }
}
