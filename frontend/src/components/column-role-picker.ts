// <ss-column-role-picker
//    header="Date"
//    .samples=${["2026-04-01", "2026-04-02"]}
//    .role=${"date"}
//    @role-changed=${...}
// ></ss-column-role-picker>
//
// Per-column role selector for the import wizard. Shows the column header,
// up to 3 sample values, and a <select> for the role assignment.
// Emits a "role-changed" custom event with { header, role } on change.

import { LitElement, html, css } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { baseStyles, typography } from '../styles';
import type { ColumnRole } from '../types';

const ROLES: Array<{ value: ColumnRole | 'ignore'; label: string }> = [
  { value: 'ignore', label: 'Ignore' },
  { value: 'date', label: 'Date' },
  { value: 'description', label: 'Description' },
  { value: 'amount', label: 'Amount (net)' },
  { value: 'debit', label: 'Debit (out)' },
  { value: 'credit', label: 'Credit (in)' },
  { value: 'currency', label: 'Currency' },
];

@customElement('ss-column-role-picker')
export class SsColumnRolePicker extends LitElement {
  @property({ type: String })
  header = '';

  @property({ attribute: false })
  samples: string[] = [];

  @property({ type: String })
  role: ColumnRole | 'ignore' = 'ignore';

  private _onChange(e: Event) {
    const value = (e.target as HTMLSelectElement).value as ColumnRole | 'ignore';
    this.role = value;
    this.dispatchEvent(
      new CustomEvent('role-changed', {
        detail: { header: this.header, role: value },
        bubbles: true,
        composed: true,
      }),
    );
  }

  render() {
    const preview = this.samples.slice(0, 3);
    return html`
      <div class="picker">
        <div class="col-header ss-text-button">${this.header}</div>
        <div class="samples ss-text-caption">
          ${preview.map((s) => html`<div class="sample">${s || '—'}</div>`)}
        </div>
        <select class="role-select ss-text-body" .value=${this.role} @change=${this._onChange}>
          ${ROLES.map(
            (r) => html`<option value=${r.value} ?selected=${this.role === r.value}>${r.label}</option>`,
          )}
        </select>
      </div>
    `;
  }

  static styles = [
    baseStyles,
    typography,
    css`
      .picker {
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-2);
        background: var(--secondary-background-color, #f5f5f5);
        border-radius: 8px;
        padding: var(--ss-space-3);
        min-width: 120px;
      }
      .col-header {
        font-weight: 600;
        color: var(--primary-text-color, #1a1a1a);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .samples {
        display: flex;
        flex-direction: column;
        gap: 2px;
        min-height: 48px;
        color: var(--secondary-text-color, #5a5a5a);
      }
      .sample {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .role-select {
        min-height: var(--ss-touch-min);
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 6px;
        background: var(--card-background-color, #ffffff);
        color: var(--primary-text-color, #1a1a1a);
        padding: var(--ss-space-2);
        cursor: pointer;
        font-family: var(--ss-font-sans);
        font-size: var(--ss-text-body-size);
      }
      .role-select:focus {
        outline: 2px solid var(--primary-color, #03a9f4);
        outline-offset: 1px;
      }
    `,
  ];
}

declare global {
  interface HTMLElementTagNameMap {
    'ss-column-role-picker': SsColumnRolePicker;
  }
}
