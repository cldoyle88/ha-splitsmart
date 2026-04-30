// <ss-staging-detail-sheet
//    .hass=${hass}
//    .config=${splitsmartConfig}
//    .stagingId=${'st_…'}
//    @close=${...}
// ></ss-staging-detail-sheet>
//
// Per-row detail sheet, opened from #staging/<staging_id>. Subscribes
// to splitsmart/list_staging/subscribe to find (and stay live on) the
// target row.
//
// Lets the user:
//   • Set paid_by, category, split (single or multi-allocation).
//   • Override description, date, or add notes (collapsible).
//   • Promote the row → calls splitsmart.promote_staging.
//   • Skip / ignore → calls splitsmart.skip_staging.
//   • Create a rule for similar rows → calls
//     splitsmart/draft_rule_from_row, opens ss-rule-snippet-sheet.
//
// Foreign-currency rows: quick-split is blocked (no home_amount on the
// staging row); the sheet shows an input to supply the home amount.

import { LitElement, html, css, type PropertyValues } from 'lit';
import { customElement, property, state } from 'lit/decorators.js';
import { baseStyles, typography } from '../styles';
import {
  draftRuleFromRow,
  promoteStaging,
  skipStaging,
  subscribeStaging,
  type DraftRuleResult,
  type StagingEvent,
} from '../api';
import type {
  CategoryAllocation,
  HomeAssistant,
  Participant,
  Split,
  SplitsmartConfig,
  StagingRow,
} from '../types';
import type { AllocationRow } from '../components/allocation-editor';
import { isSplitValid, makeDefaultSplit } from '../components/split-picker';
import '../components/modal';
import '../components/button';
import '../components/split-picker';
import '../components/category-picker';
import '../components/allocation-editor';
import './ss-rule-snippet-sheet';

const ROUND = (n: number) => Math.round(n * 100) / 100;

@customElement('ss-staging-detail-sheet')
export class SsStagingDetailSheet extends LitElement {
  @property({ attribute: false })
  hass?: HomeAssistant;

  @property({ attribute: false })
  config: SplitsmartConfig | null = null;

  @property({ type: String })
  stagingId = '';

  @state()
  private _row: StagingRow | null = null;

  // ---- form state ----
  @state()
  private _paidBy = '';

  @state()
  private _homeAmount = 0;

  @state()
  private _category = '';

  @state()
  private _split: Split = { method: 'equal', shares: [] };

  @state()
  private _multiCategory = false;

  @state()
  private _allocations: AllocationRow[] = [];

  @state()
  private _overrideDesc = '';

  @state()
  private _overrideDate = '';

  @state()
  private _notes = '';

  // ---- action state ----
  @state()
  private _promoting = false;

  @state()
  private _skipping = false;

  @state()
  private _draftingRule = false;

  @state()
  private _error: string | null = null;

  @state()
  private _ruleResult: DraftRuleResult | null = null;

  private _subUnsub: (() => void) | null = null;
  private _initialized = false;

  protected async updated(changed: PropertyValues) {
    const hassChanged = changed.has('hass');
    const idChanged = changed.has('stagingId');

    if ((hassChanged || idChanged) && this.hass && this.stagingId) {
      this._subUnsub?.();
      this._subUnsub = null;
      this._initialized = false;
      this._subUnsub = await subscribeStaging(this.hass, (ev: StagingEvent) =>
        this._onEvent(ev),
      );
    }
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._subUnsub?.();
    this._subUnsub = null;
  }

  private _onEvent(ev: StagingEvent) {
    if (ev.kind === 'init') {
      const found = ev.rows.find((r) => r.id === this.stagingId) ?? null;
      this._row = found;
      if (found && !this._initialized) this._initForm(found);
      return;
    }

    const deleted = new Set(ev.deleted);
    if (deleted.has(this.stagingId)) {
      this._row = null;
      return;
    }

    const updated = [...ev.added, ...ev.updated].find((r) => r.id === this.stagingId);
    if (updated) {
      this._row = updated;
      if (!this._initialized) this._initForm(updated);
    }
  }

  private _initForm(row: StagingRow) {
    const active = this._activeParticipants();
    this._paidBy = row.uploaded_by;
    this._homeAmount = this._isForeignRow(row) ? 0 : row.amount;
    this._category = row.category_hint ?? this.config?.categories[0] ?? '';
    this._split = makeDefaultSplit('equal', active);
    this._multiCategory = false;
    this._allocations = [];
    this._overrideDesc = '';
    this._overrideDate = '';
    this._notes = '';
    this._error = null;
    this._ruleResult = null;
    this._initialized = true;
  }

  private _activeParticipants(): Participant[] {
    return (this.config?.participants ?? []).filter((p) => p.active);
  }

  private _isForeignRow(row: StagingRow): boolean {
    return row.currency !== (this.config?.home_currency ?? 'GBP');
  }

  private _close() {
    this.dispatchEvent(new CustomEvent('close', { bubbles: true, composed: true }));
  }

  private _buildCategories(): CategoryAllocation[] {
    if (!this._multiCategory) {
      return [{ name: this._category, home_amount: this._homeAmount, split: this._split }];
    }
    return this._allocations.map((a) => ({
      name: a.name,
      home_amount: a.home_amount,
      split: this._split,
    }));
  }

  private _isValid(): boolean {
    if (!this.hass || !this._row || !this._paidBy) return false;
    if (this._homeAmount <= 0) return false;
    if (!this._multiCategory) {
      return this._category.length > 0 && isSplitValid(this._split, this._homeAmount);
    }
    if (this._allocations.length === 0) return false;
    const sum = ROUND(this._allocations.reduce((acc, r) => acc + r.home_amount, 0));
    return Math.abs(sum - this._homeAmount) < 0.01 && isSplitValid(this._split, this._homeAmount);
  }

  private async _promote() {
    if (!this.hass || !this._row || !this._isValid() || this._promoting) return;
    this._promoting = true;
    this._error = null;
    try {
      await promoteStaging(this.hass, {
        staging_id: this._row.id,
        paid_by: this._paidBy,
        categories: this._buildCategories(),
        notes: this._notes || null,
        override_description: this._overrideDesc || null,
        override_date: this._overrideDate || null,
      });
      this._close();
    } catch (err) {
      this._error = err instanceof Error ? err.message : String(err);
    } finally {
      this._promoting = false;
    }
  }

  private async _skip() {
    if (!this.hass || !this._row || this._skipping) return;
    this._skipping = true;
    this._error = null;
    try {
      await skipStaging(this.hass, this._row.id);
      this._close();
    } catch (err) {
      this._error = err instanceof Error ? err.message : String(err);
    } finally {
      this._skipping = false;
    }
  }

  private async _draftRule(action: 'always_split' | 'always_ignore' | 'review_each_time') {
    if (!this.hass || !this._row || this._draftingRule) return;
    this._draftingRule = true;
    this._error = null;
    try {
      this._ruleResult = await draftRuleFromRow(this.hass, {
        staging_id: this._row.id,
        action,
      });
    } catch (err) {
      this._error = err instanceof Error ? err.message : String(err);
    } finally {
      this._draftingRule = false;
    }
  }

  private _renderForm() {
    const row = this._row!;
    const active = this._activeParticipants();
    const isForeign = this._isForeignRow(row);
    const homeCurrency = this.config?.home_currency ?? 'GBP';
    const categories = this.config?.categories ?? [];

    return html`
      <div class="form">
        ${isForeign
          ? html`
              <div class="fx-banner ss-text-caption">
                Foreign-currency row: ${row.amount.toFixed(2)} ${row.currency}. Enter the
                equivalent amount in ${homeCurrency} below to promote.
              </div>
            `
          : ''}

        <div class="field">
          <label class="ss-text-caption field-label">Paid by</label>
          <select
            class="select ss-text-body"
            @change=${(e: Event) => {
              this._paidBy = (e.target as HTMLSelectElement).value;
            }}
          >
            ${active.map(
              (p) =>
                html`<option value=${p.user_id} ?selected=${p.user_id === this._paidBy}>
                  ${p.display_name}
                </option>`,
            )}
          </select>
        </div>

        ${isForeign
          ? html`
              <div class="field">
                <label class="ss-text-caption field-label">Home amount (${homeCurrency})</label>
                <input
                  class="text-input ss-mono-amount"
                  type="number"
                  step="0.01"
                  min="0"
                  .value=${String(this._homeAmount || '')}
                  @input=${(e: Event) => {
                    this._homeAmount = Number((e.target as HTMLInputElement).value) || 0;
                  }}
                />
              </div>
            `
          : ''}

        ${!this._multiCategory
          ? html`
              <div class="field">
                <label class="ss-text-caption field-label">Category</label>
                <ss-category-picker
                  .options=${categories}
                  .value=${this._category}
                  @ss-change=${(e: CustomEvent) => {
                    this._category = e.detail.value as string;
                  }}
                ></ss-category-picker>
              </div>
              <div class="field">
                <label class="ss-text-caption field-label">Split</label>
                <ss-split-picker
                  .participants=${active}
                  .allocationAmount=${this._homeAmount}
                  .value=${this._split}
                  .currency=${homeCurrency}
                  @ss-change=${(e: CustomEvent) => {
                    this._split = e.detail.value as Split;
                  }}
                ></ss-split-picker>
              </div>
              <ss-button
                variant="secondary"
                @click=${() => {
                  this._multiCategory = true;
                  this._allocations = [{ name: this._category, home_amount: this._homeAmount }];
                }}
              >
                Split across categories
              </ss-button>
            `
          : html`
              <div class="field">
                <label class="ss-text-caption field-label">Category amounts</label>
                <ss-allocation-editor
                  .categories=${categories}
                  .total=${this._homeAmount}
                  .value=${this._allocations}
                  .currency=${homeCurrency}
                  @ss-change=${(e: CustomEvent) => {
                    this._allocations = e.detail.value as AllocationRow[];
                  }}
                ></ss-allocation-editor>
              </div>
              <div class="field">
                <label class="ss-text-caption field-label">Split (all categories)</label>
                <ss-split-picker
                  .participants=${active}
                  .allocationAmount=${this._homeAmount}
                  .value=${this._split}
                  .currency=${homeCurrency}
                  @ss-change=${(e: CustomEvent) => {
                    this._split = e.detail.value as Split;
                  }}
                ></ss-split-picker>
              </div>
              <ss-button
                variant="secondary"
                @click=${() => {
                  this._multiCategory = false;
                }}
              >
                Single category
              </ss-button>
            `}

        <details class="overrides">
          <summary class="ss-text-caption overrides-label">Override description, date, or notes</summary>
          <div class="overrides-body">
            <div class="field">
              <label class="ss-text-caption field-label">Description</label>
              <input
                class="text-input ss-text-body"
                type="text"
                .placeholder=${row.description ?? ''}
                .value=${this._overrideDesc}
                @input=${(e: Event) => {
                  this._overrideDesc = (e.target as HTMLInputElement).value;
                }}
              />
            </div>
            <div class="field">
              <label class="ss-text-caption field-label">Date</label>
              <input
                class="text-input ss-text-body"
                type="date"
                .placeholder=${row.date ?? ''}
                .value=${this._overrideDate}
                @input=${(e: Event) => {
                  this._overrideDate = (e.target as HTMLInputElement).value;
                }}
              />
            </div>
            <div class="field">
              <label class="ss-text-caption field-label">Notes</label>
              <textarea
                class="textarea ss-text-body"
                rows="2"
                .value=${this._notes}
                @input=${(e: Event) => {
                  this._notes = (e.target as HTMLTextAreaElement).value;
                }}
              ></textarea>
            </div>
          </div>
        </details>

        <details class="metadata">
          <summary class="ss-text-caption metadata-label">Import metadata</summary>
          <dl class="metadata-list">
            ${row.source_preset
              ? html`<div class="meta-row">
                  <dt class="ss-text-caption">Source</dt>
                  <dd class="ss-text-caption">${row.source_preset}</dd>
                </div>`
              : ''}
            ${row.source_ref
              ? html`<div class="meta-row">
                  <dt class="ss-text-caption">Ref</dt>
                  <dd class="ss-text-caption mono">${row.source_ref}</dd>
                </div>`
              : ''}
            ${row.dedup_hash
              ? html`<div class="meta-row">
                  <dt class="ss-text-caption">Dedup</dt>
                  <dd class="ss-text-caption mono">${row.dedup_hash.slice(0, 16)}…</dd>
                </div>`
              : ''}
          </dl>
        </details>

        ${this._error
          ? html`<div class="error ss-text-body">${this._error}</div>`
          : ''}

        <div class="rule-section">
          <div class="ss-text-caption rule-label">Create a rule for similar rows</div>
          <div class="rule-actions">
            <ss-button
              variant="secondary"
              .disabled=${this._draftingRule}
              @click=${() => this._draftRule('always_split')}
            >Always split</ss-button>
            <ss-button
              variant="secondary"
              .disabled=${this._draftingRule}
              @click=${() => this._draftRule('always_ignore')}
            >Always ignore</ss-button>
            <ss-button
              variant="secondary"
              .disabled=${this._draftingRule}
              @click=${() => this._draftRule('review_each_time')}
            >Review each time</ss-button>
          </div>
        </div>
      </div>
    `;
  }

  render() {
    const row = this._row;
    const heading = row?.description ?? (row ? 'Staging row' : 'Loading…');

    return html`
      <ss-modal .open=${true} .heading=${heading} @close=${this._close}>
        ${row === null && this.stagingId
          ? html`<div class="loading ss-text-caption">Loading row…</div>`
          : row === null
            ? html`<div class="loading ss-text-caption">Row not found.</div>`
            : this._renderForm()}

        <ss-button
          slot="footer"
          variant="secondary"
          .disabled=${this._skipping || !row}
          @click=${this._skip}
        >
          ${this._skipping ? 'Skipping…' : 'Skip'}
        </ss-button>
        <ss-button
          slot="footer"
          variant="primary"
          .disabled=${!this._isValid() || this._promoting}
          @click=${this._promote}
        >
          ${this._promoting ? 'Promoting…' : 'Promote to expense'}
        </ss-button>
      </ss-modal>

      ${this._ruleResult
        ? html`
            <ss-rule-snippet-sheet
              .yamlSnippet=${this._ruleResult.yaml_snippet}
              .draftId=${this._ruleResult.draft.id}
              @close=${() => {
                this._ruleResult = null;
              }}
            ></ss-rule-snippet-sheet>
          `
        : ''}
    `;
  }

  static styles = [
    baseStyles,
    typography,
    css`
      :host {
        display: contents;
      }
      .loading {
        padding: var(--ss-space-4);
        color: var(--secondary-text-color, #5a5a5a);
        text-align: center;
      }
      .form {
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-4);
      }
      .fx-banner {
        padding: var(--ss-space-2) var(--ss-space-3);
        background: color-mix(in srgb, var(--info-color, #0288d1) 12%, transparent);
        color: var(--info-color, #0288d1);
        border-radius: 6px;
      }
      .field {
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-2);
      }
      .field-label {
        color: var(--secondary-text-color, #5a5a5a);
      }
      .select,
      .text-input,
      .textarea {
        min-height: var(--ss-touch-min);
        padding: var(--ss-space-2) var(--ss-space-3);
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 8px;
        background: var(--card-background-color, #ffffff);
        color: var(--primary-text-color, #1a1a1a);
        font-family: var(--ss-font-sans);
        font-size: inherit;
        width: 100%;
        box-sizing: border-box;
      }
      .select:focus,
      .text-input:focus,
      .textarea:focus {
        outline: 2px solid var(--primary-color, #03a9f4);
        outline-offset: 1px;
      }
      .textarea {
        resize: vertical;
        min-height: 56px;
      }
      .overrides,
      .metadata {
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 8px;
      }
      .overrides-label,
      .metadata-label {
        display: block;
        padding: var(--ss-space-2) var(--ss-space-3);
        color: var(--secondary-text-color, #5a5a5a);
        cursor: pointer;
      }
      .overrides-body {
        padding: var(--ss-space-3);
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-3);
        border-top: 1px solid var(--divider-color, #e0e0e0);
      }
      .metadata-list {
        margin: 0;
        padding: var(--ss-space-3);
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-2);
        border-top: 1px solid var(--divider-color, #e0e0e0);
      }
      .meta-row {
        display: flex;
        gap: var(--ss-space-3);
      }
      .meta-row dt {
        color: var(--secondary-text-color, #5a5a5a);
        min-width: 60px;
        flex-shrink: 0;
      }
      .meta-row dd {
        margin: 0;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .mono {
        font-family: var(--ss-font-mono);
      }
      .error {
        padding: var(--ss-space-3);
        border-radius: 8px;
        background: color-mix(in srgb, var(--error-color, #db4437) 10%, transparent);
        color: var(--error-color, #db4437);
      }
      .rule-section {
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-2);
        padding-top: var(--ss-space-2);
        border-top: 1px solid var(--divider-color, #e0e0e0);
      }
      .rule-label {
        color: var(--secondary-text-color, #5a5a5a);
      }
      .rule-actions {
        display: flex;
        flex-wrap: wrap;
        gap: var(--ss-space-2);
      }
    `,
  ];
}

declare global {
  interface HTMLElementTagNameMap {
    'ss-staging-detail-sheet': SsStagingDetailSheet;
  }
}
