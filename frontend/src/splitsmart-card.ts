// Splitsmart Lovelace custom card — M2 entry point.
//
// Step 5 scope: hello-world shell. Registers <splitsmart-card> and a
// gallery entry via window.customCards, wires up the hass property so
// Lovelace's reactive re-render contract works, and ensures the
// self-hosted fonts are installed before first paint. Every view, the
// router, and the design system land in later steps.

import { LitElement, html, css, type PropertyValues } from 'lit';
import { customElement, property, state } from 'lit/decorators.js';

import { ensureFontsLoaded } from './styles';
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
    ensureFontsLoaded();
  }

  protected firstUpdated(_changed: PropertyValues): void {
    // Subsequent steps hydrate config + subscribe to expense deltas here.
  }

  render() {
    const view = this._config.view ?? DEFAULT_VIEW;
    return html`
      <ha-card>
        <div class="shell">
          <div class="title">Splitsmart</div>
          <div class="caption">
            ${this.hass
              ? html`View: <span class="mono">${view}</span> · v${VERSION}`
              : html`<span class="mono">Waiting for Home Assistant…</span>`}
          </div>
        </div>
      </ha-card>
    `;
  }

  static styles = css`
    :host {
      display: block;
    }
    ha-card {
      background: var(--card-background-color, #ffffff);
      color: var(--primary-text-color, #1a1a1a);
      border-radius: var(--ha-card-border-radius, 12px);
    }
    .shell {
      padding: 24px;
      display: flex;
      flex-direction: column;
      gap: 4px;
      font-family: 'DM Sans', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
    }
    .title {
      font-size: 28px;
      font-weight: 600;
      line-height: 1.2;
      color: var(--primary-text-color, #1a1a1a);
    }
    .caption {
      font-size: 13px;
      color: var(--secondary-text-color, #5a5a5a);
      line-height: 1.4;
    }
    .mono {
      font-family: 'DM Mono', ui-monospace, 'SF Mono', Menlo, monospace;
      font-variant-numeric: tabular-nums;
    }
  `;
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
