import { describe, it, expect } from 'vitest';
import { fixture, html } from '@open-wc/testing-helpers';
import '../../src/components/icon';
import type { SsIcon } from '../../src/components/icon';

describe('ss-icon', () => {
  it('passes name through to ha-icon', async () => {
    const el = await fixture<SsIcon>(html`<ss-icon name="mdi:plus"></ss-icon>`);
    const ha = el.shadowRoot!.querySelector('ha-icon') as unknown as { icon: string };
    expect(ha.icon).toBe('mdi:plus');
  });

  it('defaults to presentation role when no label', async () => {
    const el = await fixture<SsIcon>(html`<ss-icon name="mdi:plus"></ss-icon>`);
    const ha = el.shadowRoot!.querySelector('ha-icon')!;
    expect(ha.getAttribute('role')).toBe('presentation');
    expect(ha.getAttribute('aria-hidden')).toBe('true');
  });

  it('promotes to img role when aria-label given', async () => {
    const el = await fixture<SsIcon>(html`<ss-icon name="mdi:plus" aria-label="Add"></ss-icon>`);
    const ha = el.shadowRoot!.querySelector('ha-icon')!;
    expect(ha.getAttribute('role')).toBe('img');
    expect(ha.getAttribute('aria-label')).toBe('Add');
    expect(ha.getAttribute('aria-hidden')).toBe('false');
  });
});
