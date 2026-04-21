// <ss-placeholder-tile
//    icon="mdi:tray-full"
//    title="Pending review"
//    milestone="M5"
//    caption="Receipts and imports waiting for a split/ignore decision."
// ></ss-placeholder-tile>
//
// Renders a deliberately non-interactive tile on the Home view for
// features that are spec'd but not yet built. Per decision 10 from
// M2_PLAN.md §8, M2 uses this only for the Staging queue — import,
// rules and settings do not get Home-screen placeholders.

import { LitElement, html, css } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { baseStyles, typography } from '../styles';
import './icon';

@customElement('ss-placeholder-tile')
export class SsPlaceholderTile extends LitElement {
  @property({ type: String })
  icon = 'mdi:clock-outline';

  @property({ type: String })
  title = '';

  /** Which milestone ships this feature, e.g. "M5". */
  @property({ type: String })
  milestone = '';

  @property({ type: String })
  caption = '';

  render() {
    const badge = this.milestone ? `Coming in ${this.milestone}` : 'Coming soon';
    return html`
      <div class="tile" aria-disabled="true">
        <div class="icon-wrap"><ss-icon .name=${this.icon} .size=${24}></ss-icon></div>
        <div class="copy">
          <div class="ss-text-title title">${this.title}</div>
          ${this.caption ? html`<div class="ss-text-caption caption">${this.caption}</div>` : ''}
        </div>
        <div class="badge ss-text-caption">${badge}</div>
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
      .tile {
        display: flex;
        align-items: center;
        gap: var(--ss-space-3);
        padding: var(--ss-space-4);
        border: 1px dashed var(--divider-color, #e0e0e0);
        border-radius: var(--ss-card-radius);
        color: var(--secondary-text-color, #5a5a5a);
        opacity: 0.78;
      }
      .icon-wrap {
        flex: 0 0 auto;
      }
      .copy {
        flex: 1;
        min-width: 0;
      }
      .title {
        color: var(--primary-text-color, #1a1a1a);
        margin-bottom: 2px;
      }
      .caption {
        color: var(--secondary-text-color, #5a5a5a);
      }
      .badge {
        flex: 0 0 auto;
        padding: 2px var(--ss-space-2);
        border-radius: 999px;
        background-color: var(--secondary-background-color, #f5f5f5);
        color: var(--secondary-text-color, #5a5a5a);
        white-space: nowrap;
      }
    `,
  ];
}

declare global {
  interface HTMLElementTagNameMap {
    'ss-placeholder-tile': SsPlaceholderTile;
  }
}
