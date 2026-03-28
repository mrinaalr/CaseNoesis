"""
Facet decision tree — group-centric partition of the case corpus.

**Depth / levels:** Each tuple in ``DEFAULT_FACET_ORDER`` is one partition dimension (one
tree depth). ``max_depth=N`` means “use only the first **N** dimensions in order,” then
stop at cohort leaves (e.g. ``N=4`` = Topic → Severity → Platform → Inv. type only).
**Full** (``max_depth=None``) uses the entire tuple (currently ``len(DEFAULT_FACET_ORDER)``
levels).

**Going deeper:** Append ``(case_dict_field, "Short label")`` to ``DEFAULT_FACET_ORDER``.
Fields may be JSON arrays on the case row or merged keys from ``extracted_features``
(``get_all_cases`` merges those onto each case dict). More levels → wider tree and more
nodes (combinatorial growth).

Each case is assigned exactly one branch per level via ``primary_bucket`` (first value
after sorting, or ``∅`` if empty).

Outputs cohort_group_id (hash of facet path), counts, and facet_signature for each
node — aligned with search.md (groups by default, not case-level search payloads).

Usage:
    from storage import CaseStorage
    from facet_tree import build_facet_tree

    storage = CaseStorage("caselinker.db")
    cases = storage.get_all_cases(include_raw_data=False)
    root = build_facet_tree(cases)
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Dict, List, Optional, Sequence, Tuple

# (column / case dict key, short label for display)
FacetStep = Tuple[str, str]

# Ordered partition dimensions — length = maximum facet depth for a “full” tree.
DEFAULT_FACET_ORDER: Sequence[FacetStep] = (
    ("case_topics", "Topic"),
    ("severity_indicators", "Severity"),
    ("platforms_used", "Platform"),
    ("investigation_type", "Inv. type"),
    ("source", "Source"),
    ("agencies_involved", "Agency"),
    ("organizations", "Organization"),
    ("locations", "Location"),
    ("severity_phrases", "Severity Phrase"),
)

EMPTY_BUCKET = "∅"


def _scalar_to_str(val: Any) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, dict):
        for key in ("name", "label", "city", "state", "region", "location"):
            v = val.get(key)
            if v is not None and str(v).strip():
                return str(v).strip()
        try:
            return json.dumps(val, sort_keys=True, default=str)[:160]
        except TypeError:
            s = str(val).strip()
            return s if s else None
    s = str(val).strip()
    return s if s else None


def _as_str_list(val: Any) -> List[str]:
    if val is None:
        return []
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            if isinstance(parsed, list):
                out: List[str] = []
                for x in parsed:
                    t = _scalar_to_str(x)
                    if t:
                        out.append(t)
                return out
        except (json.JSONDecodeError, TypeError):
            s = val.strip()
            return [s] if s else []
    if isinstance(val, list):
        out = []
        for x in val:
            t = _scalar_to_str(x)
            if t:
                out.append(t)
        return out
    t = _scalar_to_str(val)
    return [t] if t else []


def primary_bucket(case: Dict[str, Any], field_key: str) -> str:
    """
    Deterministic single bucket for this case at this facet level (partition).
    Uses lexicographically first value (case-insensitive key) so the same case
    never appears in two siblings at the same depth.
    """
    values = _as_str_list(case.get(field_key))
    if not values:
        return EMPTY_BUCKET
    return sorted(values, key=lambda s: s.upper())[0]


def cohort_group_id_from_path(path: List[Tuple[str, str]]) -> str:
    """Stable opaque group id for a facet path (search.md group_id)."""
    if not path:
        canonical = "root"
    else:
        canonical = "|".join(f"{k}={v}" for k, v in path)
    return sha256(canonical.encode("utf-8")).hexdigest()[:16]


@dataclass
class FacetTreeNode:
    """One node in the facet tree (internal branch or terminal cohort)."""

    label: str
    depth: int
    case_count: int
    cohort_group_id: str
    facet_signature: List[Tuple[str, str]] = field(default_factory=list)
    facet_key: Optional[str] = None
    facet_value: Optional[str] = None
    children: List["FacetTreeNode"] = field(default_factory=list)
    is_leaf: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "depth": self.depth,
            "case_count": self.case_count,
            "cohort_group_id": self.cohort_group_id,
            "facet_signature": [{"facet": k, "value": v} for k, v in self.facet_signature],
            "facet_key": self.facet_key,
            "facet_value": self.facet_value,
            "is_leaf": self.is_leaf,
            "children": [c.to_dict() for c in self.children],
        }


def _leaf_label(path: List[Tuple[str, str]]) -> str:
    if not path:
        return "Cohort (empty path)"
    parts = [f"{k}={v}" for k, v in path]
    return "Cohort · " + " · ".join(parts)


def _split_children(
    cases_subset: List[Dict[str, Any]],
    depth: int,
    path: List[Tuple[str, str]],
    facet_order: Sequence[FacetStep],
    max_depth: Optional[int],
) -> List[FacetTreeNode]:
    if not cases_subset:
        return []

    limit = len(facet_order) if max_depth is None else min(max_depth, len(facet_order))
    if depth >= limit:
        return [
            FacetTreeNode(
                label=_leaf_label(path),
                depth=depth,
                case_count=len(cases_subset),
                cohort_group_id=cohort_group_id_from_path(path),
                facet_signature=list(path),
                is_leaf=True,
            )
        ]

    facet_key, facet_display = facet_order[depth]
    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for c in cases_subset:
        b = primary_bucket(c, facet_key)
        buckets[b].append(c)

    nodes: List[FacetTreeNode] = []
    for value in sorted(buckets.keys(), key=lambda x: (x == EMPTY_BUCKET, x.upper())):
        sub = buckets[value]
        subpath = path + [(facet_key, value)]
        child_list = _split_children(sub, depth + 1, subpath, facet_order, max_depth)

        nodes.append(
            FacetTreeNode(
                label=f"{facet_display}: {value}",
                depth=depth + 1,
                case_count=len(sub),
                cohort_group_id=cohort_group_id_from_path(subpath),
                facet_signature=subpath,
                facet_key=facet_key,
                facet_value=value,
                children=child_list,
                is_leaf=False,
            )
        )
    return nodes


def build_facet_tree(
    cases: List[Dict[str, Any]],
    facet_order: Optional[Sequence[FacetStep]] = None,
    max_depth: Optional[int] = None,
) -> FacetTreeNode:
    """
    Build the full facet tree for the given cases.

    Args:
        cases: Case dicts (typically from get_all_cases(include_raw_data=False)).
        facet_order: Ordered list of (field_key, display_name); defaults to DEFAULT_FACET_ORDER.
        max_depth: Cap how many facet levels to expand (None = all).

    Returns:
        Root node labeled "All cases" with partition children under DEFAULT_FACET_ORDER.
    """
    order: Sequence[FacetStep] = facet_order if facet_order is not None else DEFAULT_FACET_ORDER
    root = FacetTreeNode(
        label="All cases",
        depth=0,
        case_count=len(cases),
        cohort_group_id=cohort_group_id_from_path([]),
        facet_signature=[],
        children=_split_children(cases, 0, [], order, max_depth),
        is_leaf=False,
    )
    return root


def count_nodes(node: FacetTreeNode) -> int:
    return 1 + sum(count_nodes(c) for c in node.children)


def max_tree_depth(node: FacetTreeNode) -> int:
    if not node.children:
        return node.depth
    return max(max_tree_depth(c) for c in node.children)
