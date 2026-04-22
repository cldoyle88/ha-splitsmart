// <ss-settle-up-view
//    .hass=${hass}
//    .config=${cfg}
//    .expenses=${expenses}
//    .settlements=${settlements}
//    .prefill=${settlement | undefined}
// ></ss-settle-up-view>
//
// Form to record a payment. Pre-fills the amount from the current
// pairwise debt when (from, to) is set and no amount has been typed
// yet. Used both at #settle and inside the Settlement detail sheet's
// edit mode (step 15), distinguished by .prefill.

import { LitElement, html, css } from 'lit';
import { customElement, property, state } from 'lit/decorators.js';
import { baseStyles, typography } from '../styles';
import {
  addSettlement as apiAddSettlement,
  editSettlement as apiEditSettlement,
} from '../api';
import { formatAmount } from '../util/currency';
import { computePairwise } from '../util/balances';
import type {
  Expense,
  HomeAssistant,
  Participant,
  Settlement,
  SplitsmartConfig,
} from '../types';
import '../components/amount-input';
import '../components/button';

function todayIso(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

@customElement('ss-settle-up-view')
export class SsSettleUpView extends LitElement {
  @property({ attribute: false })
  hass?: HomeAssistant;

  @property({ attribute: false })
  config: SplitsmartConfig | null = null;

  @property({ attribute: false })
  expenses: Expense[] = [];

  @property({ attribute: false })
  settlements: Settlement[] = [];

  @property({ attribute: false })
  prefill?: Settlement;

  @property({ type: String })
  locale = 'en-GB';

  @state()
  private _date = todayIso();

  @state()
  private _fromUser = '';

  @state()
  private _toUser = '';

  @state()
  private _amount = 0;

  @state()
  private _amountTouched = false;

  @state()
  private _notes: string | null = null;

  @state()
  private _saving = false;

  @state()
  private _error: string | null = null;

  private _activeParticipants(): Participant[] {
    return (this.config?.participants ?? []).filter((p) => p.active);
  }

  protected willUpdate(changed: Map<string, unknown>): void {
    if (changed.has('config') && this.config && !this._fromUser) {
      const active = this._activeParticipants();
      this._fromUser = this.config.current_user_id;
      this._toUser = active.find((p) => p.user_id !== this._fromUser)?.user_id ?? '';
    }
    if (changed.has('prefill') && this.prefill) {
      this._date = this.prefill.date;
      this._fromUser = this.prefill.from_user;
      this._toUser = this.prefill.to_user;
      this._amount = this.prefill.home_amount;
      this._amountTouched = true;
      this._notes = this.prefill.notes;
    }
  }

  private _suggestedAmount(): number {
    if (this.prefill) return this.prefill.home_amount;
    if (!this._fromUser || !this._toUser) return 0;
    const pw = computePairwise(this.expenses, this.settlements);
    return Math.round((pw[this._fromUser]?.[this._toUser] ?? 0) * 100) / 100;
  }

  private _maybeAutofillAmount(): void {
    if (this._amountTouched) return;
    this._amount = this._suggestedAmount();
  }

  private _swap(): void {
    const prev = this._fromUser;
    this._fromUser = this._toUser;
    this._toUser = prev;
    this._maybeAutofillAmount();
  }

  private _isValid(): boolean {
    return (
      this._date.length === 10 &&
      this._fromUser.length > 0 &&
      this._toUser.length > 0 &&
      this._fromUser !== this._toUser &&
      this._amount > 0
    );
  }

  private async _save(): Promise<void> {
    if (!this.hass || this._saving || !this._isValid()) return;
    this._saving = true;
    this._error = null;
    try {
      if (this.prefill) {
        await apiEditSettlement(this.hass, {
          id: this.prefill.id,
          date: this._date,
          from_user: this._fromUser,
          to_user: this._toUser,
          amount: this._amount,
          notes: this._notes,
        });
      } else {
        await apiAddSettlement(this.hass, {
          date: this._date,
          from_user: this._fromUser,
          to_user: this._toUser,
          amount: this._amount,
          notes: this._notes,
        });
      }
      this.dispatchEvent(
        new CustomEvent('ss-saved', { bubbles: true, composed: true }),
      );
      if (!this.prefill) {
        this.dispatchEvent(
          new CustomEvent('ss-navigate', {
            detail: { route: 'home' },
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

  render() {
    if (!this.config) return html`<div class="ss-text-caption loading">Loading…</div>`;
    const active = this._activeParticipants();
    const currency = this.config.home_currency;
    const suggested = this._suggestedAmount();
    const notSameUser = this._fromUser !== this._toUser;

    return html`
      <div class="container">
        <header class="page-header">
          <ss-button variant="secondary" @click=${this._cancel}>Cancel</ss-button>
          <div class="ss-text-title title">
            ${this.prefill ? 'Edit settlement' : 'Settle up'}
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

        <div class="pair">
          <div class="field">
            <label class="ss-text-caption" for="from">From</label>
            <select
              id="from"
              class="ss-text-body text-input ss-focus-ring"
              .value=${this._fromUser}
              @change=${(e: Event) => {
                this._fromUser = (e.target as HTMLSelectElement).value;
                this._maybeAutofillAmount();
              }}
            >
              ${active.map(
                (p) => html`<option value=${p.user_id} ?selected=${p.user_id === this._fromUser}>
                  ${p.display_name}
                </option>`,
              )}
            </select>
          </div>
          <button
            class="swap ss-focus-ring"
            type="button"
            aria-label="Swap from and to"
            @click=${this._swap}
          >
            ⇄
          </button>
          <div class="field">
            <label class="ss-text-caption" for="to">To</label>
            <select
              id="to"
              class="ss-text-body text-input ss-focus-ring"
              .value=${this._toUser}
              @change=${(e: Event) => {
                this._toUser = (e.target as HTMLSelectElement).value;
                this._maybeAutofillAmount();
              }}
            >
              ${active.map(
                (p) => html`<option value=${p.user_id} ?selected=${p.user_id === this._toUser}>
                  ${p.display_name}
                </option>`,
              )}
            </select>
          </div>
        </div>

        ${!notSameUser
          ? html`<div class="warn ss-text-caption">From and To must be different people.</div>`
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
              .currency=${currency}
              @ss-change=${(e: CustomEvent) => {
                this._amount = Number(e.detail.value) || 0;
                this._amountTouched = true;
              }}
            ></ss-amount-input>
            ${suggested > 0 && !this._amountTouched
              ? html`<div class="suggest ss-text-caption">
                  Suggested: ${formatAmount(suggested, currency, this.locale)}
                </div>`
              : ''}
          </div>
        </div>

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
      .pair {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
        gap: var(--ss-space-3);
        align-items: end;
      }
      .swap {
        min-height: var(--ss-touch-min);
        min-width: var(--ss-touch-min);
        border: 1px solid var(--divider-color, #e0e0e0);
        background: var(--card-background-color, #ffffff);
        color: var(--primary-text-color, #1a1a1a);
        border-radius: 50%;
        font-size: 20px;
        cursor: pointer;
      }
      .swap:focus-visible {
        outline: 2px solid var(--primary-color, #03a9f4);
        outline-offset: 2px;
      }
      .field {
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-2);
      }
      .field label {
        color: var(--secondary-text-color, #5a5a5a);
      }
      .text-input {
        padding: var(--ss-space-2) var(--ss-space-3);
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 8px;
        background-color: var(--card-background-color, #ffffff);
        color: var(--primary-text-color, #1a1a1a);
        min-height: var(--ss-touch-min);
      }
      .text-input:focus-visible {
        outline: 2px solid var(--primary-color, #03a9f4);
        outline-offset: 2px;
      }
      .row {
        display: grid;
        grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
        gap: var(--ss-space-3);
      }
      .suggest {
        color: var(--secondary-text-color, #5a5a5a);
      }
      .warn {
        color: var(--warning-color, #ffa600);
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
    'ss-settle-up-view': SsSettleUpView;
  }
}
