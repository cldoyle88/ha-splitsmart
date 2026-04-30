// <ss-import-view
//    .hass=${hass}
//    .config=${splitsmartConfig}
// ></ss-import-view>
//
// File-upload entry point for the import pipeline. Presents a drag-and-drop
// / browse area, POSTs to /api/splitsmart/upload, then calls
// splitsmart/inspect_upload. If the inspection identifies a known preset or a
// saved mapping the file is imported immediately via splitsmart.import_file;
// otherwise the user is routed to the column-mapping wizard.

import { LitElement, html, css } from 'lit';
import { customElement, property, state } from 'lit/decorators.js';
import { baseStyles, typography } from '../styles';
import { importFile, inspectUpload } from '../api';
import type { HomeAssistant, SplitsmartConfig } from '../types';
import '../components/button';

type UploadState =
  | { kind: 'idle' }
  | { kind: 'uploading'; progress: number }
  | { kind: 'inspecting' }
  | { kind: 'importing' }
  | { kind: 'done'; result: { imported: number; auto_promoted: number; auto_ignored: number; still_pending: number } }
  | { kind: 'error'; message: string };

@customElement('ss-import-view')
export class SsImportView extends LitElement {
  @property({ attribute: false })
  hass?: HomeAssistant;

  @property({ attribute: false })
  config: SplitsmartConfig | null = null;

  @state()
  private _uploadState: UploadState = { kind: 'idle' };

  @state()
  private _dragging = false;

  private _navigate(route: string) {
    this.dispatchEvent(
      new CustomEvent('ss-navigate', { detail: { route }, bubbles: true, composed: true }),
    );
  }

  private _onDragOver(e: DragEvent) {
    e.preventDefault();
    this._dragging = true;
  }

  private _onDragLeave() {
    this._dragging = false;
  }

  private _onDrop(e: DragEvent) {
    e.preventDefault();
    this._dragging = false;
    const file = e.dataTransfer?.files?.[0];
    if (file) this._handleFile(file);
  }

  private _onFileInput(e: Event) {
    const file = (e.target as HTMLInputElement).files?.[0];
    if (file) this._handleFile(file);
  }

  private async _handleFile(file: File) {
    if (!this.hass) return;
    const ext = file.name.split('.').pop()?.toLowerCase() ?? 'csv';
    const allowed = ['csv', 'ofx', 'qfx', 'xlsx'];
    if (!allowed.includes(ext)) {
      this._uploadState = { kind: 'error', message: `Unsupported file type .${ext}. Use CSV, OFX, QFX, or XLSX.` };
      return;
    }

    this._uploadState = { kind: 'uploading', progress: 0 };

    let uploadId: string;
    try {
      uploadId = await this._uploadFile(file);
    } catch (err) {
      this._uploadState = { kind: 'error', message: String(err) };
      return;
    }

    this._uploadState = { kind: 'inspecting' };
    let inspection;
    try {
      inspection = await inspectUpload(this.hass, uploadId);
    } catch (err) {
      this._uploadState = { kind: 'error', message: String(err) };
      return;
    }

    const hasMapping = inspection.preset !== null || inspection.saved_mapping !== null;
    if (!hasMapping) {
      this._navigate(`wizard/${uploadId}`);
      return;
    }

    this._uploadState = { kind: 'importing' };
    try {
      const result = await importFile(this.hass, { upload_id: uploadId });
      this._uploadState = { kind: 'done', result };
    } catch (err) {
      this._uploadState = { kind: 'error', message: String(err) };
    }
  }

  private async _uploadFile(file: File): Promise<string> {
    const formData = new FormData();
    formData.append('file', file);

    const token = (this.hass as unknown as { auth?: { data?: { access_token?: string } } }).auth?.data?.access_token ?? '';
    const resp = await fetch('/api/splitsmart/upload', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: formData,
    });
    if (!resp.ok) {
      const text = await resp.text().catch(() => resp.statusText);
      throw new Error(`Upload failed (${resp.status}): ${text}`);
    }
    const data = (await resp.json()) as { upload_id?: string };
    if (!data.upload_id) throw new Error('Server did not return an upload_id.');
    return data.upload_id;
  }

  private _reset() {
    this._uploadState = { kind: 'idle' };
  }

  private _renderIdle() {
    return html`
      <div
        class="drop-zone ${this._dragging ? 'dragging' : ''}"
        @dragover=${this._onDragOver}
        @dragleave=${this._onDragLeave}
        @drop=${this._onDrop}
        role="button"
        tabindex="0"
        aria-label="Drop a bank statement file here or click to browse"
        @click=${() => (this.shadowRoot?.querySelector<HTMLInputElement>('#file-input'))?.click()}
        @keydown=${(e: KeyboardEvent) => e.key === 'Enter' && (this.shadowRoot?.querySelector<HTMLInputElement>('#file-input'))?.click()}
      >
        <span class="drop-icon" aria-hidden="true">↑</span>
        <div class="ss-text-body drop-label">Drop a statement file here</div>
        <div class="ss-text-caption drop-hint">CSV, OFX, QFX, XLSX · or click to browse</div>
        <input
          id="file-input"
          type="file"
          accept=".csv,.ofx,.qfx,.xlsx"
          hidden
          @change=${this._onFileInput}
        />
      </div>
    `;
  }

  private _renderWorking(label: string) {
    return html`
      <div class="working">
        <div class="ss-text-body">${label}</div>
      </div>
    `;
  }

  private _renderDone(result: Extract<UploadState, { kind: 'done' }>['result']) {
    return html`
      <div class="done">
        <div class="ss-text-title">Import complete</div>
        <dl class="result-list ss-text-body">
          <div class="result-row">
            <dt>Imported</dt>
            <dd>${result.imported}</dd>
          </div>
          <div class="result-row">
            <dt>Auto-split</dt>
            <dd>${result.auto_promoted}</dd>
          </div>
          <div class="result-row">
            <dt>Auto-ignored</dt>
            <dd>${result.auto_ignored}</dd>
          </div>
          <div class="result-row">
            <dt>Pending review</dt>
            <dd>${result.still_pending}</dd>
          </div>
        </dl>
        <div class="done-actions">
          ${result.still_pending > 0
            ? html`<ss-button variant="primary" @click=${() => this._navigate('staging')}>
                Review pending (${result.still_pending})
              </ss-button>`
            : ''}
          <ss-button variant="secondary" @click=${this._reset}>Import another</ss-button>
          <ss-button variant="secondary" @click=${() => this._navigate('home')}>Home</ss-button>
        </div>
      </div>
    `;
  }

  render() {
    const s = this._uploadState;
    return html`
      <div class="container">
        <div class="toolbar">
          <ss-button variant="secondary" @click=${() => this._navigate('home')}>← Back</ss-button>
          <h2 class="ss-text-title title">Import statement</h2>
        </div>

        ${s.kind === 'idle' ? this._renderIdle() : ''}
        ${s.kind === 'uploading' ? this._renderWorking('Uploading…') : ''}
        ${s.kind === 'inspecting' ? this._renderWorking('Inspecting file…') : ''}
        ${s.kind === 'importing' ? this._renderWorking('Importing rows…') : ''}
        ${s.kind === 'done' ? this._renderDone(s.result) : ''}
        ${s.kind === 'error'
          ? html`
              <div class="error-block">
                <div class="ss-text-body error-msg">${s.message}</div>
                <ss-button variant="secondary" @click=${this._reset}>Try again</ss-button>
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
      .drop-zone {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: var(--ss-space-3);
        border: 2px dashed var(--divider-color, #e0e0e0);
        border-radius: 12px;
        padding: var(--ss-space-7) var(--ss-space-4);
        cursor: pointer;
        transition: border-color var(--ss-duration-fast) var(--ss-easing-standard),
                    background-color var(--ss-duration-fast) var(--ss-easing-standard);
        text-align: center;
      }
      .drop-zone:hover,
      .drop-zone.dragging {
        border-color: var(--ss-accent-color);
        background: color-mix(in srgb, var(--ss-accent-color) 6%, transparent);
      }
      .drop-zone:focus-visible {
        outline: 2px solid var(--primary-color, #03a9f4);
        outline-offset: 2px;
      }
      .drop-icon {
        font-size: 32px;
        color: var(--ss-accent-color);
        line-height: 1;
      }
      .drop-hint {
        color: var(--secondary-text-color, #5a5a5a);
      }
      .working {
        display: flex;
        align-items: center;
        justify-content: center;
        padding: var(--ss-space-7);
        color: var(--secondary-text-color, #5a5a5a);
      }
      .done {
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-4);
      }
      .result-list {
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-2);
        margin: 0;
      }
      .result-row {
        display: flex;
        justify-content: space-between;
        padding: var(--ss-space-2) var(--ss-space-3);
        background: var(--secondary-background-color, #f5f5f5);
        border-radius: 6px;
      }
      dt {
        color: var(--secondary-text-color, #5a5a5a);
      }
      dd {
        margin: 0;
        font-weight: 600;
      }
      .done-actions {
        display: flex;
        flex-wrap: wrap;
        gap: var(--ss-space-3);
      }
      .error-block {
        display: flex;
        flex-direction: column;
        gap: var(--ss-space-3);
        padding: var(--ss-space-4);
        border-radius: 8px;
        background: color-mix(in srgb, var(--error-color, #db4437) 8%, transparent);
      }
      .error-msg {
        color: var(--error-color, #db4437);
      }
    `,
  ];
}

declare global {
  interface HTMLElementTagNameMap {
    'ss-import-view': SsImportView;
  }
}
