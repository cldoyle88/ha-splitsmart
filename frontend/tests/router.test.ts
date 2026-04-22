import { describe, it, expect, beforeEach, vi } from 'vitest';
import { parseHash, serialise, subscribeRoute, navigate } from '../src/router';

describe('parseHash', () => {
  it('returns home for empty string', () => {
    expect(parseHash('')).toEqual({ view: 'home', query: {} });
  });

  it('returns home for just #', () => {
    expect(parseHash('#')).toEqual({ view: 'home', query: {} });
  });

  it('parses home', () => {
    expect(parseHash('#home')).toEqual({ view: 'home', query: {} });
  });

  it('parses ledger without query', () => {
    expect(parseHash('#ledger')).toEqual({ view: 'ledger', query: {} });
  });

  it('parses ledger with query', () => {
    expect(parseHash('#ledger?month=2026-04&category=Groceries')).toEqual({
      view: 'ledger',
      query: { month: '2026-04', category: 'Groceries' },
    });
  });

  it('parses expense/<id>', () => {
    expect(parseHash('#expense/ex_01J9X')).toEqual({
      view: 'expense',
      param: 'ex_01J9X',
      query: {},
    });
  });

  it('parses settlement/<id>', () => {
    expect(parseHash('#settlement/sl_01J9X')).toEqual({
      view: 'settlement',
      param: 'sl_01J9X',
      query: {},
    });
  });

  it('falls back to home on unknown view', () => {
    expect(parseHash('#mystery')).toEqual({ view: 'home', query: {} });
  });

  it('falls back to home on expense without id', () => {
    expect(parseHash('#expense')).toEqual({ view: 'home', query: {} });
  });

  it('decodes percent-encoded query values', () => {
    expect(parseHash('#ledger?category=Eating%20out')).toEqual({
      view: 'ledger',
      query: { category: 'Eating out' },
    });
  });

  it('accepts input without leading #', () => {
    expect(parseHash('ledger')).toEqual({ view: 'ledger', query: {} });
  });
});

describe('serialise', () => {
  it('home with no query', () => {
    expect(serialise({ view: 'home', query: {} })).toBe('home');
  });

  it('ledger with query', () => {
    expect(serialise({ view: 'ledger', query: { month: '2026-04' } })).toBe(
      'ledger?month=2026-04',
    );
  });

  it('encodes special characters in query values', () => {
    expect(serialise({ view: 'ledger', query: { category: 'Eating out' } })).toBe(
      'ledger?category=Eating%20out',
    );
  });

  it('expense with param', () => {
    expect(serialise({ view: 'expense', param: 'ex_01', query: {} })).toBe(
      'expense/ex_01',
    );
  });

  it('skips empty query values', () => {
    expect(serialise({ view: 'ledger', query: { month: '', category: 'X' } })).toBe(
      'ledger?category=X',
    );
  });

  it('round-trips via parseHash', () => {
    const r = { view: 'ledger' as const, query: { month: '2026-04', category: 'Food & Drink' } };
    expect(parseHash(serialise(r))).toEqual(r);
  });
});

describe('subscribeRoute', () => {
  beforeEach(() => {
    window.location.hash = '';
  });

  it('fires with the initial route synchronously', () => {
    window.location.hash = '#ledger';
    const cb = vi.fn();
    const unsub = subscribeRoute(cb);
    expect(cb).toHaveBeenCalledTimes(1);
    expect(cb.mock.calls[0]![0]).toEqual({ view: 'ledger', query: {} });
    unsub();
  });

  it('fires on hashchange', () => {
    const cb = vi.fn();
    const unsub = subscribeRoute(cb);
    cb.mockClear();
    window.location.hash = '#add';
    window.dispatchEvent(new HashChangeEvent('hashchange'));
    expect(cb).toHaveBeenCalledTimes(1);
    expect(cb.mock.calls[0]![0]).toEqual({ view: 'add', query: {} });
    unsub();
  });

  it('stops firing after unsubscribe', () => {
    const cb = vi.fn();
    const unsub = subscribeRoute(cb);
    cb.mockClear();
    unsub();
    window.location.hash = '#ledger';
    window.dispatchEvent(new HashChangeEvent('hashchange'));
    expect(cb).not.toHaveBeenCalled();
  });
});

describe('navigate', () => {
  beforeEach(() => {
    window.location.hash = '';
  });

  it('assigns string directly', () => {
    navigate('ledger?month=2026-04');
    expect(window.location.hash).toBe('#ledger?month=2026-04');
  });

  it('serialises Route', () => {
    navigate({ view: 'add', query: {} });
    expect(window.location.hash).toBe('#add');
  });
});
