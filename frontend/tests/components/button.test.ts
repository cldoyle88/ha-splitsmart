import { describe, it, expect } from 'vitest';
import { fixture, html } from '@open-wc/testing-helpers';
import '../../src/components/button';
import type { SsButton } from '../../src/components/button';

describe('ss-button', () => {
  it('renders a native button with the slot content', async () => {
    const el = await fixture<SsButton>(html`<ss-button>Save</ss-button>`);
    const btn = el.shadowRoot!.querySelector('button')!;
    expect(btn).toBeTruthy();
    expect(btn.type).toBe('button');
    expect(el.textContent?.trim()).toBe('Save');
  });

  it('reflects disabled to the native button', async () => {
    const el = await fixture<SsButton>(html`<ss-button disabled>Save</ss-button>`);
    const btn = el.shadowRoot!.querySelector('button')!;
    expect(btn.disabled).toBe(true);
  });

  it('applies variant-destructive when variant="destructive"', async () => {
    const el = await fixture<SsButton>(html`<ss-button variant="destructive">Delete</ss-button>`);
    const btn = el.shadowRoot!.querySelector('button')!;
    expect(btn.classList.contains('variant-destructive')).toBe(true);
  });

  it('defaults to primary variant', async () => {
    const el = await fixture<SsButton>(html`<ss-button>OK</ss-button>`);
    const btn = el.shadowRoot!.querySelector('button')!;
    expect(btn.classList.contains('variant-primary')).toBe(true);
  });

  it('propagates type="submit" so it participates in forms', async () => {
    const el = await fixture<SsButton>(html`<ss-button type="submit">Submit</ss-button>`);
    const btn = el.shadowRoot!.querySelector('button')!;
    expect(btn.type).toBe('submit');
  });
});
