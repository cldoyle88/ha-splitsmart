// <ss-icon name="mdi:plus-circle" size="24"></ss-icon>
//
// Thin wrapper around HA's <ha-icon>. We delegate to it when available
// (the normal case — Lovelace always loads ha-icon). The wrapper exists
// so we can tune colour / size / accessibility consistently across the
// card without repeating the three-line boilerplate at every use site.

import { LitElement, html, css } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { baseStyles } from '../styles';

@customElement('ss-icon')
export class SsIcon extends LitElement {
  /** MDI icon name — e.g. "mdi:plus-circle". */
  @property({ type: String })
  name = '';

  /** CSS size in px. Defaults to 20 (matches button / row label height). */
  @property({ type: Number })
  size = 20;

  /** Optional aria-label for icon-only buttons. */
  @property({ type: String, attribute: 'aria-label' })
  ariaLabel: string | null = null;

  render() {
    return html`
      <ha-icon
        .icon=${this.name}
        role=${this.ariaLabel ? 'img' : 'presentation'}
        aria-label=${this.ariaLabel ?? ''}
        aria-hidden=${this.ariaLabel ? 'false' : 'true'}
        style=${`--mdc-icon-size: ${this.size}px; width: ${this.size}px; height: ${this.size}px;`}
      ></ha-icon>
    `;
  }

  static styles = [
    baseStyles,
    css`
      :host {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        color: inherit;
        line-height: 0;
      }
      ha-icon {
        color: inherit;
      }
    `,
  ];
}

declare global {
  interface HTMLElementTagNameMap {
    'ss-icon': SsIcon;
  }
}
