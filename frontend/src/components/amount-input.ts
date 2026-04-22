// <ss-amount-input currency="GBP" .value=${40.0} @ss-change=${...}>
//
// Text input with currency prefix. Commits a numeric value on blur
// and on `input` (debounce-free — the form decides when to read it).
// Emits ss-change with {value: number | null, raw: string}.

import { LitElement, html, css } from 'lit';
import { customElement, property, state } from 'lit/decorators.js';
import { baseStyles, typography } from '../styles';
import { parseAmount } from '../util/currency';

@customElement('ss-amount-input')
export class SsAmountInput extends LitElement {
  @property({ type: Number })
  value: number | null = null;

  @property({ type: String })
  currency = 'GBP';

  @property({ type: String })
  placeholder = '0.00';

  @property({ type: String, attribute: 'aria-label' })
  ariaLabel: string | null = null;

  @property({ type: Boolean })
  disabled = false;

  @state()
  private _raw = '';

  protected willUpdate(): void {
    if (this.value != null && this._raw === '') {
      this._raw = this.value.toFixed(2);
    }
  }

  private _emit(): void {
    const parsed = parseAmount(this._raw);
    this.dispatchEvent(
      new CustomEvent('ss-change', {
        detail: { value: parsed, raw: this._raw },
        bubbles: true,
        composed: true,
      }),
    );
  }

  private _onInput(e: Event): void {
    const target = e.target as HTMLInputElement;
    this._raw = target.value;
    this._emit();
  }

  private _symbol(): string {
    // Keep it simple — we only care about common currencies in M2.
    const map: Record<string, string> = { GBP: '£', EUR: '€', USD: '$', CAD: '$', AUD: '$' };
    return map[this.currency] ?? this.currency;
  }

  render() {
    return html`
      <label class="wrap ${this.disabled ? 'disabled' : ''}">
        <span class="symbol ss-text-body">${this._symbol()}</span>
        <input
          class="ss-mono-amount input ss-focus-ring"
          type="text"
          inputmode="decimal"
          autocomplete="off"
          .value=${this._raw}
          placeholder=${this.placeholder}
          aria-label=${this.ariaLabel ?? ''}
          ?disabled=${this.disabled}
          @input=${this._onInput}
          @blur=${this._emit}
        />
      </label>
    `;
  }

  static styles = [
    baseStyles,
    typography,
    css`
      :host {
        display: block;
      }
      .wrap {
        display: flex;
        align-items: center;
        gap: var(--ss-space-2);
        padding: var(--ss-space-2) var(--ss-space-3);
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 8px;
        background-color: var(--card-background-color, #ffffff);
        min-height: var(--ss-touch-min);
      }
      .wrap:focus-within {
        border-color: var(--primary-color, #03a9f4);
      }
      .wrap.disabled {
        opacity: 0.5;
      }
      .symbol {
        color: var(--secondary-text-color, #5a5a5a);
      }
      .input {
        flex: 1;
        border: none;
        outline: none;
        background: transparent;
        color: var(--primary-text-color, #1a1a1a);
        min-width: 0;
        font-variant-numeric: tabular-nums;
      }
    `,
  ];
}

declare global {
  interface HTMLElementTagNameMap {
    'ss-amount-input': SsAmountInput;
  }
}
