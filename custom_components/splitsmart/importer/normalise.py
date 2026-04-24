"""Description normalisation + dedup-hash construction.

Shared between the importer (when writing new staging rows) and dedup
(when comparing against existing staging/shared/tombstoned rows). Keeping
the recipe in one module guarantees both sides stay in lockstep; a drift
here would silently break duplicate detection.
"""

from __future__ import annotations

import hashlib
import re

# Trailing date suffixes that some card issuers append to merchant names,
# e.g. "TFL TRAVEL 15/04", "TESCO METRO 2026-04-15". Stripping them keeps
# daily charges from the same merchant collapsed to one dedup hash so
# re-imports of later statements don't double up.
_TRAILING_DATE_RE = re.compile(
    r"(?:\s+\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|\s+\d{4}-\d{2}-\d{2})\s*$"
)
_WHITESPACE_RUN = re.compile(r"\s+")


def normalise_description(raw: str) -> str:
    """Canonical form for dedup hashing. See M3_PLAN.md §4 for the recipe."""
    s = raw.strip().lstrip("*").strip()
    s = _TRAILING_DATE_RE.sub("", s)
    s = s.upper()
    s = _WHITESPACE_RUN.sub(" ", s).strip()
    return s


def dedup_hash(*, date: str, amount: float, currency: str, description: str) -> str:
    """Build the multiset-dedup fingerprint for a row.

    Stored on every staging row and recomputed against every row under
    consideration for import. SPEC §12.4 is the authoritative definition.
    """
    canonical = f"{date}|{round(amount, 2):.2f}|{currency}|{normalise_description(description)}"
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
