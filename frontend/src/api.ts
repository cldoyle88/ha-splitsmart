// Thin wrapper around hass.callWS / hass.callService / connection.subscribeMessage.
//
// Every function here does one thing: forward a typed request to HA and
// unpack the typed response. Views never talk to hass directly; they go
// through this module so the websocket contract lives in one place.
//
// Writes (add/edit/delete) return {id} from the existing M1 services.
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

export interface IdResponse {
  id: string;
}

async function callWithResponse(
  hass: HomeAssistant,
  service: string,
  data: Record<string, unknown>,
): Promise<IdResponse> {
  const result = (await hass.callService(DOMAIN, service, data, {
    return_response: true,
  })) as { response?: IdResponse } | IdResponse | undefined;

  // HA wraps service responses in { response: {...} } on some versions;
  // others return the raw object. Accept both shapes.
  if (result && typeof result === 'object' && 'response' in result) {
    return (result as { response: IdResponse }).response;
  }
  return (result as IdResponse) ?? { id: '' };
}

export function addExpense(
  hass: HomeAssistant,
  payload: AddExpensePayload,
): Promise<IdResponse> {
  return callWithResponse(hass, 'add_expense', { ...payload });
}

export function editExpense(
  hass: HomeAssistant,
  payload: EditExpensePayload,
): Promise<IdResponse> {
  return callWithResponse(hass, 'edit_expense', { ...payload });
}

export function deleteExpense(
  hass: HomeAssistant,
  id: string,
  reason?: string,
): Promise<IdResponse> {
  return callWithResponse(hass, 'delete_expense', { id, ...(reason ? { reason } : {}) });
}

export function addSettlement(
  hass: HomeAssistant,
  payload: AddSettlementPayload,
): Promise<IdResponse> {
  return callWithResponse(hass, 'add_settlement', { ...payload });
}

export function editSettlement(
  hass: HomeAssistant,
  payload: EditSettlementPayload,
): Promise<IdResponse> {
  return callWithResponse(hass, 'edit_settlement', { ...payload });
}

export function deleteSettlement(
  hass: HomeAssistant,
  id: string,
  reason?: string,
): Promise<IdResponse> {
  return callWithResponse(hass, 'delete_settlement', { id, ...(reason ? { reason } : {}) });
}
