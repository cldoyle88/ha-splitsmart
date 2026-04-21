import { describe, it, expect, vi } from 'vitest';
import {
  addExpense,
  addSettlement,
  deleteExpense,
  deleteSettlement,
  editExpense,
  editSettlement,
  getConfig,
  listExpenses,
  subscribeExpenses,
} from '../src/api';
import type { HomeAssistant } from '../src/types';

function makeHass(overrides: Partial<HomeAssistant> = {}): HomeAssistant {
  return {
    states: {},
    user: { id: 'u1', name: 'Chris' },
    callWS: vi.fn().mockResolvedValue({}),
    callService: vi.fn().mockResolvedValue({ response: { id: 'ex_test' } }),
    connection: {
      subscribeMessage: vi.fn().mockImplementation(async () => () => {}),
    },
    ...overrides,
  } as HomeAssistant;
}

describe('getConfig', () => {
  it('sends splitsmart/get_config', async () => {
    const hass = makeHass();
    await getConfig(hass);
    expect(hass.callWS).toHaveBeenCalledWith({ type: 'splitsmart/get_config' });
  });
});

describe('listExpenses', () => {
  it('sends splitsmart/list_expenses with no filters', async () => {
    const hass = makeHass();
    await listExpenses(hass);
    expect(hass.callWS).toHaveBeenCalledWith({ type: 'splitsmart/list_expenses' });
  });

  it('forwards month / category / paid_by filters', async () => {
    const hass = makeHass();
    await listExpenses(hass, { month: '2026-04', category: 'Groceries', paid_by: 'u1' });
    expect(hass.callWS).toHaveBeenCalledWith({
      type: 'splitsmart/list_expenses',
      month: '2026-04',
      category: 'Groceries',
      paid_by: 'u1',
    });
  });

  it('omits filter keys when undefined', async () => {
    const hass = makeHass();
    await listExpenses(hass, { month: '2026-04' });
    expect(hass.callWS).toHaveBeenCalledWith({
      type: 'splitsmart/list_expenses',
      month: '2026-04',
    });
  });
});

describe('subscribeExpenses', () => {
  it('registers a handler and returns the unsubscribe', async () => {
    const unsub = vi.fn();
    const hass = makeHass({
      connection: {
        subscribeMessage: vi.fn().mockResolvedValue(unsub),
      },
    });
    const handler = vi.fn();
    const result = await subscribeExpenses(hass, handler);
    expect(hass.connection.subscribeMessage).toHaveBeenCalledWith(handler, {
      type: 'splitsmart/list_expenses/subscribe',
    });
    expect(result).toBe(unsub);
  });
});

describe('addExpense', () => {
  it('sends a splitsmart.add_expense call with return_response', async () => {
    const hass = makeHass();
    const payload = {
      date: '2026-04-20',
      description: 'Waitrose',
      paid_by: 'u1',
      amount: 40,
      categories: [
        {
          name: 'Groceries',
          home_amount: 40,
          split: {
            method: 'equal' as const,
            shares: [
              { user_id: 'u1', value: 50 },
              { user_id: 'u2', value: 50 },
            ],
          },
        },
      ],
    };
    const result = await addExpense(hass, payload);
    expect(hass.callService).toHaveBeenCalledWith(
      'splitsmart',
      'add_expense',
      payload,
      { return_response: true },
    );
    expect(result).toEqual({ id: 'ex_test' });
  });

  it('accepts response without {response: ...} wrapper', async () => {
    const hass = makeHass({
      callService: vi.fn().mockResolvedValue({ id: 'ex_unwrapped' }),
    });
    const result = await addExpense(hass, {
      date: '2026-04-20',
      description: 'X',
      paid_by: 'u1',
      amount: 1,
      categories: [],
    });
    expect(result).toEqual({ id: 'ex_unwrapped' });
  });
});

describe('editExpense', () => {
  it('includes the target id and reason', async () => {
    const hass = makeHass();
    await editExpense(hass, {
      id: 'ex_01',
      reason: 'typo',
      date: '2026-04-20',
      description: 'Tesco',
      paid_by: 'u1',
      amount: 10,
      categories: [],
    });
    const call = (hass.callService as ReturnType<typeof vi.fn>).mock.calls[0]!;
    expect(call[0]).toBe('splitsmart');
    expect(call[1]).toBe('edit_expense');
    expect(call[2]).toMatchObject({ id: 'ex_01', reason: 'typo' });
  });
});

describe('deleteExpense', () => {
  it('sends {id} without reason when none supplied', async () => {
    const hass = makeHass();
    await deleteExpense(hass, 'ex_01');
    expect(hass.callService).toHaveBeenCalledWith(
      'splitsmart',
      'delete_expense',
      { id: 'ex_01' },
      { return_response: true },
    );
  });

  it('adds reason when supplied', async () => {
    const hass = makeHass();
    await deleteExpense(hass, 'ex_01', 'mistake');
    expect(hass.callService).toHaveBeenCalledWith(
      'splitsmart',
      'delete_expense',
      { id: 'ex_01', reason: 'mistake' },
      { return_response: true },
    );
  });
});

describe('settlement services', () => {
  it('addSettlement forwards the payload', async () => {
    const hass = makeHass();
    await addSettlement(hass, {
      date: '2026-04-21',
      from_user: 'u2',
      to_user: 'u1',
      amount: 40,
    });
    expect(hass.callService).toHaveBeenCalledWith(
      'splitsmart',
      'add_settlement',
      { date: '2026-04-21', from_user: 'u2', to_user: 'u1', amount: 40 },
      { return_response: true },
    );
  });

  it('editSettlement includes id', async () => {
    const hass = makeHass();
    await editSettlement(hass, {
      id: 'sl_01',
      date: '2026-04-21',
      from_user: 'u2',
      to_user: 'u1',
      amount: 41,
    });
    expect((hass.callService as ReturnType<typeof vi.fn>).mock.calls[0]![1]).toBe(
      'edit_settlement',
    );
    expect((hass.callService as ReturnType<typeof vi.fn>).mock.calls[0]![2]).toMatchObject({
      id: 'sl_01',
    });
  });

  it('deleteSettlement sends {id}', async () => {
    const hass = makeHass();
    await deleteSettlement(hass, 'sl_01');
    expect(hass.callService).toHaveBeenCalledWith(
      'splitsmart',
      'delete_settlement',
      { id: 'sl_01' },
      { return_response: true },
    );
  });
});
