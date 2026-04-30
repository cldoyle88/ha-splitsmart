// <ss-staging-view
//    .hass=${hass}
//    .config=${splitsmartConfig}
// ></ss-staging-view>
//
// Staging review queue (SPEC §14, M5). Subscribes to
// splitsmart/list_staging/subscribe. Displays pending and
// review_each_time rows; FX-retry rows (always_split) get a badge.
//
// Per-row quick actions:
//   • Split 50/50  — promotes with single "Other" (or category_hint) category,
//                    equal-split 50/50 using first two active participants.
//   • Ignore       — calls splitsmart.skip_staging.
//   • ⋯            — opens detail sheet (#staging/<id>).
//
// Bulk mode: long-press a row → checkbox mode; action bar offers Skip selected.
// A 5-second dismissible toast confirms each action.
//
// Filter chips for source_preset and currency.

import { LitElement, html, css, type PropertyValues } from 'lit';
import { customElement, property, state } from 'lit/decorators.js';
import { baseStyles, typography } from '../styles';
import { promoteStaging, skipStaging, subscribeStaging, type StagingEvent } from '../api';
import type { HomeAssistant, SplitsmartConfig, StagingRow } from '../types';
import '../components/button';
import '../components/empty-state';

const RULE_ACTION_BADGE: Record<string, string> = {
  review_each_time: 'Review',
  always_split: 'FX retry',
};

@customElement('ss-staging-view')
export class SsStagingView extends LitElement {
  @property({ attribute: false })
  hass?: HomeAssistant;

  @property({ attribute: false })
  config: SplitsmartConfig | null = null;

  @state()
  private _rows: StagingRow[] = [];

  @state()
  private _filterSource: string | null = null;

  @state()
  private _filterCurrency: string | null = null;

  @state()
  private _bulkMode = false;

  @state()
  private _selected = new Set<string>();

  @state()
  private _toast: string | null = null;

  @state()
  private _working = new Set<string>();

  private _subUnsub: (() => void) | null = null;
  private _toastTimer: ReturnType<typeof setTimeout> | null = null;
  private _longPressTimer: ReturnType<typeof setTimeout> | null = null;

  protected async updated(changed: PropertyValues) {
    if (changed.has('hass') && this.hass && !this._subUnsub) {
      this._subUnsub = await subscribeStaging(this.hass, (ev) => this._onEvent(ev));
    }
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._subUnsub?.();
    this._subUnsub = null;
    if (this._toastTimer) clearTimeout(this._toastTimer);
    if (this._longPressTimer) clearTimeout(this._longPressTimer);
  }

  private _onEvent(ev: StagingEvent) {
    if (ev.kind === 'init') {
      this._rows = ev.rows;
      return;
    }
    const map = new Map(this._rows.map((r) => [r.id, r]));
    for (const r of [...ev.added, ...ev.updated]) map.set(r.id, r);
    for (const id of ev.deleted) map.delete(id);
    this._rows = [...map.values()];
  }

  private _navigate(route: string) {
    this.dispatchEvent(
      new CustomEvent('ss-navigate', { detail: { route }, bubbles: true, composed: true }),
    );
  }

  private _showToast(message: string) {
    if (this._toastTimer) clearTimeout(this._toastTimer);
    this._toast = message;
    this._toastTimer = setTimeout(() => { this._toast = null; }, 5000);
  }

  private _visibleRows(): StagingRow[] {
    let rows = this._rows;
    if (this._filterSource) rows = rows.filter((r) => r.source_preset === this._filterSource);
    if (this._filterCurrency) rows = rows.filter((r) => r.currency === this._filterCurrency);
    return rows;
  }

  private _sources(): string[] {
    return [...new Set(this._rows.map((r) => r.source_preset).filter(Boolean) as string[])];
  }

  private _currencies(): string[] {
    const home = this.config?.home_currency ?? '';
    return [...new Set(this._rows.map((r) => r.currency).filter((c) => c !== home))];
  }

  private _defaultSplit(): Array<{ user_id: string; value: number }> {
    const active = this.config?.participants.filter((p) => p.active) ?? [];
    if (active.length === 0) return [];
    const pct = Math.round(100 / active.length);
    const shares = active.map((p, i) => ({
      user_id: p.user_id,
      value: i === active.length - 1 ? 100 - pct * (active.length - 1) : pct,
    }));
    return shares;
  }

  private async _quickPromote(row: StagingRow) {
    if (!this.hass || !this.config || this._working.has(row.id)) return;
    const paidBy = row.uploaded_by;
    const catName = row.category_hint ?? 'Other';
    const shares = this._defaultSplit();
    if (shares.length < 2) return;

    this._working = new Set([...this._working, row.id]);
    try {
      await promoteStaging(this.hass, {
        staging_id: row.id,
        paid_by: paidBy,
        categories: [
          {
            name: catName,
            home_amount: row.amount,
            split: { method: 'equal', shares },
          },
        ],
      });
      this._showToast(`Promoted "${row.description ?? row.id}"`);
    } catch {
      this._showToast('Promote failed — check the developer tools log.');
    } finally {
      this._working = new Set([...this._working].filter((id) => id !== row.id));
    }
  }

  private async _ignore(row: StagingRow) {
    if (!this.hass || this._working.has(row.id)) return;
    this._working = new Set([...this._working, row.id]);
    try {
      await skipStaging(this.hass, row.id);
      this._showToast(`Ignored "${row.description ?? row.id}"`);
    } catch {
      this._showToast('Skip failed — check the developer tools log.');
    } finally {
      this._working = new Set([...this._working].filter((id) => id !== row.id));
    }
  }

  private async _bulkSkip() {
    if (!this.hass || this._selected.size === 0) return;
    const ids = [...this._selected];
    for (const id of ids) {
      await skipStaging(this.hass, id).catch(() => {});
    }
    const n = ids.length;
    this._selected = new Set();
    this._bulkMode = false;
    this._showToast(`Skipped ${n} row${n !== 1 ? 's' : ''}`);
  }

  private _enterBulk(id: string) {
    this._bulkMode = true;
    this._selected = new Set([id]);
  }

  private _toggleSelect(id: string) {
    const next = new Set(this._selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    this._selected = next;
  }

  private _onLongPressStart(id: string) {
    this._longPressTimer = setTimeout(() => this._enterBulk(id), 600);
  }

  private _onLongPressEnd() {
    if (this._longPressTimer) {
      clearTimeout(this._longPressTimer);
      this._longPressTimer = null;
    }
  }

  private _renderFilterChips() {
    const sources = this._sources();
    const currencies = this._currencies();
    if (sources.length === 0 && currencies.length === 0) return html``;
    return html`
      <div class="chips">
        ${sources.map(
          (s) => html`
            <button
              class="chip ${this._filterSource === s ? 'chip-active' : ''}"
              @click=${() => { this._filterSource = this._filterSource === s ? null : s; }}
            >${s}</button>
          `,
        )}
        ${currencies.map(
          (c) => html`
            <button
              class="chip ${this._filterCurrency === c ? 'chip-active' : ''}"
              @click=${() => { this._filterCurrency = this._filterCurrency === c ? null : c; }}
            >${c}</button>
          `,
        )}
      </div>
    `;
  }

  private _renderRow(row: StagingRow) {
    const busy = this._working.has(row.id);
    const isChecked = this._selected.has(row.id);
    const badge = RULE_ACTION_BADGE[row.rule_action] ?? null;
    const isForeign = row.currency !== (this.config?.home_currency ?? 'GBP');

    return html`
      <div
        class="row-item ${isChecked ? 'row-selected' : ''}"
        @pointerdown=${() => this._onLongPressStart(row.id)}
        @pointerup=${this._onLongPressEnd}
        @pointercancel=${this._onLongPressEnd}
        @click=${() => {
          if (this._bulkMode) {
            this._toggleSelect(row.id);
          } else {
            this._navigate(`staging/${row.id}`);
          }
        }}
      >
        ${this._bulkMode
          ? html`<input
              type="checkbox"
              class="row-check"
              .checked=${isChecked}
              @click=${(e: Event) => { e.stopPropagation(); this._toggleSelect(row.id); }}
            />`
          : ''}
        <div class="row-body">
          <div class="row-main">
            <div class="row-desc ss-text-body">${row.description ?? '—'}</div>
            <div class="row-date ss-text-caption">${row.date ?? ''}</div>
          </div>
          <div class="row-right">
            <div class="row-amount ss-mono-amount">
              ${row.amount.toFixed(2)} ${row.currency}
            </div>
            ${badge ? html`<span class="row-badge ss-text-caption">${badge}</span>` : ''}
            ${row.category_hint ? html`<span class="row-hint ss-text-caption">${row.category_hint}</span>` : ''}
            ${isForeign ? html`<span class="row-fx ss-text-caption">FX</span>` : ''}
          </div>
        </div>
        ${!this._bulkMode
          ? html`
              <div class="row-actions" @click=${(e: Event) => e.stopPropagation()}>
                <ss-button
                  variant="secondary"
                  .disabled=${busy || isForeign}
                  @click=${() => this._quickPromote(row)}
                  aria-label="Split 50/50"
                >Split</ss-button>
                <ss-button
                  variant="secondary"
                  .disabled=${busy}
                  @click=${() => this._ignore(row)}
                  aria-label="Ignore this row"
                >Ignore</ss-button>
              </div>
            `
          : ''}
      </div>
    `;
  }

  private _renderBulkBar() {
    return html`
      <div class="bulk-bar">
        <span class="ss-text-body">${this._selected.size} selected</span>
        <div class="bulk-actions">
          <ss-button
            variant="destructive"
            .disabled=${this._selected.size === 0}
            @click=${this._bulkSkip}
          >Skip selected</ss-button>
          <ss-button
            variant="secondary"
            @click=${() => { this._bulkMode = false; this._selected = new Set(); }}
          >Cancel</ss-button>
        </div>
      </div>
    `;
  }

  render() {
    const visible = this._visibleRows();

    return html`
      <div class="container">
        <div class="toolbar">
          <ss-button variant="secondary" @click=${() => this._navigate('home')}>← Back</ss-button>
          <h2 class="ss-text-title title">Pending review</h2>
          <ss-button variant="secondary" @click=${() => this._navigate('rules')}>Rules</ss-button>
        </div>

        ${this._renderFilterChips()}

        ${this._bulkMode ? this._renderBulkBar() : ''}

        ${visible.length === 0
          ? html`
              <ss-empty-state
                icon="mdi:tray-arrow-down"
                heading="Nothing to review"
                caption="Import a bank statement to start splitting rows."
              >
                <ss-button slot="action" variant="primary" @click=${() => this._navigate('import')}>
                  Import file
                </ss-button>
                <ss-button slot="action" variant="secondary" @click=${() => this._navigate('add')}>
                  Add expense
                </ss-button>
              </ss-empty-state>
            `
          : html`
              <div class="row-list">
                ${visible.map((r) => this._renderRow(r))}
              </div>
            `}

        ${this._toast
          ? html`
              <div class="toast ss-text-body" role="status">
                ${this._toast}
                <button class="toast-dismiss" @click=${() => { this._toast = null; }}>✕</button>
              </div>
            `
          : ''}
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
        gap: var(--ss-space-3);
        padding: var(--ss-space-4);
        position: relative;
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
      .chips {
        display: flex;
        flex-wrap: wrap;
        gap: var(--ss-space-2);
      }
      .chip {
        padding: var(--ss-space-1) var(--ss-space-3);
        border-radius: 20px;
        border: 1px solid var(--divider-color, #e0e0e0);
        background: transparent;
        color: var(--primary-text-color, #1a1a1a);
        cursor: pointer;
        font-family: var(--ss-font-sans);
        font-size: var(--ss-text-caption-size);
        transition: background-color var(--ss-duration-fast) var(--ss-easing-standard);
      }
      .chip:hover {
        background: var(--secondary-background-color, #f5f5f5);
      }
      .chip-active {
        background: var(--ss-accent-color);
        color: var(--text-primary-color, #ffffff);
        border-color: var(--ss-accent-color);
      }
      .bulk-bar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: var(--ss-space-2) var(--ss-space-3);
        background: var(--secondary-background-color, #f5f5f5);
        border-radius: 8px;
      }
      .bulk-actions {
        display: flex;
        gap: var(--ss-space-2);
      }
      .row-list {
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-2);
      }
      .row-item {
        background: var(--secondary-background-color, #f5f5f5);
        border-radius: 10px;
        padding: var(--ss-space-3) var(--ss-space-3);
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-2);
        cursor: pointer;
        transition: background-color var(--ss-duration-fast) var(--ss-easing-standard);
        user-select: none;
      }
      .row-item:hover {
        background: color-mix(in srgb, var(--ss-accent-color) 8%, var(--secondary-background-color, #f5f5f5));
      }
      .row-selected {
        background: color-mix(in srgb, var(--ss-accent-color) 15%, var(--secondary-background-color, #f5f5f5));
      }
      .row-check {
        width: 20px;
        height: 20px;
        cursor: pointer;
        align-self: flex-start;
      }
      .row-body {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: var(--ss-space-3);
      }
      .row-main {
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: 2px;
      }
      .row-desc {
        font-weight: 500;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .row-date {
        color: var(--secondary-text-color, #5a5a5a);
      }
      .row-right {
        display: flex;
        flex-direction: column;
        align-items: flex-end;
        gap: 2px;
        flex-shrink: 0;
      }
      .row-amount {
        font-weight: 500;
      }
      .row-badge {
        background: color-mix(in srgb, var(--warning-color, #f9a825) 18%, transparent);
        color: var(--warning-color, #f9a825);
        padding: 1px var(--ss-space-2);
        border-radius: 4px;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.3px;
      }
      .row-hint {
        background: color-mix(in srgb, var(--ss-accent-color) 15%, transparent);
        color: var(--ss-accent-color);
        padding: 1px var(--ss-space-2);
        border-radius: 4px;
        font-size: 11px;
      }
      .row-fx {
        background: color-mix(in srgb, var(--info-color, #0288d1) 15%, transparent);
        color: var(--info-color, #0288d1);
        padding: 1px var(--ss-space-2);
        border-radius: 4px;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.3px;
      }
      .row-actions {
        display: flex;
        gap: var(--ss-space-2);
        padding-top: var(--ss-space-1);
      }
      .toast {
        position: sticky;
        bottom: var(--ss-space-4);
        left: var(--ss-space-4);
        right: var(--ss-space-4);
        background: var(--primary-text-color, #1a1a1a);
        color: var(--card-background-color, #ffffff);
        padding: var(--ss-space-3) var(--ss-space-4);
        border-radius: 10px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
        z-index: 10;
      }
      .toast-dismiss {
        background: transparent;
        border: none;
        color: inherit;
        cursor: pointer;
        font-size: 16px;
        padding: var(--ss-space-1);
        line-height: 1;
      }
    `,
  ];
}

declare global {
  interface HTMLElementTagNameMap {
    'ss-staging-view': SsStagingView;
  }
}
