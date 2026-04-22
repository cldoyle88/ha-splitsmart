// Thin wrapper around hass.callWS / hass.callService / connection.subscribeMessage.
//
// Every function here does one thing: forward a typed request to HA and
// unpack the typed response. Views never talk to hass directly; they go
// through this module so the websocket contract lives in one place.
//
// Writes (add/edit/delete) return void; the websocket subscription delivers
// the resulting record via delta event within ~100ms.
// Reads go over the step-3 websocket commands.

import type {
  Expense,
  HomeAssistant,
  Settlement,
  SplitsmartConfig,
} from './types';

const DOMAIN = 'splitsmart';

// --------------------------------------------------------------- websocket reads

export async function getConfig(hass: HomeAssistant): Promise<SplitsmartConfig> {
  return hass.callWS<SplitsmartConfig>({ type: 'splitsmart/get_config' });
}

export interface ListExpensesFilters {
  month?: string;
  category?: string;
  paid_by?: string;
}

export interface ListExpensesResult {
  version: number;
  expenses: Expense[];
  settlements: Settlement[];
  total: number;
}

export async function listExpenses(
  hass: HomeAssistant,
  filters: ListExpensesFilters = {},
): Promise<ListExpensesResult> {
  const msg: Record<string, unknown> = { type: 'splitsmart/list_expenses' };
  if (filters.month) msg.month = filters.month;
  if (filters.category) msg.category = filters.category;
  if (filters.paid_by) msg.paid_by = filters.paid_by;
  return hass.callWS<ListExpensesResult>(msg);
}

export interface InitEvent {
  version: number;
  kind: 'init';
  expenses: Expense[];
  settlements: Settlement[];
}

export interface DeltaEvent {
  version: number;
  kind: 'delta';
  added: Array<{ kind: 'expense' | 'settlement'; record: Expense | Settlement }>;
  updated: Array<{ kind: 'expense' | 'settlement'; record: Expense | Settlement }>;
  deleted: string[];
}

export type SubscribeEvent = InitEvent | DeltaEvent;

/**
 * Subscribe to /list_expenses/subscribe. The backend sends one init event
 * immediately followed by zero-or-more delta events as the coordinator
 * writes. Returned promise resolves with the unsubscribe function.
 */
export function subscribeExpenses(
  hass: HomeAssistant,
  handler: (event: SubscribeEvent) => void,
): Promise<() => void> {
  return hass.connection.subscribeMessage<SubscribeEvent>(handler, {
    type: 'splitsmart/list_expenses/subscribe',
  });
}

// --------------------------------------------------------------- service writes

export interface AddExpensePayload {
  date: string;
  description: string;
  paid_by: string;
  amount: number;
  currency?: string;
  categories: Expense['categories'];
  notes?: string | null;
  receipt_path?: string | null;
  source?: string;
  staging_id?: string | null;
}

export interface EditExpensePayload extends AddExpensePayload {
  id: string;
  reason?: string | null;
}

export interface AddSettlementPayload {
  date: string;
  from_user: string;
  to_user: string;
  amount: number;
  currency?: string;
  notes?: string | null;
}

export interface EditSettlementPayload extends AddSettlementPayload {
  id: string;
  reason?: string | null;
}

export async function addExpense(
  hass: HomeAssistant,
  payload: AddExpensePayload,
): Promise<void> {
  await hass.callService(DOMAIN, 'add_expense', { ...payload });
}

export async function editExpense(
  hass: HomeAssistant,
  payload: EditExpensePayload,
): Promise<void> {
  await hass.callService(DOMAIN, 'edit_expense', { ...payload });
}

export async function deleteExpense(
  hass: HomeAssistant,
  id: string,
  reason?: string,
): Promise<void> {
  await hass.callService(DOMAIN, 'delete_expense', { id, ...(reason ? { reason } : {}) });
}

export async function addSettlement(
  hass: HomeAssistant,
  payload: AddSettlementPayload,
): Promise<void> {
  await hass.callService(DOMAIN, 'add_settlement', { ...payload });
}

export async function editSettlement(
  hass: HomeAssistant,
  payload: EditSettlementPayload,
): Promise<void> {
  await hass.callService(DOMAIN, 'edit_settlement', { ...payload });
}

export async function deleteSettlement(
  hass: HomeAssistant,
  id: string,
  reason?: string,
): Promise<void> {
  await hass.callService(DOMAIN, 'delete_settlement', { id, ...(reason ? { reason } : {}) });
}
