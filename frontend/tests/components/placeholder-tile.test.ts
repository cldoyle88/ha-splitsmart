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

  // ---- M3 pendingCount override ----

  it('renders plural caption for pendingCount > 1', async () => {
    const el = await fixture<SsPlaceholderTile>(
      html`<ss-placeholder-tile
        title="Pending review"
        milestone="M5"
        caption="original caption"
        .pendingCount=${3}
      ></ss-placeholder-tile>`,
    );
    const text = el.shadowRoot!.textContent ?? '';
    expect(text).toContain('You have 3 rows to review');
    expect(text).not.toContain('original caption');
  });

  it('renders singular caption for pendingCount === 1', async () => {
    const el = await fixture<SsPlaceholderTile>(
      html`<ss-placeholder-tile
        title="Pending review"
        milestone="M5"
        .pendingCount=${1}
      ></ss-placeholder-tile>`,
    );
    expect(el.shadowRoot!.textContent).toContain('You have 1 row to review');
  });

  it('renders "all caught up" when pendingCount === 0', async () => {
    const el = await fixture<SsPlaceholderTile>(
      html`<ss-placeholder-tile
        title="Pending review"
        milestone="M5"
        .pendingCount=${0}
      ></ss-placeholder-tile>`,
    );
    expect(el.shadowRoot!.textContent).toContain("You're all caught up");
  });

  it('falls back to static caption when pendingCount is null', async () => {
    const el = await fixture<SsPlaceholderTile>(
      html`<ss-placeholder-tile
        title="Pending review"
        milestone="M5"
        caption="original caption"
        .pendingCount=${null}
      ></ss-placeholder-tile>`,
    );
    expect(el.shadowRoot!.textContent).toContain('original caption');
  });

  it('keeps the "Coming in M5" badge even when pendingCount is set', async () => {
    const el = await fixture<SsPlaceholderTile>(
      html`<ss-placeholder-tile
        title="Pending review"
        milestone="M5"
        .pendingCount=${5}
      ></ss-placeholder-tile>`,
    );
    expect(el.shadowRoot!.textContent).toContain('Coming in M5');
  });

  it('stays non-interactive (aria-disabled) even with a live count', async () => {
    const el = await fixture<SsPlaceholderTile>(
      html`<ss-placeholder-tile
        title="Pending review"
        milestone="M5"
        .pendingCount=${5}
      ></ss-placeholder-tile>`,
    );
    const tile = el.shadowRoot!.querySelector('.tile');
    expect(tile?.getAttribute('aria-disabled')).toBe('true');
  });
});
