// Splitsmart Lovelace custom card — M2 entry point.
//
// Step 5 scope: hello-world shell. Registers <splitsmart-card> and a
// gallery entry via window.customCards, wires up the hass property so
// Lovelace's reactive re-render contract works, and ensures the
// self-hosted fonts are installed before first paint. Every view, the
// router, and the design system land in later steps.

import { LitElement, html, css, type PropertyValues } from 'lit';
import { customElement, property, state } from 'lit/decorators.js';

import { baseStyles, installGlobalStyles, typography } from './styles';
import type { HomeAssistant, SplitsmartCardConfig } from './types';

export const VERSION = '0.1.0-m2';

const DEFAULT_VIEW = 'home';
const SUPPORTED_VIEWS = new Set(['home', 'ledger', 'add', 'settle']);

@customElement('splitsmart-card')
export class SplitsmartCard extends LitElement {
  /** Injected by Lovelace on every state change. */
  @property({ attribute: false })
  hass?: HomeAssistant;

  /** Card config from the dashboard YAML. */
  @state()
  private _config: SplitsmartCardConfig = { type: 'custom:splitsmart-card' };

  setConfig(config: SplitsmartCardConfig): void {
    if (config.view && !SUPPORTED_VIEWS.has(config.view)) {
      throw new Error(
        `Unknown view '${config.view}'. Supported: home, ledger, add, settle.`,
      );
    }
    this._config = { ...config };
  }

  connectedCallback(): void {
    super.connectedCallback();
    installGlobalStyles();
  }

  protected firstUpdated(_changed: PropertyValues): void {
    // Subsequent steps hydrate config + subscribe to expense deltas here.
  }

  render() {
    const view = this._config.view ?? DEFAULT_VIEW;
    return html`
      <ha-card>
        <div class="shell">
          <div class="ss-text-display">Splitsmart</div>
          <div class="ss-text-caption">
            ${this.hass
              ? html`View: <span class="ss-mono-caption">${view}</span> · v${VERSION}`
              : html`<span class="ss-mono-caption">Waiting for Home Assistant…</span>`}
          </div>
        </div>
      </ha-card>
    `;
  }

  static styles = [
    baseStyles,
    typography,
    css`
      ha-card {
        background: var(--card-background-color, #ffffff);
        color: var(--primary-text-color, #1a1a1a);
        border-radius: var(--ss-card-radius);
      }
      .shell {
        padding: var(--ss-space-5);
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-1);
      }
    `,
  ];
}

// Register an entry in the Lovelace "Add Card" gallery. Preview artwork
// is deferred to M7 polish (decision 4 from M2_PLAN.md §8).
window.customCards = window.customCards ?? [];
if (!window.customCards.some((c) => c.type === 'splitsmart-card')) {
  window.customCards.push({
    type: 'splitsmart-card',
    name: 'Splitsmart',
    description: 'Household expense splitting — balances, ledger, add, settle up.',
  });
}

declare global {
  interface HTMLElementTagNameMap {
    'splitsmart-card': SplitsmartCard;
  }
}
