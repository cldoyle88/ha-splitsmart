import { describe, it, expect, beforeEach } from 'vitest';
import { fixture, html } from '@open-wc/testing-helpers';
import '../../src/components/modal';
import type { SsModal } from '../../src/components/modal';

describe('ss-modal', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('renders nothing when closed', async () => {
    const el = await fixture<SsModal>(html`<ss-modal heading="X"></ss-modal>`);
    expect(el.shadowRoot!.querySelector('.backdrop')).toBeNull();
  });

  it('renders a dialog with heading when open', async () => {
    const el = await fixture<SsModal>(html`<ss-modal .open=${true} heading="Details"></ss-modal>`);
    const dialog = el.shadowRoot!.querySelector('[role="dialog"]');
    expect(dialog).toBeTruthy();
    expect(el.shadowRoot!.textContent).toContain('Details');
  });

  it('dispatches close when the close button is clicked', async () => {
    const el = await fixture<SsModal>(html`<ss-modal .open=${true} heading="X"></ss-modal>`);
    let fired = false;
    el.addEventListener('close', () => (fired = true));
    const btn = el.shadowRoot!.querySelector<HTMLButtonElement>('.icon-button')!;
    btn.click();
    expect(fired).toBe(true);
  });

  it('dispatches close when backdrop is clicked', async () => {
    const el = await fixture<SsModal>(html`<ss-modal .open=${true} heading="X"></ss-modal>`);
    let fired = false;
    el.addEventListener('close', () => (fired = true));
    const backdrop = el.shadowRoot!.querySelector<HTMLDivElement>('.backdrop')!;
    backdrop.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(fired).toBe(true);
  });

  it('dispatches close on Escape', async () => {
    const el = await fixture<SsModal>(html`<ss-modal .open=${true} heading="X"></ss-modal>`);
    let fired = false;
    el.addEventListener('close', () => (fired = true));
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(fired).toBe(true);
  });

  it('shows back chevron when show-back is set', async () => {
    const el = await fixture<SsModal>(
      html`<ss-modal .open=${true} heading="X" show-back></ss-modal>`,
    );
    const label = el.shadowRoot!.querySelector<HTMLButtonElement>('.icon-button')!.ariaLabel;
    expect(label).toBe('Back');
  });
});
