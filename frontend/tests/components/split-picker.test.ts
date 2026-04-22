import { describe, it, expect } from 'vitest';
import { isSplitValid, makeDefaultSplit } from '../../src/components/split-picker';
import type { Participant } from '../../src/types';

const pair: Participant[] = [
  { user_id: 'u1', display_name: 'Chris', active: true },
  { user_id: 'u2', display_name: 'Slav', active: true },
];

describe('makeDefaultSplit', () => {
  it('equal splits 100 across N', () => {
    const s = makeDefaultSplit('equal', pair);
    expect(s.method).toBe('equal');
    expect(s.shares.map((x) => x.value)).toEqual([50, 50]);
  });

  it('shares defaults to 1 each', () => {
    const s = makeDefaultSplit('shares', pair);
    expect(s.shares.every((x) => x.value === 1)).toBe(true);
  });

  it('percentage defaults to 0s', () => {
    const s = makeDefaultSplit('percentage', pair);
    expect(s.shares.every((x) => x.value === 0)).toBe(true);
  });

  it('exact defaults to 0s', () => {
    const s = makeDefaultSplit('exact', pair);
    expect(s.shares.every((x) => x.value === 0)).toBe(true);
  });
});

describe('isSplitValid', () => {
  it('equal 50/50 is valid', () => {
    expect(
      isSplitValid(
        { method: 'equal', shares: [{ user_id: 'u1', value: 50 }, { user_id: 'u2', value: 50 }] },
        100,
      ),
    ).toBe(true);
  });

  it('all-zero equal is invalid', () => {
    expect(
      isSplitValid(
        { method: 'equal', shares: [{ user_id: 'u1', value: 0 }, { user_id: 'u2', value: 0 }] },
        100,
      ),
    ).toBe(false);
  });

  it('exact matching allocation is valid', () => {
    expect(
      isSplitValid(
        { method: 'exact', shares: [{ user_id: 'u1', value: 8.5 }, { user_id: 'u2', value: 0 }] },
        8.5,
      ),
    ).toBe(true);
  });

  it('exact sum off by 1p is invalid', () => {
    expect(
      isSplitValid(
        { method: 'exact', shares: [{ user_id: 'u1', value: 8.4 }, { user_id: 'u2', value: 0 }] },
        8.5,
      ),
    ).toBe(false);
  });

  it('empty shares is invalid', () => {
    expect(isSplitValid({ method: 'equal', shares: [] }, 100)).toBe(false);
  });
});
