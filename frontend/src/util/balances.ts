// Client-side ledger math — mirrors M1 backend's ledger.py so the card
// can render balances without a server round-trip on every delta.
// Pure functions; no HA or Lit. Tests cover the SPEC §9.3 worked example.

import type { Expense, Settlement, Split } from '../types';

const ROUND = (n: number) => Math.round(n * 100) / 100;

/** Each user's share of a single split in home-currency terms. */
export function splitShares(split: Split, allocationAmount: number): Record<string, number> {
  const out: Record<string, number> = {};
  if (!split || !split.shares || split.shares.length === 0) return out;

  if (split.method === 'exact') {
    for (const s of split.shares) {
      out[s.user_id] = (out[s.user_id] ?? 0) + s.value;
    }
    return out;
  }

  const total = split.shares.reduce((acc, s) => acc + (Number(s.value) || 0), 0);
  if (total <= 0) return out;

  for (const s of split.shares) {
    const portion = (Number(s.value) || 0) / total;
    out[s.user_id] = (out[s.user_id] ?? 0) + allocationAmount * portion;
  }
  return out;
}

/** Sum an expense's per-user share across all its category allocations. */
export function expenseShares(expense: Expense): Record<string, number> {
  const acc: Record<string, number> = {};
  for (const alloc of expense.categories ?? []) {
    const shares = splitShares(alloc.split, alloc.home_amount);
    for (const [uid, amount] of Object.entries(shares)) {
      acc[uid] = (acc[uid] ?? 0) + amount;
    }
  }
  return acc;
}

/**
 * Net balance per user from all expenses + settlements. Positive means
 * the user is owed money, negative means they owe. Mirrors the M1 sign
 * convention in ledger.compute_balances exactly.
 */
export function computeBalances(
  expenses: Expense[],
  settlements: Settlement[],
): Record<string, number> {
  const bal: Record<string, number> = {};

  for (const exp of expenses) {
    bal[exp.paid_by] = (bal[exp.paid_by] ?? 0) + exp.home_amount;
    for (const [uid, owed] of Object.entries(expenseShares(exp))) {
      bal[uid] = (bal[uid] ?? 0) - owed;
    }
  }

  for (const st of settlements) {
    bal[st.from_user] = (bal[st.from_user] ?? 0) + st.home_amount;
    bal[st.to_user] = (bal[st.to_user] ?? 0) - st.home_amount;
  }

  const rounded: Record<string, number> = {};
  for (const [uid, v] of Object.entries(bal)) {
    rounded[uid] = ROUND(v);
  }
  return rounded;
}

/**
 * Directed pairwise debts: result[a][b] = what ``a`` currently owes ``b``.
 * Useful for the Settle-Up form to suggest an amount.
 */
export function computePairwise(
  expenses: Expense[],
  settlements: Settlement[],
): Record<string, Record<string, number>> {
  const debts: Record<string, Record<string, number>> = {};

  const add = (a: string, b: string, amt: number) => {
    if (a === b || amt === 0) return;
    if (!debts[a]) debts[a] = {};
    debts[a]![b] = (debts[a]![b] ?? 0) + amt;
  };

  for (const exp of expenses) {
    for (const [uid, owed] of Object.entries(expenseShares(exp))) {
      if (uid !== exp.paid_by) add(uid, exp.paid_by, owed);
    }
  }

  for (const st of settlements) {
    add(st.to_user, st.from_user, st.home_amount);
  }

  // Net pairs: if a owes b £30 and b owes a £10, collapse to a owes b £20.
  const net: Record<string, Record<string, number>> = {};
  for (const [a, row] of Object.entries(debts)) {
    for (const [b, amt] of Object.entries(row)) {
      const reverse = debts[b]?.[a] ?? 0;
      const diff = ROUND(amt - reverse);
      if (diff > 0) {
        if (!net[a]) net[a] = {};
        net[a]![b] = diff;
      }
    }
  }
  return net;
}
