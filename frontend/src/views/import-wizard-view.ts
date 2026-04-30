// <ss-import-wizard-view
//    .hass=${hass}
//    .config=${splitsmartConfig}
//    .uploadId=${"abc123"}
// ></ss-import-wizard-view>
//
// Three-step column-mapping wizard, shown when the file importer cannot
// identify a preset or saved mapping for an uploaded file.
//
// Step 1 — Preview:  header row + up to 5 sample rows.
// Step 2 — Roles:    per-column role picker + currency default + amount sign.
// Step 3 — Commit:   saves the mapping then calls splitsmart.import_file.
//
// On success, navigates to #staging so the user can review imported rows.
// The wizard guards against committing until at least date + description +
// (amount or debit+credit) columns are assigned.

import { LitElement, html, css, type PropertyValues } from 'lit';
import { customElement, property, state } from 'lit/decorators.js';
import { baseStyles, typography } from '../styles';
import { importFile, inspectUpload, saveMapping } from '../api';
import type { ColumnMapping, ColumnRole, FileInspection, HomeAssistant, SplitsmartConfig } from '../types';
import '../components/button';
import '../components/column-role-picker';

type WizardStep = 1 | 2 | 3;

function defaultRoles(headers: string[]): Record<string, ColumnRole | 'ignore'> {
  const roles: Record<string, ColumnRole | 'ignore'> = {};
  for (const h of headers) {
    const lower = h.toLowerCase();
    if (/^date|^time|^transaction.?date/.test(lower)) {
      roles[h] = 'date';
    } else if (/desc|merchant|narrative|reference|payee/.test(lower)) {
      roles[h] = 'description';
    } else if (/^amount$|^value$|^net/.test(lower)) {
      roles[h] = 'amount';
    } else if (/debit|out/.test(lower)) {
      roles[h] = 'debit';
    } else if (/credit|in/.test(lower)) {
      roles[h] = 'credit';
    } else if (/curr/.test(lower)) {
      roles[h] = 'currency';
    } else {
      roles[h] = 'ignore';
    }
  }
  return roles;
}

function isReadyToCommit(
  roles: Record<string, ColumnRole | 'ignore'>,
): boolean {
  const assigned = Object.values(roles);
  const hasDate = assigned.includes('date');
  const hasDesc = assigned.includes('description');
  const hasAmount = assigned.includes('amount') ||
    (assigned.includes('debit') && assigned.includes('credit'));
  return hasDate && hasDesc && hasAmount;
}

@customElement('ss-import-wizard-view')
export class SsImportWizardView extends LitElement {
  @property({ attribute: false })
  hass?: HomeAssistant;

  @property({ attribute: false })
  config: SplitsmartConfig | null = null;

  @property({ type: String })
  uploadId = '';

  @state()
  private _step: WizardStep = 1;

  @state()
  private _inspection: FileInspection | null = null;

  @state()
  private _loading = true;

  @state()
  private _loadError: string | null = null;

  @state()
  private _roles: Record<string, ColumnRole | 'ignore'> = {};

  @state()
  private _currencyDefault = '';

  @state()
  private _amountSign: 'positive' | 'negative' | 'credit_debit' = 'negative';

  @state()
  private _committing = false;

  @state()
  private _commitError: string | null = null;

  protected async updated(changed: PropertyValues) {
    if ((changed.has('hass') || changed.has('uploadId')) && this.hass && this.uploadId && this._loading) {
      await this._load();
    }
  }

  private async _load() {
    if (!this.hass || !this.uploadId) return;
    this._loading = true;
    this._loadError = null;
    try {
      const inspection = await inspectUpload(this.hass, this.uploadId);
      this._inspection = inspection;
      this._roles = defaultRoles(inspection.headers);
      this._currencyDefault = this.config?.home_currency ?? 'GBP';
    } catch (err) {
      this._loadError = String(err);
    } finally {
      this._loading = false;
    }
  }

  private _navigate(route: string) {
    this.dispatchEvent(
      new CustomEvent('ss-navigate', { detail: { route }, bubbles: true, composed: true }),
    );
  }

  private _onRoleChanged(e: CustomEvent<{ header: string; role: ColumnRole | 'ignore' }>) {
    this._roles = { ...this._roles, [e.detail.header]: e.detail.role };
  }

  private async _commit() {
    if (!this.hass || !this._inspection || this._committing) return;
    this._committing = true;
    this._commitError = null;
    try {
      const mapping: ColumnMapping = {
        columns: this._roles as Record<string, ColumnRole>,
        currency_default: this._currencyDefault || null,
        amount_sign: this._amountSign,
      };
      await saveMapping(this.hass, this._inspection.file_origin_hash, mapping);
      await importFile(this.hass, {
        upload_id: this.uploadId,
        mapping,
        remember_mapping: true,
      });
      this._navigate('staging');
    } catch (err) {
      this._commitError = String(err);
      this._committing = false;
    }
  }

  private _renderStep1() {
    const insp = this._inspection!;
    const cols = insp.headers;
    const rows = insp.sample_rows.slice(0, 5);
    return html`
      <div class="step-content">
        <div class="ss-text-title step-heading">Step 1 of 3 — Preview</div>
        <div class="ss-text-caption step-desc">
          ${insp.filename} · ${insp.row_count} rows detected
        </div>
        <div class="table-wrap">
          <table class="preview-table ss-text-caption">
            <thead>
              <tr>
                ${cols.map((h) => html`<th>${h}</th>`)}
              </tr>
            </thead>
            <tbody>
              ${rows.map(
                (row) => html`
                  <tr>
                    ${cols.map((_, i) => html`<td>${row[i] ?? ''}</td>`)}
                  </tr>
                `,
              )}
            </tbody>
          </table>
        </div>
        <div class="step-actions">
          <ss-button variant="secondary" @click=${() => this._navigate('import')}>Cancel</ss-button>
          <ss-button variant="primary" @click=${() => { this._step = 2; }}>Next →</ss-button>
        </div>
      </div>
    `;
  }

  private _renderStep2() {
    const insp = this._inspection!;
    const ready = isReadyToCommit(this._roles);
    return html`
      <div class="step-content">
        <div class="ss-text-title step-heading">Step 2 of 3 — Assign columns</div>
        <div class="ss-text-caption step-desc">
          Assign a role to each column. At minimum: Date, Description, and Amount (or Debit + Credit).
        </div>

        <div class="role-grid">
          ${insp.headers.map((h, i) => {
            const samples = insp.sample_rows.slice(0, 3).map((r) => r[i] ?? '');
            return html`
              <ss-column-role-picker
                header=${h}
                .samples=${samples}
                .role=${this._roles[h] ?? 'ignore'}
                @role-changed=${this._onRoleChanged}
              ></ss-column-role-picker>
            `;
          })}
        </div>

        <div class="extras">
          <label class="extra-field">
            <span class="ss-text-caption">Default currency (when no currency column)</span>
            <input
              type="text"
              class="text-input ss-text-body"
              maxlength="3"
              .value=${this._currencyDefault}
              @input=${(e: Event) => {
                this._currencyDefault = (e.target as HTMLInputElement).value.toUpperCase();
              }}
            />
          </label>

          <label class="extra-field">
            <span class="ss-text-caption">Amount sign convention</span>
            <select
              class="select-input ss-text-body"
              .value=${this._amountSign}
              @change=${(e: Event) => {
                this._amountSign = (e.target as HTMLSelectElement).value as typeof this._amountSign;
              }}
            >
              <option value="negative">Negative = money out (most banks)</option>
              <option value="positive">Positive = money out</option>
              <option value="credit_debit">Separate debit / credit columns</option>
            </select>
          </label>
        </div>

        <div class="step-actions">
          <ss-button variant="secondary" @click=${() => { this._step = 1; }}>← Back</ss-button>
          <ss-button variant="primary" .disabled=${!ready} @click=${() => { this._step = 3; }}>
            Next →
          </ss-button>
        </div>
        ${!ready
          ? html`<div class="ss-text-caption warn">Assign Date, Description, and Amount columns before continuing.</div>`
          : ''}
      </div>
    `;
  }

  private _renderStep3() {
    const insp = this._inspection!;
    const assigned = Object.entries(this._roles)
      .filter(([, r]) => r !== 'ignore')
      .map(([h, r]) => html`<div class="mapping-row ss-text-caption"><span class="col-name">${h}</span><span class="col-role">${r}</span></div>`);
    return html`
      <div class="step-content">
        <div class="ss-text-title step-heading">Step 3 of 3 — Confirm</div>
        <div class="ss-text-caption step-desc">
          Review the mapping and click Import. The mapping is saved automatically for
          next month's statement from the same source.
        </div>

        <div class="mapping-summary">
          <div class="ss-text-caption mapping-file">${insp.filename}</div>
          ${assigned}
          ${this._currencyDefault
            ? html`<div class="mapping-row ss-text-caption"><span class="col-name">Default currency</span><span class="col-role">${this._currencyDefault}</span></div>`
            : ''}
        </div>

        ${this._commitError
          ? html`<div class="error-msg ss-text-caption">${this._commitError}</div>`
          : ''}

        <div class="step-actions">
          <ss-button variant="secondary" .disabled=${this._committing} @click=${() => { this._step = 2; }}>← Back</ss-button>
          <ss-button variant="primary" .disabled=${this._committing} @click=${this._commit}>
            ${this._committing ? 'Importing…' : 'Import'}
          </ss-button>
        </div>
      </div>
    `;
  }

  render() {
    if (this._loading) {
      return html`<div class="loading ss-text-caption">Loading file preview…</div>`;
    }
    if (this._loadError) {
      return html`
        <div class="container">
          <div class="error-msg ss-text-body">${this._loadError}</div>
          <ss-button variant="secondary" @click=${() => this._navigate('import')}>← Back</ss-button>
        </div>
      `;
    }
    if (!this._inspection) return html``;

    return html`
      <div class="container">
        <div class="toolbar">
          <ss-button variant="secondary" @click=${() => this._navigate('import')}>← Back</ss-button>
          <h2 class="ss-text-title title">Import wizard</h2>
        </div>
        ${this._step === 1 ? this._renderStep1() : ''}
        ${this._step === 2 ? this._renderStep2() : ''}
        ${this._step === 3 ? this._renderStep3() : ''}
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
      .loading {
        padding: var(--ss-space-5);
        color: var(--secondary-text-color, #5a5a5a);
      }
      .step-content {
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-4);
      }
      .step-heading {
        margin: 0;
      }
      .step-desc {
        color: var(--secondary-text-color, #5a5a5a);
      }
      .table-wrap {
        overflow-x: auto;
        border-radius: 8px;
        border: 1px solid var(--divider-color, #e0e0e0);
      }
      .preview-table {
        width: 100%;
        border-collapse: collapse;
      }
      .preview-table th,
      .preview-table td {
        padding: var(--ss-space-2) var(--ss-space-3);
        text-align: left;
        border-bottom: 1px solid var(--divider-color, #e0e0e0);
        white-space: nowrap;
        max-width: 160px;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .preview-table th {
        background: var(--secondary-background-color, #f5f5f5);
        font-weight: 600;
        color: var(--primary-text-color, #1a1a1a);
      }
      .preview-table tr:last-child td {
        border-bottom: none;
      }
      .role-grid {
        display: flex;
        flex-wrap: wrap;
        gap: var(--ss-space-3);
      }
      .extras {
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-3);
      }
      .extra-field {
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-1);
      }
      .text-input,
      .select-input {
        min-height: var(--ss-touch-min);
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 6px;
        background: var(--card-background-color, #ffffff);
        color: var(--primary-text-color, #1a1a1a);
        padding: var(--ss-space-2) var(--ss-space-3);
        font-family: var(--ss-font-sans);
        font-size: var(--ss-text-body-size);
        max-width: 280px;
      }
      .text-input:focus,
      .select-input:focus {
        outline: 2px solid var(--primary-color, #03a9f4);
        outline-offset: 1px;
      }
      .step-actions {
        display: flex;
        gap: var(--ss-space-3);
        flex-wrap: wrap;
      }
      .warn {
        color: var(--warning-color, #f9a825);
      }
      .mapping-summary {
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-1);
        background: var(--secondary-background-color, #f5f5f5);
        border-radius: 8px;
        padding: var(--ss-space-3) var(--ss-space-4);
      }
      .mapping-file {
        font-weight: 600;
        color: var(--primary-text-color, #1a1a1a);
        margin-bottom: var(--ss-space-2);
      }
      .mapping-row {
        display: flex;
        justify-content: space-between;
        gap: var(--ss-space-3);
      }
      .col-name {
        color: var(--secondary-text-color, #5a5a5a);
      }
      .col-role {
        font-weight: 500;
        color: var(--primary-text-color, #1a1a1a);
      }
      .error-msg {
        color: var(--error-color, #db4437);
        background: color-mix(in srgb, var(--error-color, #db4437) 8%, transparent);
        padding: var(--ss-space-2) var(--ss-space-3);
        border-radius: 6px;
      }
    `,
  ];
}

declare global {
  interface HTMLElementTagNameMap {
    'ss-import-wizard-view': SsImportWizardView;
  }
}
