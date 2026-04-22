// <ss-split-picker
//    .participants=${activeParticipants}
//    .allocationAmount=${55.20}
//    .value=${splitObject}
//    currency="GBP"
//    @ss-change=${...}>
//
// Method tabs (Equal / Percentage / Shares / Exact) plus an N-user
// share grid. Emits ss-change whenever any input changes, with the
// complete {method, shares} split object. Also emits {valid: boolean}
// so the parent form can toggle Save.
//
// For 'equal', the grid is read-only — everyone gets the same
// percentage. For 'percentage' / 'shares' / 'exact', values are
// user-editable.

import { LitElement, html, css } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { baseStyles, typography } from '../styles';
import { parseAmount } from '../util/currency';
import type { Participant, Split } from '../types';

type Method = 'equal' | 'percentage' | 'shares' | 'exact';

const METHODS: { id: Method; label: string }[] = [
  { id: 'equal', label: 'Equal' },
  { id: 'percentage', label: '%' },
  { id: 'shares', label: 'Shares' },
  { id: 'exact', label: 'Exact' },
];

/** Build a valid split for the given method + participant list.
 *  Equal fills each with 100/N; others zero. */
export function makeDefaultSplit(method: Method, participants: Participant[]): Split {
  const per = participants.length > 0 ? Math.round((100 / participants.length) * 100) / 100 : 0;
  const shares = participants.map((p) => ({
    user_id: p.user_id,
    value: method === 'equal' ? per : method === 'shares' ? 1 : 0,
  }));
  return { method, shares };
}

/** Validate a split against the allocation amount. Returns true/false. */
export function isSplitValid(split: Split, allocationAmount: number): boolean {
  if (!split.shares || split.shares.length === 0) return false;
  const nonZero = split.shares.some((s) => (Number(s.value) || 0) > 0);
  if (split.method === 'exact') {
    const sum = split.shares.reduce((acc, s) => acc + (Number(s.value) || 0), 0);
    return nonZero && Math.abs(sum - allocationAmount) < 0.01;
  }
  return nonZero;
}

@customElement('ss-split-picker')
export class SsSplitPicker extends LitElement {
  @property({ attribute: false })
  participants: Participant[] = [];

  @property({ type: Number, attribute: 'allocation-amount' })
  allocationAmount = 0;

  @property({ attribute: false })
  value: Split = { method: 'equal', shares: [] };

  @property({ type: String })
  currency = 'GBP';

  private _pickMethod(method: Method): void {
    let next: Split;
    if (method === 'equal') {
      const per = this.participants.length > 0 ? 100 / this.participants.length : 0;
      next = {
        method,
        shares: this.participants.map((p) => ({ user_id: p.user_id, value: per })),
      };
    } else {
      // Preserve existing share user ids but reset to shape-appropriate values.
      next = {
        method,
        shares: this.participants.map((p) => {
          const existing = this.value.shares.find((s) => s.user_id === p.user_id);
          if (method === 'shares') return { user_id: p.user_id, value: existing?.value || 1 };
          return { user_id: p.user_id, value: existing?.value ?? 0 };
        }),
      };
    }
    this._emit(next);
  }

  private _updateShare(userId: string, rawValue: string): void {
    const n = parseAmount(rawValue) ?? 0;
    const next: Split = {
      method: this.value.method,
      shares: this.value.shares.map((s) =>
        s.user_id === userId ? { ...s, value: n } : s,
      ),
    };
    this._emit(next);
  }

  private _emit(next: Split): void {
    this.value = next;
    this.dispatchEvent(
      new CustomEvent('ss-change', {
        detail: {
          value: next,
          valid: isSplitValid(next, this.allocationAmount),
        },
        bubbles: true,
        composed: true,
      }),
    );
  }

  private _symbol(): string {
    const map: Record<string, string> = { GBP: '£', EUR: '€', USD: '$' };
    return map[this.currency] ?? this.currency;
  }

  private _suffixFor(): string {
    if (this.value.method === 'equal' || this.value.method === 'percentage') return '%';
    if (this.value.method === 'shares') return 'share(s)';
    return this._symbol();
  }

  render() {
    const readOnly = this.value.method === 'equal';
    const suffix = this._suffixFor();

    return html`
      <div class="container">
        <div class="methods" role="radiogroup" aria-label="Split method">
          ${METHODS.map(
            (m) => html`
              <button
                class="method ${m.id === this.value.method ? 'active' : ''} ss-focus-ring ss-text-button"
                type="button"
                role="radio"
                aria-checked=${m.id === this.value.method ? 'true' : 'false'}
                @click=${() => this._pickMethod(m.id)}
              >
                ${m.label}
              </button>
            `,
          )}
        </div>
        <div class="shares">
          ${this.value.shares.map((s) => {
            const p = this.participants.find((x) => x.user_id === s.user_id);
            if (!p) return html``;
            return html`
              <div class="share-row">
                <div class="name ss-text-body">${p.display_name}</div>
                <div class="input-wrap">
                  <input
                    class="ss-mono-amount share-input ss-focus-ring"
                    type="text"
                    inputmode="decimal"
                    .value=${String(s.value ?? 0)}
                    ?readonly=${readOnly}
                    aria-label=${`Share for ${p.display_name}`}
                    @input=${(e: Event) =>
                      this._updateShare(s.user_id, (e.target as HTMLInputElement).value)}
                  />
                  <span class="suffix ss-text-caption">${suffix}</span>
                </div>
              </div>
            `;
          })}
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
      .methods {
        display: flex;
        flex-wrap: wrap;
        gap: var(--ss-space-2);
        margin-bottom: var(--ss-space-3);
      }
      .method {
        min-height: 36px;
        padding: var(--ss-space-2) var(--ss-space-3);
        border-radius: 999px;
        border: 1px solid var(--divider-color, #e0e0e0);
        background-color: var(--card-background-color, #ffffff);
        color: var(--primary-text-color, #1a1a1a);
        cursor: pointer;
      }
      .method.active {
        background-color: var(--ss-accent-color);
        color: var(--text-primary-color, #ffffff);
        border-color: transparent;
      }
      .method:focus-visible {
        outline: 2px solid var(--primary-color, #03a9f4);
        outline-offset: 2px;
      }
      .shares {
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-2);
      }
      .share-row {
        display: flex;
        align-items: center;
        gap: var(--ss-space-3);
      }
      .name {
        flex: 1;
      }
      .input-wrap {
        display: flex;
        align-items: center;
        gap: var(--ss-space-1);
        padding: var(--ss-space-2) var(--ss-space-3);
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 8px;
        background-color: var(--card-background-color, #ffffff);
        min-width: 140px;
      }
      .input-wrap:focus-within {
        border-color: var(--primary-color, #03a9f4);
      }
      .share-input {
        width: 80px;
        border: none;
        outline: none;
        background: transparent;
        color: var(--primary-text-color, #1a1a1a);
        font-variant-numeric: tabular-nums;
        text-align: right;
      }
      .share-input[readonly] {
        color: var(--secondary-text-color, #5a5a5a);
      }
      .suffix {
        color: var(--secondary-text-color, #5a5a5a);
      }
    `,
  ];
}

declare global {
  interface HTMLElementTagNameMap {
    'ss-split-picker': SsSplitPicker;
  }
}
