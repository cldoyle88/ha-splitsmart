"""Constants for Splitsmart."""
from __future__ import annotations

DOMAIN = "splitsmart"

# Config entry data keys
CONF_PARTICIPANTS = "participants"
CONF_HOME_CURRENCY = "home_currency"
CONF_CATEGORIES = "categories"
CONF_NAMED_SPLITS = "named_splits"

# Default categories
DEFAULT_CATEGORIES: list[str] = [
    "Groceries",
    "Utilities",
    "Rent",
    "Eating out",
    "Transport",
    "Household",
    "Entertainment",
    "Other",
]

# Common currencies for config flow (pinned at top)
COMMON_CURRENCIES: list[str] = ["GBP", "EUR", "USD", "CAD", "AUD"]

# Storage sub-paths (relative to /config/splitsmart/)
STORAGE_SUBDIR = "splitsmart"
SHARED_DIR = "shared"
STAGING_DIR = "staging"
RECEIPTS_DIR = "receipts"
EXPENSES_FILE = "expenses.jsonl"
SETTLEMENTS_FILE = "settlements.jsonl"
TOMBSTONES_FILE = "tombstones.jsonl"

# JSONL record id prefixes
ID_PREFIX_EXPENSE = "ex"
ID_PREFIX_SETTLEMENT = "sl"
ID_PREFIX_TOMBSTONE = "tb"
ID_PREFIX_STAGING = "st"
ID_PREFIX_RULE = "r"

# Split methods
SPLIT_METHOD_EQUAL = "equal"
SPLIT_METHOD_PERCENTAGE = "percentage"
SPLIT_METHOD_SHARES = "shares"
SPLIT_METHOD_EXACT = "exact"
SPLIT_METHODS = {SPLIT_METHOD_EQUAL, SPLIT_METHOD_PERCENTAGE, SPLIT_METHOD_SHARES, SPLIT_METHOD_EXACT}

# Entry sources
SOURCE_MANUAL = "manual"
SOURCE_STAGING = "staging"
SOURCE_TELEGRAM = "telegram"
SOURCE_RECURRING = "recurring"
SOURCES = {SOURCE_MANUAL, SOURCE_STAGING, SOURCE_TELEGRAM, SOURCE_RECURRING}

# Tombstone operations
TOMBSTONE_EDIT = "edit"
TOMBSTONE_DELETE = "delete"
TOMBSTONE_DISCARD = "discard"

# Tombstone target types
TARGET_EXPENSE = "expense"
TARGET_SETTLEMENT = "settlement"
TARGET_STAGING = "staging"

# Service names
SERVICE_ADD_EXPENSE = "add_expense"
SERVICE_ADD_SETTLEMENT = "add_settlement"
SERVICE_EDIT_EXPENSE = "edit_expense"
SERVICE_EDIT_SETTLEMENT = "edit_settlement"
SERVICE_DELETE_EXPENSE = "delete_expense"
SERVICE_DELETE_SETTLEMENT = "delete_settlement"

# Coordinator
COORDINATOR_UPDATE_INTERVAL_MINUTES = 5

# Sensor unique id fragments
SENSOR_BALANCE = "balance"
SENSOR_SPENDING_MONTH = "spending_month"
SENSOR_SPENDING_TOTAL_MONTH = "spending_total_month"
SENSOR_LAST_EXPENSE = "last_expense"
