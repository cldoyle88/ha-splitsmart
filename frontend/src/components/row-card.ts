// <ss-row-card .expense=${...} .participants=${...} home-currency="GBP">
//
// Single expense row used in the Ledger list and on Home as the "last
// expense" tile (variant='compact'). Displays description + relative
// date on the left, amount + paid-by avatar on the right. Click to
// open the Detail sheet.

import { LitElement, html, css } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { baseStyles, typography } from '../styles';
import { formatAmount } from '../util/currency';
import { formatRelativeDate } from '../util/date';
import type { Expense, Participant } from '../types';
import './user-avatar';

export type SsRowCardVariant = 'default' | 'compact';

@customElement('ss-row-card')
export class SsRowCard extends LitElement {
  @property({ attribute: false })
  expense!: Expense;

  @property({ attribute: false })
  participants: Participant[] = [];

  @property({ type: String, attribute: 'home-currency' })
  homeCurrency = 'GBP';

  @property({ type: String })
  locale = 'en-GB';

  @property({ type: String })
  variant: SsRowCardVariant = 'default';

  private _payer(): Participant | null {
    return this.participants.find((p) => p.user_id === this.expense.paid_by) ?? null;
  }

  private _categoriesLabel(): string {
    const names = (this.expense.categories ?? []).map((c) => c.name);
    if (names.length === 0) return '';
    if (names.length === 1) return names[0]!;
    return `${names[0]} +${names.length - 1}`;
  }

  private _onActivate(e: Event) {
    if (e instanceof KeyboardEvent && e.key !== 'Enter' && e.key !== ' ') return;
    e.preventDefault();
    this.dispatchEvent(
      new CustomEvent('ss-open-detail', {
        detail: { expense_id: this.expense.id },
        bubbles: true,
        composed: true,
      }),
    );
  }

  render() {
    const payer = this._payer();
    const date = formatRelativeDate(this.expense.date, new Date(), this.locale);
    const amount = formatAmount(this.expense.home_amount, this.homeCurrency, this.locale);
    const subtitle = [date, this._categoriesLabel()].filter(Boolean).join(' · ');

    return html`
      <div
        class="row variant-${this.variant} ss-focus-ring"
        role="button"
        tabindex="0"
        @click=${this._onActivate}
        @keydown=${this._onActivate}
      >
        <div class="main">
          <div class="ss-text-body description">${this.expense.description}</div>
          <div class="ss-text-caption subtitle">${subtitle}</div>
        </div>
        <div class="right">
          <div class="ss-mono-amount amount">${amount}</div>
          ${payer
            ? html`<ss-user-avatar
                .name=${payer.display_name}
                .userId=${payer.user_id}
                .size=${24}
                ?former=${!payer.active}
              ></ss-user-avatar>`
            : ''}
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
      .row {
        display: flex;
        align-items: center;
        gap: var(--ss-space-3);
        padding: var(--ss-space-3) var(--ss-space-4);
        border-radius: var(--ss-card-radius);
        background-color: var(--card-background-color, #ffffff);
        border: 1px solid var(--divider-color, #e0e0e0);
        cursor: pointer;
        min-height: var(--ss-touch-min);
        transition: background-color var(--ss-duration-fast) var(--ss-easing-standard);
      }
      .row:hover,
      .row:focus-visible {
        background-color: var(--secondary-background-color, #f5f5f5);
      }
      .row:focus-visible {
        outline: 2px solid var(--primary-color, #03a9f4);
        outline-offset: 2px;
      }
      .variant-compact {
        padding: var(--ss-space-2) var(--ss-space-3);
      }
      .main {
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: 2px;
      }
      .description {
        color: var(--primary-text-color, #1a1a1a);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .subtitle {
        color: var(--secondary-text-color, #5a5a5a);
      }
      .right {
        display: flex;
        align-items: center;
        gap: var(--ss-space-2);
      }
      .amount {
        color: var(--primary-text-color, #1a1a1a);
      }
    `,
  ];
}

declare global {
  interface HTMLElementTagNameMap {
    'ss-row-card': SsRowCard;
  }
}
