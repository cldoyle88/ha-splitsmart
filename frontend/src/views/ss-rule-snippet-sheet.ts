// <ss-rule-snippet-sheet
//    .yamlSnippet=${'- id: r_…\n  …'}
//    .draftId=${'r_…'}
//    @close=${...}
// ></ss-rule-snippet-sheet>
//
// Overlay sheet that shows a YAML snippet the user should paste into
// their rules.yaml file. Copy-to-clipboard button + close. The watcher
// in __init__.py picks up the change automatically within 30 seconds.

import { LitElement, html, css } from 'lit';
import { customElement, property, state } from 'lit/decorators.js';
import { baseStyles, typography } from '../styles';
import '../components/modal';
import '../components/button';

@customElement('ss-rule-snippet-sheet')
export class SsRuleSnippetSheet extends LitElement {
  @property({ type: String })
  yamlSnippet = '';

  @property({ type: String })
  draftId = '';

  @state()
  private _copied = false;

  private _close() {
    this.dispatchEvent(new CustomEvent('close', { bubbles: true, composed: true }));
  }

  private async _copy() {
    try {
      await navigator.clipboard.writeText(this.yamlSnippet);
      this._copied = true;
      setTimeout(() => {
        this._copied = false;
      }, 2500);
    } catch {
      // Clipboard API unavailable — select the text instead.
      const pre = this.shadowRoot?.querySelector('pre');
      if (pre) {
        const sel = window.getSelection();
        const range = document.createRange();
        range.selectNodeContents(pre);
        sel?.removeAllRanges();
        sel?.addRange(range);
      }
    }
  }

  render() {
    return html`
      <ss-modal .open=${true} heading="Rule YAML snippet" @close=${this._close}>
        <div class="body">
          <p class="ss-text-body instruction">
            Add this snippet to your <code>rules.yaml</code> file. The integration
            picks up changes automatically within 30 seconds.
          </p>
          <pre class="snippet ss-text-caption">${this.yamlSnippet}</pre>
          ${this._copied
            ? html`<div class="copied-banner ss-text-caption">Copied to clipboard ✓</div>`
            : ''}
        </div>

        <ss-button slot="footer" variant="secondary" @click=${this._close}>Close</ss-button>
        <ss-button slot="footer" variant="primary" @click=${this._copy}>
          ${this._copied ? 'Copied!' : 'Copy YAML'}
        </ss-button>
      </ss-modal>
    `;
  }

  static styles = [
    baseStyles,
    typography,
    css`
      :host {
        display: contents;
      }
      .body {
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-4);
      }
      .instruction {
        margin: 0;
        color: var(--secondary-text-color, #5a5a5a);
      }
      code {
        font-family: var(--ss-font-mono);
        background: var(--secondary-background-color, #f5f5f5);
        padding: 1px 4px;
        border-radius: 4px;
      }
      .snippet {
        margin: 0;
        padding: var(--ss-space-3);
        background: var(--secondary-background-color, #f5f5f5);
        border-radius: 8px;
        font-family: var(--ss-font-mono);
        font-size: 13px;
        white-space: pre;
        overflow-x: auto;
        line-height: 1.5;
        color: var(--primary-text-color, #1a1a1a);
        cursor: text;
        user-select: text;
      }
      .copied-banner {
        background: color-mix(in srgb, var(--ss-credit-color) 15%, transparent);
        color: var(--ss-credit-color);
        padding: var(--ss-space-2) var(--ss-space-3);
        border-radius: 6px;
        text-align: center;
      }
    `,
  ];
}

declare global {
  interface HTMLElementTagNameMap {
    'ss-rule-snippet-sheet': SsRuleSnippetSheet;
  }
}
