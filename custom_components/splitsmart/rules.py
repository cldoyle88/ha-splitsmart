"""Pure rules engine for Splitsmart.

No IO, no HA imports. All validation errors are returned as strings; the
caller is responsible for logging them. This keeps the module unit-testable
without an event loop or Home Assistant fixtures.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

import yaml

# ------------------------------------------------------------------ dataclasses


@dataclass(frozen=True)
class Rule:
    id: str
    description: str | None
    pattern: re.Pattern[str]
    currency_match: str | None
    amount_min: Decimal | None
    amount_max: Decimal | None
    action: Literal["always_split", "always_ignore", "review_each_time"]
    category: str | None
    split: dict[str, Any] | None
    priority: int


@dataclass(frozen=True)
class RuleMatch:
    rule: Rule
    # Placeholder for v2 enrichment (e.g. capture groups from the pattern match).


class RuleParseError(ValueError):
    """Raised per-entry inside load_rules; never propagated to callers."""


# ------------------------------------------------------------------ amount parsing

# Amount constraints use separate semantics for single-bound vs range:
#   "> N"  → amount_min=N, amount_max=None → requires amount > N (exclusive)
#   "< N"  → amount_min=None, amount_max=N → requires amount < N (exclusive)
#   "N..M" → amount_min=N, amount_max=M   → requires N <= amount <= M (inclusive)


def _parse_amount(value: Any) -> tuple[Decimal | None, Decimal | None]:
    """Return (amount_min, amount_max) for a raw amount constraint string.

    Raises RuleParseError if the format is unrecognised.
    """
    if value is None:
        return None, None
    text = str(value).strip()
    if not text:
        return None, None

    try:
        if text.startswith("> "):
            return Decimal(text[2:].strip()), None
        if text.startswith("< "):
            return None, Decimal(text[2:].strip())
        if ".." in text:
            parts = text.split("..", 1)
            lo = Decimal(parts[0].strip())
            hi = Decimal(parts[1].strip())
            if lo > hi:
                raise RuleParseError(f"Amount range lower bound {lo} exceeds upper bound {hi}")
            return lo, hi
    except (InvalidOperation, ValueError) as err:
        raise RuleParseError(f"Invalid amount constraint {value!r}: {err}") from err

    raise RuleParseError(f"Invalid amount constraint {value!r}: expected '> N', '< N', or 'N..M'")


# ------------------------------------------------------------------ regex parsing

_FLAG_MAP: dict[str, int] = {"i": re.IGNORECASE}


def _parse_pattern(raw: str) -> re.Pattern[str]:
    """Parse a /PATTERN/FLAGS regex literal. Only the 'i' flag is supported."""
    if not isinstance(raw, str) or not raw.startswith("/"):
        raise RuleParseError(f"match must be a /pattern/ literal, got: {raw!r}")
    end = raw.rfind("/")
    if end == 0:
        raise RuleParseError(f"match has no closing /: {raw!r}")
    pattern_text = raw[1:end]
    flags_text = raw[end + 1 :]

    flags = 0
    for char in flags_text:
        if char not in _FLAG_MAP:
            raise RuleParseError(f"Unsupported regex flag '{char}' in {raw!r}")
        flags |= _FLAG_MAP[char]

    try:
        return re.compile(pattern_text, flags)
    except re.error as err:
        raise RuleParseError(f"Invalid regex in {raw!r}: {err}") from err


# ------------------------------------------------------------------ single-entry loader


_VALID_ACTIONS = {"always_split", "always_ignore", "review_each_time"}
_VALID_SPLIT_METHODS = {"equal", "percentage", "shares", "exact"}
_VALID_ID_RE = re.compile(r"^[a-z0-9_]+$")


def _load_rule(
    raw: Any,
    *,
    index: int,
    named_splits: dict[str, dict[str, Any]],
    seen_ids: set[str],
) -> Rule:
    """Parse and validate a single rule dict. Raises RuleParseError on any violation."""
    if not isinstance(raw, dict):
        raise RuleParseError(f"rule at index {index} is not a mapping")

    entry_id = raw.get("id")
    if not entry_id:
        raise RuleParseError(f"rule at index {index} is missing required 'id'")
    entry_id = str(entry_id)
    if not _VALID_ID_RE.match(entry_id):
        raise RuleParseError(f"rule id {entry_id!r} must match [a-z0-9_]+")
    if entry_id in seen_ids:
        raise RuleParseError(f"duplicate id {entry_id!r} — second entry skipped")

    match_raw = raw.get("match")
    if not match_raw:
        raise RuleParseError(f"rule {entry_id!r}: missing 'match'")
    try:
        pattern = _parse_pattern(str(match_raw))
    except RuleParseError as err:
        raise RuleParseError(f"rule {entry_id!r}: {err}") from err

    action = raw.get("action")
    if action not in _VALID_ACTIONS:
        raise RuleParseError(
            f"rule {entry_id!r}: action must be always_split, always_ignore, or"
            f" review_each_time; got {action!r}"
        )

    amount_min, amount_max = _parse_amount(raw.get("amount"))

    currency_match = raw.get("currency_match")
    if currency_match is not None:
        currency_match = str(currency_match).upper()

    category = raw.get("category")
    split = raw.get("split")

    if action == "always_split":
        if not category:
            raise RuleParseError(f"rule {entry_id!r}: always_split requires 'category'")
        if not split:
            raise RuleParseError(f"rule {entry_id!r}: always_split requires 'split'")
        if not isinstance(split, dict):
            raise RuleParseError(f"rule {entry_id!r}: 'split' must be a mapping")
        method = split.get("method")
        if method not in _VALID_SPLIT_METHODS:
            raise RuleParseError(
                f"rule {entry_id!r}: split.method {method!r} is not one of"
                f" {sorted(_VALID_SPLIT_METHODS)}"
            )
        # YAML parses unquoted values like 50_50 as integers (5050).
        # Coerce to string so preset names survive round-trip through the YAML parser.
        preset_raw = split.get("preset")
        preset = str(preset_raw) if preset_raw is not None else None
        if preset and preset not in named_splits:
            raise RuleParseError(f"rule {entry_id!r}: split.preset {preset!r} not in named_splits")

    if action == "review_each_time" and not category:
        raise RuleParseError(f"rule {entry_id!r}: review_each_time requires 'category'")

    priority_raw = raw.get("priority")
    if priority_raw is None:
        priority = index * 1000
    else:
        try:
            priority = int(priority_raw)
        except (TypeError, ValueError) as err:
            raise RuleParseError(
                f"rule {entry_id!r}: priority must be an integer, got {priority_raw!r}"
            ) from err

    return Rule(
        id=entry_id,
        description=raw.get("description"),
        pattern=pattern,
        currency_match=currency_match,
        amount_min=amount_min,
        amount_max=amount_max,
        action=action,  # type: ignore[arg-type]
        category=str(category) if category else None,
        split=dict(split) if split else None,
        priority=priority,
    )


# ------------------------------------------------------------------ public API


def load_rules(
    yaml_text: str,
    *,
    named_splits: dict[str, dict[str, Any]],
) -> tuple[list[Rule], list[str]]:
    """Parse and validate a rules.yaml string.

    Returns (valid_rules sorted by priority, list_of_error_strings). Never raises.
    """
    errors: list[str] = []

    try:
        data = yaml.safe_load(yaml_text)
    except Exception as err:
        return [], [f"YAML parse error: {err}"]

    if not data or "rules" not in data:
        return [], []

    raw_entries = data.get("rules") or []
    if not isinstance(raw_entries, list):
        return [], ["'rules' key must be a list"]

    rules: list[Rule] = []
    seen_ids: set[str] = set()

    for index, raw in enumerate(raw_entries):
        try:
            rule = _load_rule(raw, index=index, named_splits=named_splits, seen_ids=seen_ids)
        except RuleParseError as err:
            errors.append(str(err))
            continue
        seen_ids.add(rule.id)
        rules.append(rule)

    rules.sort(key=lambda r: r.priority)
    return rules, errors


def evaluate(
    row: dict[str, Any],
    rules: list[Rule],
) -> RuleMatch | None:
    """First-match-wins evaluation. Row must carry 'description', 'amount', 'currency'.

    Pure: no IO, no logging.
    """
    description: str = str(row.get("description") or "")
    amount: Decimal | None = None
    raw_amount = row.get("amount")
    if raw_amount is not None:
        with contextlib.suppress(InvalidOperation):
            amount = Decimal(str(raw_amount))
    currency: str = str(row.get("currency") or "").upper()

    for rule in rules:
        # Description pattern must match (always required).
        if not rule.pattern.search(description):
            continue

        # Currency filter: skip if row's currency doesn't match.
        if rule.currency_match and rule.currency_match != currency:
            continue

        # Amount filter — see module docstring for bound semantics.
        if rule.amount_min is not None or rule.amount_max is not None:
            if amount is None:
                # Row carries no amount; amount-filtered rules never match.
                continue
            if rule.amount_min is not None and rule.amount_max is not None:
                # Range "N..M" — inclusive both ends.
                if amount < rule.amount_min or amount > rule.amount_max:
                    continue
            elif rule.amount_min is not None:
                # "> N" — exclusive lower bound.
                if amount <= rule.amount_min:
                    continue
            else:
                # "< N" — exclusive upper bound.
                if amount >= rule.amount_max:  # type: ignore[operator]
                    continue

        return RuleMatch(rule=rule)

    return None


def build_match_payload(
    match: RuleMatch,
    *,
    home_currency: str,
    expense_amount: Decimal,
    named_splits: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Build a categories block for build_expense_record from an always_split match.

    Returns None for always_ignore and review_each_time (no immediate expense).
    Raises RuleParseError if a referenced preset is missing from named_splits.
    """
    rule = match.rule
    if rule.action != "always_split":
        return None

    split_def = rule.split or {}
    method = split_def.get("method", "equal")
    preset_raw = split_def.get("preset")
    preset_name = str(preset_raw) if preset_raw is not None else None
    inline_shares = split_def.get("shares")

    if preset_name:
        if not named_splits or preset_name not in named_splits:
            raise RuleParseError(f"split.preset {preset_name!r} not found in named_splits")
        resolved_split: dict[str, Any] = dict(named_splits[preset_name])
        resolved_split.setdefault("method", method)
    elif inline_shares:
        resolved_split = {"method": method, "shares": inline_shares}
    else:
        resolved_split = {"method": method}

    return {
        "categories": [
            {
                "name": rule.category,
                "home_amount": float(expense_amount.quantize(Decimal("0.01"))),
                "split": resolved_split,
            }
        ]
    }
