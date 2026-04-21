import { describe, it, expect } from 'vitest';
import { fixture, html } from '@open-wc/testing-helpers';
import '../../src/components/user-avatar';
import { initialsFor, tintFor } from '../../src/components/user-avatar';
import type { SsUserAvatar } from '../../src/components/user-avatar';

describe('initialsFor', () => {
  it('picks first initial for a single-word name', () => {
    expect(initialsFor('Chris')).toBe('C');
  });

  it('picks first + last for a multi-word name', () => {
    expect(initialsFor('Chris Doyle')).toBe('CD');
    expect(initialsFor('Mary Jane Watson')).toBe('MW');
  });

  it('returns ? for empty / whitespace', () => {
    expect(initialsFor('')).toBe('?');
    expect(initialsFor('   ')).toBe('?');
  });

  it('uppercases lowercase input', () => {
    expect(initialsFor('chris')).toBe('C');
    expect(initialsFor('chris doyle')).toBe('CD');
  });
});

describe('tintFor', () => {
  it('is deterministic for the same user_id', () => {
    expect(tintFor('user_abc')).toBe(tintFor('user_abc'));
  });

  it('returns a hex colour string', () => {
    expect(tintFor('user_abc')).toMatch(/^#[0-9a-fA-F]{6}$/);
  });
});

describe('ss-user-avatar', () => {
  it('renders initials from the name', async () => {
    const el = await fixture<SsUserAvatar>(
      html`<ss-user-avatar name="Chris" user-id="abc"></ss-user-avatar>`,
    );
    const span = el.shadowRoot!.querySelector<HTMLSpanElement>('.avatar')!;
    expect(span.textContent?.trim()).toBe('C');
  });

  it('applies former attribute reflection', async () => {
    const el = await fixture<SsUserAvatar>(
      html`<ss-user-avatar name="Chris" user-id="abc" former></ss-user-avatar>`,
    );
    expect(el.hasAttribute('former')).toBe(true);
  });

  it('label reflects former state', async () => {
    const el = await fixture<SsUserAvatar>(
      html`<ss-user-avatar name="Chris" user-id="abc" former></ss-user-avatar>`,
    );
    const span = el.shadowRoot!.querySelector<HTMLSpanElement>('.avatar')!;
    expect(span.getAttribute('aria-label')).toBe('Chris (former participant)');
  });
});
