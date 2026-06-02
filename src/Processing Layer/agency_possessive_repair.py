"""
Tiered repair for person-name possessive welds on agency strings (ingest + stats).

Tier A: named AG surnames (allowlist) → strip surname, prepend state, keep unit name.
Tier B: NER-truncated "General's …" → repair prefix, same unit+state mapping.
Tier C: legit org/place possessives untouched (optional CEOS dedup).
Tier D: see next_ingest_edge_cases.md
"""

from __future__ import annotations

import re
from typing import Dict, Optional

_APOS = r"[''\u2019]"

# Canonical unit labels (distinct from state AG office).
IL_HTCB = "Illinois High Tech Crimes Bureau"
IL_SVP = "Illinois Sexually Violent Persons Bureau"
OH_BCI = "Ohio Bureau of Criminal Investigation"
LA_LBI = "Louisiana Bureau of Investigation"

# Tier A — surname allowlist → state for unit prefixing (NOT AG office fold).
_AG_SURNAME_TO_STATE: Dict[str, str] = {
    "raoul": "Illinois",
    "madigan": "Illinois",
    "murrill": "Louisiana",
    "yost": "Ohio",
}

_SURNAME_WELD_RE = re.compile(
    rf"^({'|'.join(_AG_SURNAME_TO_STATE.keys())}){_APOS}s\s+",
    re.IGNORECASE,
)
_GENERAL_MURRILL_RE = re.compile(
    rf"^general\s+murrill{_APOS}s\s+",
    re.IGNORECASE,
)
_GENERAL_TRUNC_RE = re.compile(rf"^general{_APOS}s\s+", re.IGNORECASE)

# All HTCB phrasing → one Illinois bar (includes state-prefixed mashups).
_HTCB_IN_LABEL_RE = re.compile(r"high\s+tech\s+crime'?s?\s+bureau", re.IGNORECASE)
_SVP_IN_LABEL_RE = re.compile(r"sexually\s+violent\s+persons\s+bureau", re.IGNORECASE)

_TIER_C_CEOS_DEDUP = re.compile(
    r"^justice department{_APOS}s child exploitation and obscenity section$",
    re.IGNORECASE,
)


def _map_unit_remainder(state: str, remainder: str) -> str:
    """Map stripped unit text to state-prefixed canonical org (not AG office)."""
    r = remainder.strip()
    cf = r.casefold()

    if _HTCB_IN_LABEL_RE.search(r):
        return IL_HTCB
    if _SVP_IN_LABEL_RE.search(r):
        return IL_SVP
    if "louisiana bureau of investigation" in cf or (
        state == "Louisiana" and "bureau of investigation" in cf
    ):
        return LA_LBI
    if "bureau of criminal investigation" in cf:
        if state == "Ohio" or "yost" in cf:
            return OH_BCI
        if state == "Illinois":
            return f"Illinois {r}"
    return f"{state} {r}" if r else state


def _canonicalize_unified_units(s: str, cf: str) -> Optional[str]:
    """
    Catch-all unit canonicalization (before surname strip).

    Merges all HTCB variants into IL_HTCB; other known units.
    """
    if _HTCB_IN_LABEL_RE.search(s):
        return IL_HTCB
    if _SVP_IN_LABEL_RE.search(s):
        return IL_SVP
    if "louisiana bureau of investigation" in cf:
        return LA_LBI
    if re.search(r"murrill{_APOS}s\s+louisiana bureau of investigation", cf):
        return LA_LBI
    if "bureau of criminal investigation" in cf and "texas" not in cf:
        if "illinois" in cf and "high tech" not in cf:
            return None
        if "ohio" in cf or re.search(r"\byost{_APOS}s\b", cf):
            return OH_BCI
        if re.search(r"^general{_APOS}s\s+.*bureau of criminal investigation", cf):
            return OH_BCI
    return None


def apply_possessive_tier_fixes(label: str) -> str:
    """
    Apply Tier A/B possessive repairs and Tier C CEOS dedup.

    Does NOT strip leading possessives generically (Tier C place/org names safe).
    """
    if not label or not str(label).strip():
        return label

    s = str(label).strip()
    s = re.sub(r"\s*[''\u2019]+\s*['']*\s*s\b", "'s", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip()
    if s.lower().startswith("the "):
        s = s[4:].strip()

    cf = s.casefold()

    if _TIER_C_CEOS_DEDUP.match(s) or (
        "justice department" in cf and "child exploitation and obscenity section" in cf
    ):
        return "CEOS"

    unified = _canonicalize_unified_units(s, cf)
    if unified:
        return unified

    m = _SURNAME_WELD_RE.match(s)
    if m:
        state = _AG_SURNAME_TO_STATE[m.group(1).casefold()]
        remainder = _SURNAME_WELD_RE.sub("", s, count=1).strip()
        return _map_unit_remainder(state, remainder)

    if _GENERAL_MURRILL_RE.match(s):
        remainder = _GENERAL_MURRILL_RE.sub("", s, count=1).strip()
        return _map_unit_remainder("Louisiana", remainder)

    if _GENERAL_TRUNC_RE.match(s):
        remainder = _GENERAL_TRUNC_RE.sub("", s, count=1).strip()
        if _HTCB_IN_LABEL_RE.search(remainder):
            return IL_HTCB
        if "bureau of criminal investigation" in remainder.casefold():
            return OH_BCI
        if "high tech crime" in remainder.casefold():
            return IL_HTCB
        if "office" in remainder.casefold() and "high tech" in remainder.casefold():
            return IL_HTCB
        repaired = f"Attorney General's {remainder}" if remainder else s
        return _map_unit_remainder("Illinois", remainder) if remainder else repaired

    return s
