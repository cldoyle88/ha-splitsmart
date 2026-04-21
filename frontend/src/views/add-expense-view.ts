// <ss-add-expense-view
//    .hass=${hass}
//    .config=${splitsmartConfig}
//    .prefill=${expense | undefined}
//    @ss-saved=${...}
// ></ss-add-expense-view>
//
// Full add/edit form matching SPEC §14's UI entry model. Starts in
// single-category / uniform-split mode; 'Different split per category'
// expands per-row split pickers. Live remainder gate blocks Save until
// the allocation sums to the expense total and every split is valid.
//
// Used in two contexts:
//   - As the Add view at #add (no prefill).
//   - Inside the Detail sheet's Edit mode (prefill = existing expense);
//     the view detects that via .prefill and emits ss-saved when the
//     user presses Save so the sheet can close and the root can pick up
//     the new id.

import { LitElement, html, css } from 'lit';
import { customElement, property, state } from 'lit/decorators.js';
import { baseStyles, typography } from '../styles';
import { formatAmount } from '../util/currency';
import {
  addExpense as apiAddExpense,
  editExpense as apiEditExpense,
} from '../api';
import type {
  CategoryAllocation,
  Expense,
  HomeAssistant,
  Participant,
  Split,
  SplitsmartConfig,
} from '../types';
import { isSplitValid, makeDefaultSplit } from '../components/split-picker';
import '../components/amount-input';
import '../components/category-picker';
import '../components/split-picker';
import '../components/allocation-editor';
import '../components/button';

const ROUND = (n: number) => Math.round(n * 100) / 100;

function todayIso(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

@customElement('ss-add-expense-view')
export class SsAddExpenseView extends LitElement {
  @property({ attribute: false })
  hass?: HomeAssistant;

  @property({ attribute: false })
  config: SplitsmartConfig | null = null;

  @property({ attribute: false })
  prefill?: Expense;

  @property({ type: String })
  locale = 'en-GB';

  @state()
  private _date = todayIso();

  @state()
  private _description = '';

  @state()
  private _paidBy = '';

  @state()
  private _amount = 0;

  @state()
  private _notes: string | null = null;

  /** Single-category mode: one category name + one uniform split. */
  @state()
  private _category = '';

  @state()
  private _uniformSplit: Split = { method: 'equal', shares: [] };

  /** Multi-allocation toggle. */
  @state()
  private _multiCategory = false;

  @state()
  private _allocations: { name: string; home_amount: number; _percent?: number }[] = [];

  /** 'Different split per category' override. */
  @state()
  private _perCategorySplit = false;

  @state()
  private _perCategorySplits: Record<string, Split> = {};

  @state()
  private _saving = false;

  @state()
  private _error: string | null = null;

  private _activeParticipants(): Participant[] {
    return (this.config?.participants ?? []).filter((p) => p.active);
  }

  protected willUpdate(changed: Map<string, unknown>): void {
    if (changed.has('config') && this.config && this._uniformSplit.shares.length === 0) {
      this._uniformSplit = makeDefaultSplit('equal', this._activeParticipants());
      if (!this._paidBy) this._paidBy = this.config.current_user_id;
      if (!this._category && this.config.categories.length > 0) {
        this._category = this.config.categories[0]!;
      }
    }
    if (changed.has('prefill') && this.prefill) {
      this._hydrateFromPrefill(this.prefill);
    }
  }

  private _hydrateFromPrefill(exp: Expense): void {
    this._date = exp.date;
    this._description = exp.description;
    this._paidBy = exp.paid_by;
    this._amount = exp.home_amount;
    this._notes = exp.notes;

    const allocs = exp.categories ?? [];
    if (allocs.length <= 1) {
      this._multiCategory = false;
      this._category = allocs[0]?.name ?? this._category;
      this._uniformSplit = allocs[0]?.split ?? this._uniformSplit;
    } else {
      this._multiCategory = true;
      this._allocations = allocs.map((a) => ({
        name: a.name,
        home_amount: a.home_amount,
      }));
      const firstSplit = JSON.stringify(allocs[0]!.split);
      const allSame = allocs.every((a) => JSON.stringify(a.split) === firstSplit);
      this._perCategorySplit = !allSame;
      if (allSame) {
        this._uniformSplit = allocs[0]!.split;
      } else {
        this._perCategorySplits = Object.fromEntries(
          allocs.map((a) => [a.name, a.split]),
        );
      }
    }
  }

  private _expenseTotal(): number {
    if (!this._multiCategory) return this._amount;
    return ROUND(this._allocations.reduce((acc, r) => acc + r.home_amount, 0));
  }

  private _allocationValid(): boolean {
    if (!this._multiCategory) return this._amount > 0;
    if (this._allocations.length === 0) return false;
    const sum = this._allocations.reduce((acc, r) => acc + r.home_amount, 0);
    return Math.abs(sum - this._amount) < 0.01 && this._allocations.every((r) => r.name);
  }

  private _splitsValid(): boolean {
    if (!this._multiCategory) {
      return isSplitValid(this._uniformSplit, this._amount);
    }
    if (!this._perCategorySplit) {
      return this._allocations.every((a) =>
        isSplitValid(this._uniformSplit, a.home_amount),
      );
    }
    return this._allocations.every((a) =>
      isSplitValid(this._perCategorySplits[a.name] ?? this._uniformSplit, a.home_amount),
    );
  }

  private _isValid(): boolean {
    return (
      this._date.length === 10 &&
      this._description.trim().length > 0 &&
      this._paidBy.length > 0 &&
      this._amount > 0 &&
      this._allocationValid() &&
      this._splitsValid()
    );
  }

  private _buildCategories(): CategoryAllocation[] {
    if (!this._multiCategory) {
      return [
        {
          name: this._category,
          home_amount: this._amount,
          split: this._uniformSplit,
        },
      ];
    }
    return this._allocations.map((a) => ({
      name: a.name,
      home_amount: a.home_amount,
      split: this._perCategorySplit
        ? this._perCategorySplits[a.name] ?? this._uniformSplit
        : this._uniformSplit,
    }));
  }

  private async _save(): Promise<void> {
    if (!this.hass || !this._isValid() || this._saving) return;
    this._saving = true;
    this._error = null;
    try {
      const categories = this._buildCategories();
      if (this.prefill) {
        await apiEditExpense(this.hass, {
          id: this.prefill.id,
          date: this._date,
          description: this._description.trim(),
          paid_by: this._paidBy,
          amount: this._amount,
          categories,
          notes: this._notes,
        });
      } else {
        await apiAddExpense(this.hass, {
          date: this._date,
          description: this._description.trim(),
          paid_by: this._paidBy,
          amount: this._amount,
          categories,
          notes: this._notes,
        });
      }
      this.dispatchEvent(
        new CustomEvent('ss-saved', { bubbles: true, composed: true }),
      );
      if (!this.prefill) {
        this.dispatchEvent(
          new CustomEvent('ss-navigate', {
            detail: { route: 'ledger' },
            bubbles: true,
            composed: true,
          }),
        );
      }
    } catch (err: unknown) {
      this._error = err instanceof Error ? err.message : String(err);
    } finally {
      this._saving = false;
    }
  }

  private _cancel(): void {
    this.dispatchEvent(
      new CustomEvent('ss-navigate', {
        detail: { route: 'home' },
        bubbles: true,
        composed: true,
      }),
    );
  }

  private _renderSingleCategory() {
    return html`
      <div class="field">
        <label class="ss-text-caption">Category</label>
        <ss-category-picker
          .options=${this.config?.categories ?? []}
          .value=${this._category}
          @ss-change=${(e: CustomEvent) => (this._category = e.detail.value)}
        ></ss-category-picker>
      </div>
    `;
  }

  private _renderMultiAllocation() {
    return html`
      <div class="field">
        <label class="ss-text-caption">Categories</label>
        <ss-allocation-editor
          .categories=${this.config?.categories ?? []}
          .total=${this._amount}
          .value=${this._allocations}
          .currency=${this.config?.home_currency ?? 'GBP'}
          @ss-change=${(e: CustomEvent) => (this._allocations = e.detail.value)}
        ></ss-allocation-editor>
      </div>
    `;
  }

  private _renderSplitSection() {
    const active = this._activeParticipants();
    const singleSplit = !this._multiCategory || !this._perCategorySplit;
    if (singleSplit) {
      const allocationAmount = this._multiCategory
        ? this._expenseTotal()
        : this._amount;
      return html`
        <div class="field">
          <label class="ss-text-caption">Split</label>
          <ss-split-picker
            .participants=${active}
            .allocationAmount=${allocationAmount}
            .value=${this._uniformSplit}
            .currency=${this.config?.home_currency ?? 'GBP'}
            @ss-change=${(e: CustomEvent) => (this._uniformSplit = e.detail.value)}
          ></ss-split-picker>
        </div>
      `;
    }
    return html`
      <div class="field">
        <label class="ss-text-caption">Split per category</label>
        ${this._allocations.map(
          (a) => html`
            <div class="per-cat">
              <div class="ss-text-body per-cat-title">
                ${a.name}
                <span class="ss-mono-amount muted">
                  ${formatAmount(a.home_amount, this.config?.home_currency ?? 'GBP')}
                </span>
              </div>
              <ss-split-picker
                .participants=${active}
                .allocationAmount=${a.home_amount}
                .value=${this._perCategorySplits[a.name] ?? this._uniformSplit}
                .currency=${this.config?.home_currency ?? 'GBP'}
                @ss-change=${(e: CustomEvent) =>
                  (this._perCategorySplits = {
                    ...this._perCategorySplits,
                    [a.name]: e.detail.value,
                  })}
              ></ss-split-picker>
            </div>
          `,
        )}
      </div>
    `;
  }

  render() {
    if (!this.config) return html`<div class="ss-text-caption loading">Loading…</div>`;
    const active = this._activeParticipants();

    return html`
      <div class="container">
        <header class="page-header">
          <ss-button variant="secondary" @click=${this._cancel}>Cancel</ss-button>
          <div class="ss-text-title title">
            ${this.prefill ? 'Edit expense' : 'Add expense'}
          </div>
          <ss-button
            variant="primary"
            ?disabled=${!this._isValid() || this._saving}
            @click=${this._save}
          >
            ${this._saving ? 'Saving…' : 'Save'}
          </ss-button>
        </header>

        ${this._error
          ? html`<div class="error ss-text-body">${this._error}</div>`
          : ''}

        <div class="row">
          <div class="field">
            <label class="ss-text-caption" for="date">Date</label>
            <input
              id="date"
              class="ss-text-body text-input ss-focus-ring"
              type="date"
              .value=${this._date}
              @input=${(e: Event) =>
                (this._date = (e.target as HTMLInputElement).value)}
            />
          </div>
          <div class="field">
            <label class="ss-text-caption">Amount</label>
            <ss-amount-input
              .value=${this._amount}
              .currency=${this.config.home_currency}
              @ss-change=${(e: CustomEvent) =>
                (this._amount = Number(e.detail.value) || 0)}
            ></ss-amount-input>
          </div>
        </div>

        <div class="field">
          <label class="ss-text-caption" for="description">Description</label>
          <input
            id="description"
            class="ss-text-body text-input ss-focus-ring"
            type="text"
            maxlength="200"
            placeholder="Tesco shop"
            .value=${this._description}
            @input=${(e: Event) =>
              (this._description = (e.target as HTMLInputElement).value)}
          />
        </div>

        <div class="field">
          <label class="ss-text-caption" for="paid-by">Paid by</label>
          <select
            id="paid-by"
            class="ss-text-body text-input ss-focus-ring"
            .value=${this._paidBy}
            @change=${(e: Event) =>
              (this._paidBy = (e.target as HTMLSelectElement).value)}
          >
            ${active.map(
              (p) => html`<option value=${p.user_id} ?selected=${p.user_id === this._paidBy}>
                ${p.display_name}
              </option>`,
            )}
          </select>
        </div>

        <label class="toggle ss-text-body">
          <input
            type="checkbox"
            .checked=${this._multiCategory}
            @change=${(e: Event) =>
              (this._multiCategory = (e.target as HTMLInputElement).checked)}
          />
          Split across categories
        </label>

        ${this._multiCategory ? this._renderMultiAllocation() : this._renderSingleCategory()}

        ${this._multiCategory
          ? html`
              <label class="toggle ss-text-body">
                <input
                  type="checkbox"
                  .checked=${this._perCategorySplit}
                  @change=${(e: Event) =>
                    (this._perCategorySplit = (e.target as HTMLInputElement).checked)}
                />
                Different split per category
              </label>
            `
          : ''}

        ${this._renderSplitSection()}

        <div class="field">
          <label class="ss-text-caption" for="notes">Notes</label>
          <textarea
            id="notes"
            class="ss-text-body text-input ss-focus-ring"
            rows="2"
            placeholder="Optional"
            .value=${this._notes ?? ''}
            @input=${(e: Event) => {
              const val = (e.target as HTMLTextAreaElement).value;
              this._notes = val ? val : null;
            }}
          ></textarea>
        </div>
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
      .page-header .title {
        flex: 1;
      }
      .field {
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-2);
      }
      .field label {
        color: var(--secondary-text-color, #5a5a5a);
      }
      .row {
        display: grid;
        grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
        gap: var(--ss-space-3);
      }
      .text-input {
        padding: var(--ss-space-2) var(--ss-space-3);
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 8px;
        background-color: var(--card-background-color, #ffffff);
        color: var(--primary-text-color, #1a1a1a);
        font-family: var(--ss-font-sans);
        min-height: var(--ss-touch-min);
      }
      .text-input:focus-visible {
        outline: 2px solid var(--primary-color, #03a9f4);
        outline-offset: 2px;
      }
      .toggle {
        display: flex;
        align-items: center;
        gap: var(--ss-space-2);
        color: var(--primary-text-color, #1a1a1a);
        cursor: pointer;
      }
      .per-cat {
        padding: var(--ss-space-3);
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 8px;
        margin-bottom: var(--ss-space-2);
      }
      .per-cat-title {
        display: flex;
        justify-content: space-between;
        margin-bottom: var(--ss-space-2);
      }
      .muted {
        color: var(--secondary-text-color, #5a5a5a);
      }
      .error {
        padding: var(--ss-space-3);
        border-radius: 8px;
        background-color: color-mix(in srgb, var(--error-color, #db4437) 14%, transparent);
        color: var(--error-color, #db4437);
      }
      .loading {
        padding: var(--ss-space-4);
      }
    `,
  ];
}

declare global {
  interface HTMLElementTagNameMap {
    'ss-add-expense-view': SsAddExpenseView;
  }
}
