import { describe, it, expect } from 'vitest';
import { fixture, html } from '@open-wc/testing-helpers';
import '../../src/components/empty-state';
import type { SsEmptyState } from '../../src/components/empty-state';

describe('ss-empty-state', () => {
  it('renders heading and caption', async () => {
    const el = await fixture<SsEmptyState>(
      html`<ss-empty-state
        heading="No expenses yet"
        caption="Add your first expense to get started"
      ></ss-empty-state>`,
    );
    const text = el.shadowRoot!.textContent ?? '';
    expect(text).toContain('No expenses yet');
    expect(text).toContain('Add your first expense to get started');
  });

  it('omits caption when blank', async () => {
    const el = await fixture<SsEmptyState>(
      html`<ss-empty-state heading="No data"></ss-empty-state>`,
    );
    expect(el.shadowRoot!.querySelector('.caption')).toBeNull();
  });

  it('renders icon when provided', async () => {
    const el = await fixture<SsEmptyState>(
      html`<ss-empty-state
        icon="mdi:playlist-check"
        heading="Empty"
      ></ss-empty-state>`,
    );
    expect(el.shadowRoot!.querySelector('.icon-wrap')).toBeTruthy();
  });

  it('slots action buttons', async () => {
    const el = await fixture<SsEmptyState>(
      html`<ss-empty-state heading="X">
        <button slot="action">A</button>
        <button slot="action">B</button>
      </ss-empty-state>`,
    );
    const slot = el.shadowRoot!.querySelector<HTMLSlotElement>('slot[name="action"]')!;
    const assigned = slot.assignedElements();
    expect(assigned.length).toBe(2);
  });
});
