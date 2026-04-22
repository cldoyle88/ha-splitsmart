// <ss-balance-strip .participants=${...} .balances=${...} home-currency="GBP">
//
// Per-user pills showing net balance at a glance. Credit is green with
// up arrow, debit is red with down arrow, zero is neutral with a tick —
// colour is never the only signal (SPEC §15 / decision-blind users).

import { LitElement, html, css } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { baseStyles, typography } from '../styles';
import { formatAbs } from '../util/currency';
import type { Participant } from '../types';
import './user-avatar';
import './icon';

export interface BalanceEntry {
  user_id: string;
  amount: number;
}

@customElement('ss-balance-strip')
export class SsBalanceStrip extends LitElement {
  @property({ attribute: false })
  participants: Participant[] = [];

  @property({ attribute: false })
  balances: Record<string, number> = {};

  @property({ type: String, attribute: 'home-currency' })
  homeCurrency = 'GBP';

  @property({ type: String })
  locale = 'en-GB';

  render() {
    if (this.participants.length === 0) return html``;
    return html`
      <ul class="strip">
        ${this.participants.map((p) => this._renderPill(p))}
      </ul>
    `;
  }

  private _renderPill(p: Participant) {
    const amount = Number(this.balances[p.user_id] ?? 0);
    const rounded = Math.round(amount * 100) / 100;
    const kind = rounded > 0 ? 'credit' : rounded < 0 ? 'debit' : 'zero';
    const icon =
      kind === 'credit'
        ? 'mdi:arrow-up'
        : kind === 'debit'
          ? 'mdi:arrow-down'
          : 'mdi:check';
    const tone =
      kind === 'credit' ? 'Owed to' : kind === 'debit' ? 'Owes' : 'Square with';
    return html`
      <li class="pill kind-${kind}" title="${tone} ${p.display_name}">
        <ss-user-avatar
          .name=${p.display_name}
          .userId=${p.user_id}
          .size=${28}
          ?former=${!p.active}
        ></ss-user-avatar>
        <div class="text">
          <div class="ss-text-caption name">
            ${p.display_name}${p.active ? '' : ' (former participant)'}
          </div>
          <div class="amount ss-mono-amount">
            <ss-icon .name=${icon} .size=${14}></ss-icon>
            ${formatAbs(rounded, this.homeCurrency, this.locale)}
          </div>
        </div>
      </li>
    `;
  }

  static styles = [
    baseStyles,
    typography,
    css`
      .strip {
        display: flex;
        flex-wrap: wrap;
        gap: var(--ss-space-3);
        list-style: none;
        padding: 0;
        margin: 0;
      }
      .pill {
        display: flex;
        align-items: center;
        gap: var(--ss-space-3);
        padding: var(--ss-space-2) var(--ss-space-3);
        border-radius: 999px;
        background-color: var(--secondary-background-color, #f5f5f5);
        flex: 1 1 auto;
        min-width: 0;
      }
      .text {
        min-width: 0;
      }
      .name {
        color: var(--primary-text-color, #1a1a1a);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .amount {
        display: flex;
        align-items: center;
        gap: var(--ss-space-1);
      }
      .kind-credit .amount {
        color: var(--ss-credit-color);
      }
      .kind-debit .amount {
        color: var(--ss-debit-color);
      }
      .kind-zero .amount {
        color: var(--secondary-text-color, #5a5a5a);
      }
    `,
  ];
}

declare global {
  interface HTMLElementTagNameMap {
    'ss-balance-strip': SsBalanceStrip;
  }
}
