// <ss-button variant="primary"> Label </ss-button>
//
// Three variants: primary, secondary, destructive. Disabled supported.
// Always meets SPEC §15 touch-target minimum via --ss-touch-min.
// A real <button> element is rendered so native semantics (focus,
// keyboard activation, form submission) work without JS plumbing.

import { LitElement, html, css } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { baseStyles, typography } from '../styles';

export type SsButtonVariant = 'primary' | 'secondary' | 'destructive';

@customElement('ss-button')
export class SsButton extends LitElement {
  @property({ type: String })
  variant: SsButtonVariant = 'primary';

  @property({ type: Boolean, reflect: true })
  disabled = false;

  @property({ type: String })
  type: 'button' | 'submit' | 'reset' = 'button';

  @property({ type: String, attribute: 'aria-label' })
  ariaLabel: string | null = null;

  render() {
    return html`
      <button
        class="ss-focus-ring ss-text-button variant-${this.variant}"
        type=${this.type}
        ?disabled=${this.disabled}
        aria-label=${this.ariaLabel ?? ''}
      >
        <slot></slot>
      </button>
    `;
  }

  static styles = [
    baseStyles,
    typography,
    css`
      :host {
        display: inline-block;
      }
      button {
        min-height: var(--ss-touch-min);
        min-width: var(--ss-touch-min);
        padding: var(--ss-space-2) var(--ss-space-4);
        border-radius: 8px;
        border: 1px solid transparent;
        cursor: pointer;
        transition:
          background-color var(--ss-duration-fast) var(--ss-easing-standard),
          border-color var(--ss-duration-fast) var(--ss-easing-standard),
          color var(--ss-duration-fast) var(--ss-easing-standard);
      }
      button:focus-visible {
        outline: 2px solid var(--primary-color, #03a9f4);
        outline-offset: 2px;
      }
      button:disabled {
        opacity: 0.5;
        cursor: not-allowed;
      }

      .variant-primary {
        background-color: var(--ss-accent-color);
        color: var(--text-primary-color, #ffffff);
      }
      .variant-primary:hover:not(:disabled) {
        background-color: color-mix(in srgb, var(--ss-accent-color) 88%, black);
      }

      .variant-secondary {
        background-color: transparent;
        color: var(--primary-text-color, #1a1a1a);
        border-color: var(--divider-color, #e0e0e0);
      }
      .variant-secondary:hover:not(:disabled) {
        background-color: var(--secondary-background-color, #f5f5f5);
      }

      .variant-destructive {
        background-color: transparent;
        color: var(--error-color, #db4437);
        border-color: var(--error-color, #db4437);
      }
      .variant-destructive:hover:not(:disabled) {
        background-color: color-mix(in srgb, var(--error-color, #db4437) 12%, transparent);
      }
    `,
  ];
}

declare global {
  interface HTMLElementTagNameMap {
    'ss-button': SsButton;
  }
}
