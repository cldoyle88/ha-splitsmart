// <ss-settlement-detail-sheet
//    .hass=${hass}
//    .config=${cfg}
//    .settlement=${settlement}
//    @close=${...}
// ></ss-settlement-detail-sheet>
//
// Modal sheet opened by the router when route is settlement/<id>.
// Smaller than the expense detail because settlements don't have
// categories or per-user splits — just from/to/amount/date/notes.
// Edit mode reuses <ss-settle-up-view> with prefill.

import { LitElement, html, css } from 'lit';
import { customElement, property, state } from 'lit/decorators.js';
import { baseStyles, typography } from '../styles';
import { deleteSettlement as apiDeleteSettlement } from '../api';
import { formatAmount } from '../util/currency';
import { formatRelativeDate } from '../util/date';
import type {
  Expense,
  HomeAssistant,
  Participant,
  Settlement,
  SplitsmartConfig,
} from '../types';
import '../components/modal';
import '../components/button';
import '../components/user-avatar';
import './settle-up-view';

@customElement('ss-settlement-detail-sheet')
export class SsSettlementDetailSheet extends LitElement {
  @property({ attribute: false })
  hass?: HomeAssistant;

  @property({ attribute: false })
  config: SplitsmartConfig | null = null;

  @property({ attribute: false })
  settlement: Settlement | null = null;

  /** Full expense/settlement lists for the edit form's suggestion logic. */
  @property({ attribute: false })
  expenses: Expense[] = [];

  @property({ attribute: false })
  settlements: Settlement[] = [];

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

  private async _delete(): Promise<void> {
    if (!this.hass || !this.settlement) return;
    try {
      await apiDeleteSettlement(this.hass, this.settlement.id);
      this._close();
    } catch (err: unknown) {
      this._error = err instanceof Error ? err.message : String(err);
      this._confirmingDelete = false;
    }
  }

  private _renderViewMode() {
    if (!this.settlement || !this.config) return html``;
    const st = this.settlement;
    const currency = this.config.home_currency;
    const fromUser = this._participant(st.from_user);
    const toUser = this._participant(st.to_user);

    return html`
      <div class="view">
        <div class="hero">
          <div class="ss-mono-display amount">
            ${formatAmount(st.home_amount, currency, this.locale)}
          </div>
          <div class="ss-text-caption">
            ${formatRelativeDate(st.date, new Date(), this.locale)} · ${st.date}
          </div>
        </div>

        <div class="flow">
          ${fromUser
            ? html`
                <div class="person">
                  <ss-user-avatar
                    .name=${fromUser.display_name}
                    .userId=${fromUser.user_id}
                    .size=${32}
                    ?former=${!fromUser.active}
                  ></ss-user-avatar>
                  <div class="ss-text-body">
                    ${fromUser.display_name}${fromUser.active
                      ? ''
                      : ' (former participant)'}
                  </div>
                </div>
              `
            : html`<div class="person">${st.from_user}</div>`}
          <div class="arrow ss-mono-display">→</div>
          ${toUser
            ? html`
                <div class="person">
                  <ss-user-avatar
                    .name=${toUser.display_name}
                    .userId=${toUser.user_id}
                    .size=${32}
                    ?former=${!toUser.active}
                  ></ss-user-avatar>
                  <div class="ss-text-body">
                    ${toUser.display_name}${toUser.active
                      ? ''
                      : ' (former participant)'}
                  </div>
                </div>
              `
            : html`<div class="person">${st.to_user}</div>`}
        </div>

        ${st.notes
          ? html`<dl class="facts">
              <div class="fact">
                <dt class="ss-text-caption">Notes</dt>
                <dd class="ss-text-body">${st.notes}</dd>
              </div>
            </dl>`
          : ''}

        ${this._error
          ? html`<div class="error ss-text-body">${this._error}</div>`
          : ''}
      </div>
    `;
  }

  private _renderConfirmDelete() {
    return html`
      <div class="confirm">
        <div class="ss-text-body">
          Delete this settlement? Balances will update straight away. A
          tombstone is recorded, so this can be restored from the audit log if
          needed.
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
    const heading = this._mode === 'edit' ? 'Edit settlement' : 'Settlement';
    return html`
      <ss-modal .open=${true} .heading=${heading} @close=${this._close}>
        ${this._confirmingDelete
          ? this._renderConfirmDelete()
          : this._mode === 'edit'
            ? html`
                <ss-settle-up-view
                  .hass=${this.hass}
                  .config=${this.config}
                  .expenses=${this.expenses}
                  .settlements=${this.settlements}
                  .prefill=${this.settlement ?? undefined}
                  .locale=${this.locale}
                  @ss-saved=${this._close}
                ></ss-settle-up-view>
              `
            : this._renderViewMode()}
        ${this._mode === 'view' && !this._confirmingDelete
          ? html`
              <ss-button slot="footer" variant="secondary" @click=${this._close}>
                Close
              </ss-button>
              <ss-button
                slot="footer"
                variant="destructive"
                @click=${() => (this._confirmingDelete = true)}
              >
                Delete
              </ss-button>
              <ss-button
                slot="footer"
                variant="primary"
                @click=${() => (this._mode = 'edit')}
              >
                Edit
              </ss-button>
            `
          : ''}
        ${this._mode === 'edit' && !this._confirmingDelete
          ? html`
              <ss-button
                slot="footer"
                variant="secondary"
                @click=${() => (this._mode = 'view')}
              >
                Cancel edit
              </ss-button>
            `
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
        color: var(--ss-credit-color);
      }
      .flow {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
        gap: var(--ss-space-3);
        align-items: center;
      }
      .person {
        display: flex;
        align-items: center;
        gap: var(--ss-space-2);
      }
      .arrow {
        color: var(--secondary-text-color, #5a5a5a);
        font-size: 24px;
        text-align: center;
      }
      .facts {
        margin: 0;
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
    'ss-settlement-detail-sheet': SsSettlementDetailSheet;
  }
}
