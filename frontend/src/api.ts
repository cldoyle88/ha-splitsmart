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
  ColumnMapping,
  Expense,
  FileInspection,
  HomeAssistant,
  RuleRecord,
  Settlement,
  SplitsmartConfig,
  StagingRow,
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

// --------------------------------------------------------------- M5: Rules

export interface ListRulesResult {
  version: number;
  rules: RuleRecord[];
  loaded_at: string | null;
  source_path: string;
  errors: string[];
}

export interface RulesInitEvent {
  version: number;
  kind: 'init';
  rules: RuleRecord[];
  loaded_at: string | null;
  source_path: string;
  errors: string[];
}

export interface RulesReloadEvent {
  version: number;
  kind: 'reload';
  rules: RuleRecord[];
  loaded_at: string | null;
  errors: string[];
}

export type RulesEvent = RulesInitEvent | RulesReloadEvent;

export async function listRules(hass: HomeAssistant): Promise<ListRulesResult> {
  return hass.callWS<ListRulesResult>({ type: 'splitsmart/list_rules' });
}

export function subscribeRules(
  hass: HomeAssistant,
  handler: (event: RulesEvent) => void,
): Promise<() => void> {
  return hass.connection.subscribeMessage<RulesEvent>(handler, {
    type: 'splitsmart/list_rules/subscribe',
  });
}

export interface ReloadRulesResult {
  version: number;
  loaded_at: string | null;
  rules_count: number;
  errors: string[];
}

export async function reloadRules(hass: HomeAssistant): Promise<ReloadRulesResult> {
  return hass.callWS<ReloadRulesResult>({ type: 'splitsmart/reload_rules' });
}

export interface DraftRuleResult {
  version: number;
  yaml_snippet: string;
  draft: {
    id: string;
    description: string | null;
    pattern: string;
    action: string;
    category: string | null;
    split: Record<string, unknown> | null;
    priority: number | null;
  };
}

export async function draftRuleFromRow(
  hass: HomeAssistant,
  params: {
    staging_id: string;
    action: 'always_split' | 'always_ignore' | 'review_each_time';
    default_split_preset?: string;
  },
): Promise<DraftRuleResult> {
  return hass.callWS<DraftRuleResult>({
    type: 'splitsmart/draft_rule_from_row',
    ...params,
  });
}

// --------------------------------------------------------------- M5: Staging

export interface ListStagingResult {
  version: number;
  rows: StagingRow[];
  tombstones: Record<string, unknown>[];
  total: number;
}

export async function listStaging(hass: HomeAssistant): Promise<ListStagingResult> {
  return hass.callWS<ListStagingResult>({ type: 'splitsmart/list_staging' });
}

export interface StagingInitEvent {
  version: number;
  kind: 'init';
  rows: StagingRow[];
}

export interface StagingDeltaEvent {
  version: number;
  kind: 'delta';
  added: StagingRow[];
  updated: StagingRow[];
  deleted: string[];
}

export type StagingEvent = StagingInitEvent | StagingDeltaEvent;

export function subscribeStaging(
  hass: HomeAssistant,
  handler: (event: StagingEvent) => void,
): Promise<() => void> {
  return hass.connection.subscribeMessage<StagingEvent>(handler, {
    type: 'splitsmart/list_staging/subscribe',
  });
}

export async function promoteStaging(
  hass: HomeAssistant,
  params: {
    staging_id: string;
    paid_by: string;
    categories: Expense['categories'];
    notes?: string | null;
    receipt_path?: string | null;
    override_description?: string | null;
    override_date?: string | null;
    reason?: string | null;
  },
): Promise<void> {
  await hass.callService(DOMAIN, 'promote_staging', { ...params });
}

export async function skipStaging(
  hass: HomeAssistant,
  staging_id: string,
  reason?: string,
): Promise<void> {
  await hass.callService(DOMAIN, 'skip_staging', {
    staging_id,
    ...(reason ? { reason } : {}),
  });
}

export async function applyRules(
  hass: HomeAssistant,
  user_id?: string,
): Promise<{ auto_promoted: number; auto_ignored: number; auto_review: number; still_pending: number }> {
  const result = await hass.callService(
    DOMAIN,
    'apply_rules',
    user_id ? { user_id } : {},
    { return_response: true },
  );
  return result as { auto_promoted: number; auto_ignored: number; auto_review: number; still_pending: number };
}

// --------------------------------------------------------------- M5: Import

export async function inspectUpload(
  hass: HomeAssistant,
  upload_id: string,
): Promise<FileInspection> {
  const result = await hass.callWS<{ version: number; inspection: FileInspection }>({
    type: 'splitsmart/inspect_upload',
    upload_id,
  });
  return result.inspection;
}

export async function saveMapping(
  hass: HomeAssistant,
  file_origin_hash: string,
  mapping: ColumnMapping,
): Promise<void> {
  await hass.callWS({
    type: 'splitsmart/save_mapping',
    file_origin_hash,
    mapping: mapping as unknown as Record<string, unknown>,
  });
}

export interface ImportFileResult {
  imported: number;
  duplicates: number;
  auto_promoted: number;
  auto_ignored: number;
  auto_review: number;
  still_pending: number;
}

export async function importFile(
  hass: HomeAssistant,
  params: {
    upload_id: string;
    mapping?: ColumnMapping;
    remember_mapping?: boolean;
  },
): Promise<ImportFileResult> {
  const result = await hass.callService(
    DOMAIN,
    'import_file',
    {
      upload_id: params.upload_id,
      ...(params.mapping ? { mapping: params.mapping } : {}),
      ...(params.remember_mapping !== undefined
        ? { remember_mapping: params.remember_mapping }
        : {}),
    },
    { return_response: true },
  );
  return result as ImportFileResult;
}
