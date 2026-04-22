// <ss-empty-state
//    icon="mdi:playlist-check"
//    heading="No expenses yet"
//    caption="Add your first expense to get started"
// >
//   <ss-button slot="action" variant="primary">Add expense</ss-button>
//   <ss-button slot="action" variant="secondary">Settle up</ss-button>
// </ss-empty-state>

import { LitElement, html, css } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { baseStyles, typography } from '../styles';
import './icon';

@customElement('ss-empty-state')
export class SsEmptyState extends LitElement {
  @property({ type: String })
  icon = '';

  @property({ type: String })
  heading = '';

  @property({ type: String })
  caption = '';

  render() {
    return html`
      <div class="container">
        ${this.icon
          ? html`<div class="icon-wrap"><ss-icon .name=${this.icon} .size=${48}></ss-icon></div>`
          : ''}
        <div class="ss-text-title heading">${this.heading}</div>
        ${this.caption ? html`<div class="ss-text-body caption">${this.caption}</div>` : ''}
        <div class="actions">
          <slot name="action"></slot>
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
        align-items: center;
        gap: var(--ss-space-3);
        padding: var(--ss-space-6) var(--ss-space-4);
        text-align: center;
      }
      .icon-wrap {
        color: var(--secondary-text-color, #5a5a5a);
        margin-bottom: var(--ss-space-2);
      }
      .heading {
        color: var(--primary-text-color, #1a1a1a);
      }
      .caption {
        color: var(--secondary-text-color, #5a5a5a);
        max-width: 360px;
      }
      .actions {
        display: flex;
        flex-wrap: wrap;
        justify-content: center;
        gap: var(--ss-space-3);
        margin-top: var(--ss-space-3);
      }
    `,
  ];
}

declare global {
  interface HTMLElementTagNameMap {
    'ss-empty-state': SsEmptyState;
  }
}
