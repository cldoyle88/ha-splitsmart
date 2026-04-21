// <ss-category-picker .options=${['Groceries', ...]} .value=${'Groceries'}
//    @ss-change=${...}>
//
// Wraps a native <select>. Keeping it native means keyboard navigation,
// screen readers, and the mobile wheel picker work without effort.

import { LitElement, html, css } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { baseStyles, typography } from '../styles';

@customElement('ss-category-picker')
export class SsCategoryPicker extends LitElement {
  @property({ attribute: false })
  options: string[] = [];

  @property({ type: String })
  value = '';

  @property({ type: Boolean })
  disabled = false;

  @property({ type: String })
  placeholder = 'Select a category';

  private _onChange(e: Event): void {
    const t = e.target as HTMLSelectElement;
    this.value = t.value;
    this.dispatchEvent(
      new CustomEvent('ss-change', {
        detail: { value: t.value },
        bubbles: true,
        composed: true,
      }),
    );
  }

  render() {
    return html`
      <select
        class="ss-text-body ss-focus-ring"
        .value=${this.value}
        ?disabled=${this.disabled}
        @change=${this._onChange}
      >
        ${!this.value
          ? html`<option value="" disabled selected>${this.placeholder}</option>`
          : ''}
        ${this.options.map(
          (o) => html`<option value=${o} ?selected=${o === this.value}>${o}</option>`,
        )}
      </select>
    `;
  }

  static styles = [
    baseStyles,
    typography,
    css`
      :host {
        display: block;
      }
      select {
        width: 100%;
        padding: var(--ss-space-2) var(--ss-space-3);
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 8px;
        background-color: var(--card-background-color, #ffffff);
        color: var(--primary-text-color, #1a1a1a);
        font-family: var(--ss-font-sans);
        min-height: var(--ss-touch-min);
      }
      select:focus-visible {
        outline: 2px solid var(--primary-color, #03a9f4);
        outline-offset: 2px;
      }
    `,
  ];
}

declare global {
  interface HTMLElementTagNameMap {
    'ss-category-picker': SsCategoryPicker;
  }
}
