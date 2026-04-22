// <ss-expense-detail-sheet
//    .hass=${hass}
//    .config=${cfg}
//    .expense=${expense}
//    @close=${...}
// ></ss-expense-detail-sheet>
//
// Modal sheet opened from #expense/<id>. View mode renders the
// expense's per-category breakdown and per-user shares. Edit mode
// reuses <ss-add-expense-view> with prefill set to the expense —
// Save calls edit_expense and closes the sheet via ss-saved.
// Delete asks for confirmation, then calls delete_expense.

import { LitElement, html, css } from 'lit';
import { customElement, property, state } from 'lit/decorators.js';
import { baseStyles, typography } from '../styles';
import { deleteExpense as apiDeleteExpense } from '../api';
import { formatAmount } from '../util/currency';
import { formatRelativeDate } from '../util/date';
import { expenseShares, splitShares } from '../util/balances';
import type {
  Expense,
  HomeAssistant,
  Participant,
  SplitsmartConfig,
} from '../types';
import '../components/modal';
import '../components/button';
import '../components/user-avatar';
import './add-expense-view';

@customElement('ss-expense-detail-sheet')
export class SsExpenseDetailSheet extends LitElement {
  @property({ attribute: false })
  hass?: HomeAssistant;

  @property({ attribute: false })
  config: SplitsmartConfig | null = null;

  @property({ attribute: false })
  expense: Expense | null = null;

  @property({ type: String })
  locale = 'en-GB';

  @state()
  private _mode: 'view' | 'edit' = 'view';

  @state()
  private _confirmingDelete = false;

  @state()
  private _error: string | null = null;

  private _participant(userId: string): Participant | null {
    return this.config?.participants.find((p) => p.user_id === userId) ?? null;
  }

  private _close(): void {
    this.dispatchEvent(new CustomEvent('close', { bubbles: true, composed: true }));
  }

  private _startEdit(): void {
    this._mode = 'edit';
    this._error = null;
  }

  private _cancelEdit(): void {
    this._mode = 'view';
  }

  private async _delete(): Promise<void> {
    if (!this.hass || !this.expense) return;
    try {
      await apiDeleteExpense(this.hass, this.expense.id);
      this._close();
    } catch (err: unknown) {
      this._error = err instanceof Error ? err.message : String(err);
      this._confirmingDelete = false;
    }
  }

  private _renderViewMode() {
    if (!this.expense || !this.config) return html``;
    const exp = this.expense;
    const currency = this.config.home_currency;
    const payer = this._participant(exp.paid_by);

    return html`
      <div class="view">
        <div class="hero">
          <div class="ss-mono-display amount">
            ${formatAmount(exp.home_amount, currency, this.locale)}
          </div>
          <div class="ss-text-caption">
            ${formatRelativeDate(exp.date, new Date(), this.locale)} · ${exp.date}
          </div>
        </div>

        <dl class="facts">
          <div class="fact">
            <dt class="ss-text-caption">Paid by</dt>
            <dd class="ss-text-body payer">
              ${payer
                ? html`<ss-user-avatar
                      .name=${payer.display_name}
                      .userId=${payer.user_id}
                      .size=${24}
                      ?former=${!payer.active}
                    ></ss-user-avatar>
                    ${payer.display_name}${payer.active ? '' : ' (former participant)'}`
                : exp.paid_by}
            </dd>
          </div>
          ${exp.notes
            ? html`<div class="fact">
                <dt class="ss-text-caption">Notes</dt>
                <dd class="ss-text-body">${exp.notes}</dd>
              </div>`
            : ''}
        </dl>

        <h3 class="ss-text-title section-heading">Breakdown</h3>
        <ul class="allocations">
          ${exp.categories.map((a) => {
            const shares = splitShares(a.split, a.home_amount);
            return html`
              <li class="allocation">
                <div class="allocation-head">
                  <div class="ss-text-body allocation-name">${a.name}</div>
                  <div class="ss-mono-amount">
                    ${formatAmount(a.home_amount, currency, this.locale)}
                  </div>
                </div>
                <ul class="shares">
                  ${Object.entries(shares).map(([uid, amt]) => {
                    const p = this._participant(uid);
                    const name = p?.display_name ?? uid;
                    return html`
                      <li class="share">
                        <span class="ss-text-caption">${name}</span>
                        <span class="ss-mono-caption"
                          >${formatAmount(amt, currency, this.locale)}</span
                        >
                      </li>
                    `;
                  })}
                </ul>
              </li>
            `;
          })}
        </ul>

        <div class="totals-note ss-text-caption">
          Totals per person across this expense:
          ${Object.entries(expenseShares(exp))
            .map(([uid, amt]) => {
              const p = this._participant(uid);
              const name = p?.display_name ?? uid;
              return `${name} ${formatAmount(amt, currency, this.locale)}`;
            })
            .join(' · ')}
        </div>

        ${this._error
          ? html`<div class="error ss-text-body">${this._error}</div>`
          : ''}
      </div>
    `;
  }

  private _renderEditFooter() {
    return html`
      <ss-button slot="footer" variant="secondary" @click=${this._close}>Close</ss-button>
      <ss-button
        slot="footer"
        variant="destructive"
        @click=${() => (this._confirmingDelete = true)}
      >
        Delete
      </ss-button>
      <ss-button slot="footer" variant="primary" @click=${this._startEdit}>Edit</ss-button>
    `;
  }

  private _renderConfirmDelete() {
    return html`
      <div class="confirm">
        <div class="ss-text-body">
          Delete this expense? Balances will update straight away. A tombstone is
          recorded, so this can be restored from the audit log if needed.
        </div>
        <div class="confirm-actions">
          <ss-button variant="secondary" @click=${() => (this._confirmingDelete = false)}>
            Cancel
          </ss-button>
          <ss-button variant="destructive" @click=${this._delete}>Yes, delete</ss-button>
        </div>
      </div>
    `;
  }

  render() {
    const heading =
      this._mode === 'edit' ? 'Edit expense' : (this.expense?.description ?? 'Expense');
    return html`
      <ss-modal .open=${true} .heading=${heading} @close=${this._close}>
        ${this._confirmingDelete
          ? this._renderConfirmDelete()
          : this._mode === 'edit'
            ? html`
                <ss-add-expense-view
                  .hass=${this.hass}
                  .config=${this.config}
                  .prefill=${this.expense ?? undefined}
                  .locale=${this.locale}
                  @ss-saved=${this._close}
                ></ss-add-expense-view>
              `
            : this._renderViewMode()}
        ${this._mode === 'view' && !this._confirmingDelete ? this._renderEditFooter() : ''}
        ${this._mode === 'edit'
          ? html`<ss-button
              slot="footer"
              variant="secondary"
              @click=${this._cancelEdit}
            >
              Cancel edit
            </ss-button>`
          : ''}
      </ss-modal>
    `;
  }

  static styles = [
    baseStyles,
    typography,
    css`
      :host {
        display: contents;
      }
      .view {
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-4);
      }
      .hero {
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-1);
      }
      .amount {
        color: var(--primary-text-color, #1a1a1a);
      }
      .facts {
        margin: 0;
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-3);
      }
      .fact {
        display: flex;
        flex-direction: column;
        gap: 4px;
      }
      dt,
      dd {
        margin: 0;
      }
      .payer {
        display: inline-flex;
        align-items: center;
        gap: var(--ss-space-2);
      }
      .section-heading {
        margin: 0;
      }
      .allocations {
        list-style: none;
        padding: 0;
        margin: 0;
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-3);
      }
      .allocation {
        padding: var(--ss-space-3);
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 8px;
      }
      .allocation-head {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        margin-bottom: var(--ss-space-2);
      }
      .allocation-name {
        color: var(--primary-text-color, #1a1a1a);
      }
      .shares {
        list-style: none;
        padding: 0;
        margin: 0;
        display: flex;
        flex-direction: column;
        gap: 4px;
      }
      .share {
        display: flex;
        justify-content: space-between;
        color: var(--secondary-text-color, #5a5a5a);
      }
      .totals-note {
        color: var(--secondary-text-color, #5a5a5a);
      }
      .confirm {
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-4);
      }
      .confirm-actions {
        display: flex;
        gap: var(--ss-space-3);
        justify-content: flex-end;
      }
      .error {
        padding: var(--ss-space-3);
        border-radius: 8px;
        background-color: color-mix(in srgb, var(--error-color, #db4437) 14%, transparent);
        color: var(--error-color, #db4437);
      }
    `,
  ];
}

declare global {
  interface HTMLElementTagNameMap {
    'ss-expense-detail-sheet': SsExpenseDetailSheet;
  }
}
