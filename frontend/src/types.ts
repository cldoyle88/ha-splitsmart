// Shared TypeScript types for the Splitsmart card.
// Only the minimum shape needed by the card — HA's real types are vast;
// we declare what we consume here and keep it in one file.

/** The HomeAssistant object injected by Lovelace into the card. */
export interface HomeAssistant {
  states: Record<string, HassEntityState>;
  user?: { id: string; name: string } | null;
  locale?: { language: string };
  connection: {
    subscribeMessage<T = unknown>(
      callback: (message: T) => void,
      subscribeMessage: Record<string, unknown>,
    ): Promise<() => void>;
  };
  callWS<T = unknown>(msg: Record<string, unknown>): Promise<T>;
  callService(
    domain: string,
    service: string,
    serviceData?: Record<string, unknown>,
    options?: { return_response?: boolean },
  ): Promise<unknown>;
}

/** Minimal shape for an entity state from hass.states. */
export interface HassEntityState {
  entity_id: string;
  state: string;
  attributes: Record<string, unknown>;
  last_changed: string;
  last_updated: string;
}

/** Card config passed from Lovelace YAML (e.g. type: custom:splitsmart-card). */
export interface SplitsmartCardConfig {
  type: string;
  view?: 'home' | 'ledger' | 'add' | 'settle';
}

/** Participant record from splitsmart/get_config. */
export interface Participant {
  user_id: string;
  display_name: string;
  active: boolean;
}

/** Bootstrap config from splitsmart/get_config. */
export interface SplitsmartConfig {
  version: number;
  participants: Participant[];
  home_currency: string;
  categories: string[];
  named_splits: Record<string, unknown>;
  current_user_id: string;
}

/** One split share. */
export interface SplitShare {
  user_id: string;
  value: number;
}

/** Split object on an allocation. */
export interface Split {
  method: 'equal' | 'percentage' | 'shares' | 'exact';
  shares: SplitShare[];
}

/** One category allocation on an expense. */
export interface CategoryAllocation {
  name: string;
  home_amount: number;
  split: Split;
}

/** Shared expense record. */
export interface Expense {
  id: string;
  created_at: string;
  created_by: string;
  date: string;
  description: string;
  paid_by: string;
  amount: number;
  currency: string;
  home_amount: number;
  home_currency: string;
  fx_rate: number;
  fx_date: string;
  categories: CategoryAllocation[];
  source: string;
  staging_id: string | null;
  receipt_path: string | null;
  notes: string | null;
  comments: unknown[];
}

/** Settlement record. */
export interface Settlement {
  id: string;
  created_at: string;
  created_by: string;
  date: string;
  from_user: string;
  to_user: string;
  amount: number;
  currency: string;
  home_amount: number;
  notes: string | null;
}

/** Entry in the window.customCards gallery. */
export interface CustomCardEntry {
  type: string;
  name: string;
  description: string;
  preview?: boolean;
}

declare global {
  interface Window {
    customCards?: CustomCardEntry[];
  }
}
