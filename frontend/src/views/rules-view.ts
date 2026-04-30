// <ss-rules-view
//    .hass=${hass}
//    .config=${splitsmartConfig}
// ></ss-rules-view>
//
// Read-only view of rules loaded from /config/splitsmart/rules.yaml.
// Subscribes to splitsmart/list_rules/subscribe so the display updates
// automatically when the file watcher reloads the rules. Reload button
// calls splitsmart/reload_rules to force an immediate re-read.
//
// Empty state points the user at the YAML file with a copy-paste snippet.

import { LitElement, html, css, type PropertyValues } from 'lit';
import { customElement, property, state } from 'lit/decorators.js';
import { baseStyles, typography } from '../styles';
import { reloadRules, subscribeRules, type RulesEvent } from '../api';
import type { HomeAssistant, RuleRecord, SplitsmartConfig } from '../types';
import '../components/button';
import '../components/empty-state';

const ACTION_LABEL: Record<string, string> = {
  always_split: 'Auto-split',
  always_ignore: 'Auto-ignore',
  review_each_time: 'Review',
};

const ACTION_CLASS: Record<string, string> = {
  always_split: 'badge-split',
  always_ignore: 'badge-ignore',
  review_each_time: 'badge-review',
};

function formatLoadedAt(iso: string | null): string {
  if (!iso) return 'never';
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

@customElement('ss-rules-view')
export class SsRulesView extends LitElement {
  @property({ attribute: false })
  hass?: HomeAssistant;

  @property({ attribute: false })
  config: SplitsmartConfig | null = null;

  @state()
  private _rules: RuleRecord[] = [];

  @state()
  private _loadedAt: string | null = null;

  @state()
  private _sourcePath = '';

  @state()
  private _errors: string[] = [];

  @state()
  private _reloading = false;

  private _subUnsub: (() => void) | null = null;

  protected async updated(changed: PropertyValues) {
    if (changed.has('hass') && this.hass && !this._subUnsub) {
      this._subUnsub = await subscribeRules(this.hass, (ev) => this._onEvent(ev));
    }
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._subUnsub?.();
    this._subUnsub = null;
  }

  private _onEvent(ev: RulesEvent) {
    this._rules = ev.rules;
    this._loadedAt = ev.loaded_at;
    this._errors = ev.errors;
    if (ev.kind === 'init') this._sourcePath = ev.source_path;
  }

  private async _reload() {
    if (!this.hass || this._reloading) return;
    this._reloading = true;
    try {
      await reloadRules(this.hass);
    } finally {
      this._reloading = false;
    }
  }

  private _navigate(route: string) {
    this.dispatchEvent(
      new CustomEvent('ss-navigate', { detail: { route }, bubbles: true, composed: true }),
    );
  }

  private _renderRule(rule: RuleRecord) {
    const badgeClass = ACTION_CLASS[rule.action] ?? 'badge-review';
    const badgeLabel = ACTION_LABEL[rule.action] ?? rule.action;
    return html`
      <div class="rule-row">
        <div class="rule-main">
          <div class="rule-header">
            <span class="rule-id ss-mono-caption">${rule.id}</span>
            <span class="badge ${badgeClass} ss-text-caption">${badgeLabel}</span>
          </div>
          ${rule.description
            ? html`<div class="rule-desc ss-text-body">${rule.description}</div>`
            : ''}
          <div class="rule-pattern ss-mono-caption">/${rule.pattern}/i</div>
        </div>
        <div class="rule-meta ss-text-caption">
          ${rule.category ? html`<span class="meta-chip">${rule.category}</span>` : ''}
          ${rule.currency_match
            ? html`<span class="meta-chip">${rule.currency_match}</span>`
            : ''}
          ${rule.amount_min !== null && rule.amount_max !== null
            ? html`<span class="meta-chip">${rule.amount_min}–${rule.amount_max}</span>`
            : rule.amount_min !== null
              ? html`<span class="meta-chip">&gt;${rule.amount_min}</span>`
              : rule.amount_max !== null
                ? html`<span class="meta-chip">&lt;${rule.amount_max}</span>`
                : ''}
        </div>
      </div>
    `;
  }

  private _renderEmpty() {
    const snippet = `rules:\n  - id: r_example\n    match: /tesco|sainsbury/i\n    action: always_split\n    category: Groceries\n    split:\n      method: equal\n      preset: "50_50"`;
    return html`
      <ss-empty-state
        icon="mdi:file-document-outline"
        heading="No rules configured"
        caption="Rules auto-split or auto-ignore imported rows. Add them to your rules.yaml file."
      >
        <div slot="body" class="snippet-block">
          <div class="ss-text-caption snippet-label">
            Paste under <code>${this._sourcePath || '/config/splitsmart/rules.yaml'}</code>
          </div>
          <pre class="snippet ss-mono-caption">${snippet}</pre>
        </div>
      </ss-empty-state>
    `;
  }

  render() {
    return html`
      <div class="container">
        <div class="toolbar">
          <ss-button variant="secondary" @click=${() => this._navigate('home')}>
            ← Back
          </ss-button>
          <h2 class="ss-text-title title">Rules</h2>
          <ss-button
            variant="secondary"
            .disabled=${this._reloading}
            @click=${this._reload}
          >
            ${this._reloading ? 'Reloading…' : 'Reload'}
          </ss-button>
        </div>

        <div class="status ss-text-caption">
          ${this._rules.length} rule${this._rules.length !== 1 ? 's' : ''} · last loaded
          ${formatLoadedAt(this._loadedAt)}
        </div>

        ${this._errors.length
          ? html`
              <div class="errors">
                ${this._errors.map((e) => html`<div class="error-row ss-text-caption">${e}</div>`)}
              </div>
            `
          : ''}

        ${this._rules.length === 0 ? this._renderEmpty() : html`
          <div class="rule-list">
            ${this._rules.map((r) => this._renderRule(r))}
          </div>
        `}
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
        gap: var(--ss-space-4);
        padding: var(--ss-space-4);
      }
      .toolbar {
        display: flex;
        align-items: center;
        gap: var(--ss-space-3);
      }
      .title {
        flex: 1;
        margin: 0;
      }
      .status {
        color: var(--secondary-text-color, #5a5a5a);
      }
      .errors {
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-1);
      }
      .error-row {
        color: var(--error-color, #db4437);
        background: color-mix(in srgb, var(--error-color, #db4437) 10%, transparent);
        padding: var(--ss-space-2) var(--ss-space-3);
        border-radius: 6px;
      }
      .rule-list {
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-2);
      }
      .rule-row {
        background: var(--secondary-background-color, #f5f5f5);
        border-radius: 8px;
        padding: var(--ss-space-3) var(--ss-space-4);
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-2);
      }
      .rule-header {
        display: flex;
        align-items: center;
        gap: var(--ss-space-2);
        flex-wrap: wrap;
      }
      .rule-id {
        color: var(--secondary-text-color, #5a5a5a);
      }
      .badge {
        padding: 2px var(--ss-space-2);
        border-radius: 4px;
        font-size: 11px;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.4px;
      }
      .badge-split {
        background: color-mix(in srgb, var(--ss-credit-color) 15%, transparent);
        color: var(--ss-credit-color);
      }
      .badge-ignore {
        background: color-mix(in srgb, var(--secondary-text-color, #5a5a5a) 15%, transparent);
        color: var(--secondary-text-color, #5a5a5a);
      }
      .badge-review {
        background: color-mix(in srgb, var(--warning-color, #f9a825) 15%, transparent);
        color: var(--warning-color, #f9a825);
      }
      .rule-desc {
        color: var(--primary-text-color, #1a1a1a);
      }
      .rule-pattern {
        color: var(--ss-accent-color);
      }
      .rule-meta {
        display: flex;
        flex-wrap: wrap;
        gap: var(--ss-space-1);
      }
      .meta-chip {
        background: var(--divider-color, #e0e0e0);
        color: var(--primary-text-color, #1a1a1a);
        padding: 2px var(--ss-space-2);
        border-radius: 4px;
        font-size: 12px;
      }
      .snippet-block {
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-2);
        width: 100%;
      }
      .snippet-label {
        color: var(--secondary-text-color, #5a5a5a);
      }
      .snippet-label code {
        font-family: var(--ss-font-mono);
        background: var(--divider-color, #e0e0e0);
        padding: 1px 4px;
        border-radius: 3px;
      }
      .snippet {
        background: var(--code-editor-background-color, #1e1e1e);
        color: #d4d4d4;
        padding: var(--ss-space-3);
        border-radius: 8px;
        font-family: var(--ss-font-mono);
        font-size: 12px;
        line-height: 1.5;
        overflow-x: auto;
        white-space: pre;
        margin: 0;
      }
    `,
  ];
}

declare global {
  interface HTMLElementTagNameMap {
    'ss-rules-view': SsRulesView;
  }
}
