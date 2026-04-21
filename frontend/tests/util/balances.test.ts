import { describe, it, expect } from 'vitest';
import { computeBalances, computePairwise, expenseShares, splitShares } from '../../src/util/balances';
import type { Expense, Settlement } from '../../src/types';

function tescoShop(): Expense {
  // SPEC §9.3 worked example — three categories, mixed split methods.
  return {
    id: 'ex_01',
    created_at: '2026-04-15T12:00:00+00:00',
    created_by: 'u1',
    date: '2026-04-15',
    description: 'Tesco',
    paid_by: 'u1',
    amount: 82.4,
    currency: 'GBP',
    home_amount: 82.4,
    home_currency: 'GBP',
    fx_rate: 1,
    fx_date: '2026-04-15',
    source: 'manual',
    staging_id: null,
    receipt_path: null,
    notes: null,
    comments: [],
    categories: [
      {
        name: 'Groceries',
        home_amount: 55.2,
        split: {
          method: 'equal',
          shares: [
            { user_id: 'u1', value: 50 },
            { user_id: 'u2', value: 50 },
          ],
        },
      },
      {
        name: 'Household',
        home_amount: 18.7,
        split: {
          method: 'equal',
          shares: [
            { user_id: 'u1', value: 50 },
            { user_id: 'u2', value: 50 },
          ],
        },
      },
      {
        name: 'Alcohol',
        home_amount: 8.5,
        split: {
          method: 'exact',
          shares: [
            { user_id: 'u1', value: 8.5 },
            { user_id: 'u2', value: 0 },
          ],
        },
      },
    ],
  };
}

describe('splitShares', () => {
  it('splits 50/50 equal', () => {
    const s = splitShares(
      { method: 'equal', shares: [{ user_id: 'u1', value: 50 }, { user_id: 'u2', value: 50 }] },
      100,
    );
    expect(s).toEqual({ u1: 50, u2: 50 });
  });

  it('exact uses values as absolute amounts', () => {
    const s = splitShares(
      { method: 'exact', shares: [{ user_id: 'u1', value: 8.5 }, { user_id: 'u2', value: 0 }] },
      8.5,
    );
    expect(s).toEqual({ u1: 8.5, u2: 0 });
  });

  it('shares by weights', () => {
    const s = splitShares(
      { method: 'shares', shares: [{ user_id: 'u1', value: 2 }, { user_id: 'u2', value: 1 }] },
      90,
    );
    expect(s.u1).toBeCloseTo(60);
    expect(s.u2).toBeCloseTo(30);
  });

  it('returns empty when shares are all zero (equal/percentage)', () => {
    const s = splitShares(
      { method: 'equal', shares: [{ user_id: 'u1', value: 0 }, { user_id: 'u2', value: 0 }] },
      100,
    );
    expect(s).toEqual({});
  });
});

describe('expenseShares', () => {
  it('matches SPEC §9.3 worked example', () => {
    const shares = expenseShares(tescoShop());
    expect(shares.u1).toBeCloseTo(45.45);
    expect(shares.u2).toBeCloseTo(36.95);
  });
});

describe('computeBalances', () => {
  it('produces the SPEC §9.3 net balances', () => {
    const bal = computeBalances([tescoShop()], []);
    // Chris paid 82.40, owes 45.45 → +36.95.
    // Slav paid 0, owes 36.95 → -36.95.
    expect(bal.u1).toBeCloseTo(36.95);
    expect(bal.u2).toBeCloseTo(-36.95);
  });

  it('settlements reduce the balance', () => {
    const exp = tescoShop();
    const settlement: Settlement = {
      id: 'sl_1',
      created_at: '2026-04-21T12:00:00+00:00',
      created_by: 'u2',
      date: '2026-04-21',
      from_user: 'u2',
      to_user: 'u1',
      amount: 36.95,
      currency: 'GBP',
      home_amount: 36.95,
      notes: null,
    };
    const bal = computeBalances([exp], [settlement]);
    expect(bal.u1).toBeCloseTo(0);
    expect(bal.u2).toBeCloseTo(0);
  });
});

describe('computePairwise', () => {
  it('collapses to a single direction after settlement', () => {
    const exp = tescoShop();
    const pw = computePairwise([exp], []);
    expect(pw.u2!.u1).toBeCloseTo(36.95);
    expect(pw.u1).toBeUndefined();
  });
});
