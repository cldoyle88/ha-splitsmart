import { describe, it, expect } from 'vitest';
import { fixture, html } from '@open-wc/testing-helpers';
import '../../src/components/placeholder-tile';
import type { SsPlaceholderTile } from '../../src/components/placeholder-tile';

describe('ss-placeholder-tile', () => {
  it('renders title + milestone badge', async () => {
    const el = await fixture<SsPlaceholderTile>(
      html`<ss-placeholder-tile
        title="Pending review"
        milestone="M5"
      ></ss-placeholder-tile>`,
    );
    const text = el.shadowRoot!.textContent ?? '';
    expect(text).toContain('Pending review');
    expect(text).toContain('Coming in M5');
  });

  it('falls back to "Coming soon" when no milestone', async () => {
    const el = await fixture<SsPlaceholderTile>(
      html`<ss-placeholder-tile title="TBD"></ss-placeholder-tile>`,
    );
    expect(el.shadowRoot!.textContent).toContain('Coming soon');
  });

  it('marks the tile aria-disabled', async () => {
    const el = await fixture<SsPlaceholderTile>(
      html`<ss-placeholder-tile title="X" milestone="M5"></ss-placeholder-tile>`,
    );
    const tile = el.shadowRoot!.querySelector('.tile');
    expect(tile?.getAttribute('aria-disabled')).toBe('true');
  });
});
