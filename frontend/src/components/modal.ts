// <ss-modal .open=${true} heading="Tesco Metro" @close=${...}>
//   <slot content…>
// </ss-modal>
//
// Full-screen sheet. Mobile-first — slides up from the bottom on small
// viewports, centred modal on desktop. Dismissed by the close icon, by
// escape, or by backdrop click.

import { LitElement, html, css } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { baseStyles, typography } from '../styles';
import './icon';

@customElement('ss-modal')
export class SsModal extends LitElement {
  @property({ type: Boolean, reflect: true })
  open = false;

  @property({ type: String })
  heading = '';

  /** Whether to show the back chevron instead of the close X. */
  @property({ type: Boolean, attribute: 'show-back' })
  showBack = false;

  connectedCallback(): void {
    super.connectedCallback();
    document.addEventListener('keydown', this._onKey);
  }

  disconnectedCallback(): void {
    super.disconnectedCallback();
    document.removeEventListener('keydown', this._onKey);
  }

  private _onKey = (e: KeyboardEvent) => {
    if (e.key === 'Escape' && this.open) {
      e.preventDefault();
      this._emitClose();
    }
  };

  private _emitClose() {
    this.dispatchEvent(new CustomEvent('close', { bubbles: true, composed: true }));
  }

  private _onBackdropClick(e: MouseEvent) {
    if (e.target === e.currentTarget) {
      this._emitClose();
    }
  }

  render() {
    if (!this.open) return html``;
    const iconName = this.showBack ? 'mdi:chevron-left' : 'mdi:close';
    const label = this.showBack ? 'Back' : 'Close';
    return html`
      <div class="backdrop" @click=${this._onBackdropClick}>
        <div class="sheet" role="dialog" aria-modal="true" aria-label=${this.heading}>
          <header>
            <button
              class="ss-focus-ring icon-button"
              type="button"
              @click=${this._emitClose}
              aria-label=${label}
            >
              <ss-icon .name=${iconName} .size=${24}></ss-icon>
            </button>
            <div class="ss-text-title">${this.heading}</div>
            <div class="spacer"></div>
          </header>
          <div class="body">
            <slot></slot>
          </div>
          <footer>
            <slot name="footer"></slot>
          </footer>
        </div>
      </div>
    `;
  }

  static styles = [
    baseStyles,
    typography,
    css`
      :host {
        display: contents;
      }
      .backdrop {
        position: fixed;
        inset: 0;
        z-index: 1000;
        background: rgba(0, 0, 0, 0.45);
        display: flex;
        justify-content: center;
        align-items: flex-end;
        animation: fade-in var(--ss-duration-base) var(--ss-easing-enter);
      }
      .sheet {
        background: var(--card-background-color, #ffffff);
        color: var(--primary-text-color, #1a1a1a);
        border-radius: var(--ss-card-radius) var(--ss-card-radius) 0 0;
        width: 100%;
        max-width: 640px;
        max-height: 90vh;
        display: flex;
        flex-direction: column;
        animation: slide-up var(--ss-duration-slow) var(--ss-easing-enter);
      }
      @media (min-width: 768px) {
        .backdrop {
          align-items: center;
        }
        .sheet {
          border-radius: var(--ss-card-radius);
          max-height: 85vh;
          animation: fade-in var(--ss-duration-base) var(--ss-easing-enter);
        }
      }
      header {
        display: flex;
        align-items: center;
        gap: var(--ss-space-3);
        padding: var(--ss-space-3) var(--ss-space-4);
        border-bottom: 1px solid var(--divider-color, #e0e0e0);
      }
      .icon-button {
        min-width: var(--ss-touch-min);
        min-height: var(--ss-touch-min);
        border: none;
        background: transparent;
        color: inherit;
        cursor: pointer;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
      }
      .icon-button:focus-visible {
        outline: 2px solid var(--primary-color, #03a9f4);
        outline-offset: 2px;
      }
      .icon-button:hover {
        background-color: var(--secondary-background-color, #f5f5f5);
      }
      .spacer {
        flex: 1;
      }
      .body {
        flex: 1;
        overflow-y: auto;
        padding: var(--ss-space-4);
      }
      footer {
        padding: var(--ss-space-3) var(--ss-space-4);
        border-top: 1px solid var(--divider-color, #e0e0e0);
        display: flex;
        gap: var(--ss-space-3);
        justify-content: flex-end;
      }
      footer:empty {
        display: none;
      }
      @keyframes fade-in {
        from {
          opacity: 0;
        }
        to {
          opacity: 1;
        }
      }
      @keyframes slide-up {
        from {
          transform: translateY(100%);
        }
        to {
          transform: translateY(0);
        }
      }
    `,
  ];
}

declare global {
  interface HTMLElementTagNameMap {
    'ss-modal': SsModal;
  }
}
