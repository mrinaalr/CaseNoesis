"""
Case resolve — collapse related press releases into one prosecution,
and merge their extracted features into one combined case record.

Whiteprint (design stub). Not wired into ingest yet.

Problem
-------
Collection correctly keeps **one PDF page / one Source URL / one document row**
for provenance (indictment, plea, sentencing are three documents). Downstream
needs one **canonical case** that:

1. **Links** those documents (prosecution_id owns document_ids / source_urls)
2. **Combines features** so indictment + plea + sentencing (+ any other linked
   release) contribute to one feature bag — not just an ID cluster

Feature merge (AND / OR)
------------------------
Member documents are folded with field-wise ops:

- **OR / union** (set-like): platforms, agencies, statutes, charge labels,
  topics, locations, defendant name variants, technology flags — anything true
  on *any* release is true on the canonical case.
- **AND / confirm** (when useful): facts that should agree across releases
  (same docket, same primary defendant, same district). Conflicts → review,
  do not silently overwrite.
- **Prefer later lifecycle** for outcomes: sentence length, plea type,
  disposition date come from sentencing/plea when present; indictment fills
  charges that later releases omit.
- **Span dates**: date_start = earliest release/charge signal; date_end =
  latest disposition/sentencing signal.
- **Provenance never dropped**: every source_url stays on the canonical case;
  raw document rows stay intact for audit.

This module sits in the Processing Layer, after extract (batching + NER /
entity fields are available) and before analysis / CASE-UCO graph build.

Match order (strict → soft)
---------------------------
1. Docket / case number when printed in the release
2. Same district (or USAO) + same defendant name set + overlapping charge window
3. Soft fallback: high defendant-name overlap + same office — **review queue**,
   not auto-merge (plea text ≠ indictment text; Jaccard alone misses most true pairs)

What this is not
----------------
- Scraper URL novelty (`check_expand_novelty.py`) — document-level, pre-ingest
- `validate_case_uniqueness.py` — near-duplicate *text* report, no merge
- Graph merge (`ontology/merge_graph_cache.py`) — viz node sharing, not case identity

Schema sketch (storage later)
-----------------------------
Document row (today's case row, unchanged provenance):
  id, source_url, source, case_text, date_*, defendants, district, docket, features…

Canonical case:
  prosecution_id          # stable id for the collapsed prosecution
  document_ids[]          # member document row ids
  source_urls[]           # provenance URLs kept, never dropped
  primary_document_id     # e.g. most recent lifecycle stage, or longest body
  match_method            # docket | district_defendant | soft_review
  match_confidence        # 0–1
  review_status           # auto | needs_review | confirmed | rejected
  merged_features         # OR/AND fold of member feature dicts (see merge_features)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


# ── Record shapes ─────────────────────────────────────────────────────────────


@dataclass
class DocumentRef:
    """One press-release document after extract (maps to today's case row)."""

    id: str
    source_url: str = ""
    source: str = ""
    district: str = ""
    docket: str = ""
    defendants: Tuple[str, ...] = ()
    charge_date: Optional[str] = None  # ISO date if known
    lifecycle_stage: str = ""  # indictment | plea | sentencing | other | ""
    case_text: str = ""


@dataclass
class ProsecutionCluster:
    """One canonical prosecution: linked documents + merged feature bag."""

    prosecution_id: str
    document_ids: List[str] = field(default_factory=list)
    source_urls: List[str] = field(default_factory=list)
    primary_document_id: str = ""
    match_method: str = "singleton"  # docket | district_defendant | soft_review | singleton
    match_confidence: float = 1.0
    review_status: str = "auto"  # auto | needs_review | confirmed | rejected
    merged_features: Dict[str, Any] = field(default_factory=dict)
    feature_conflicts: List[str] = field(default_factory=list)  # AND-tier disagreements


# ── Extractors (fill in when wiring to processed case dicts) ───────────────────


_DOCKET_RE = None  # set lazily; avoid import-time regex churn in the whiteprint


def extract_docket(text: str) -> str:
    """Pull a federal/state docket token from press text when present.

    Target patterns (implement when wiring):
      ``1:24-cr-00123``, ``24-CR-123``, state variants printed in USAO releases.
    """
    raise NotImplementedError("whiteprint: extract_docket")


def extract_district(case: Dict[str, Any]) -> str:
    """Normalize district / USAO / state venue from case fields or text."""
    raise NotImplementedError("whiteprint: extract_district")


def extract_defendants(case: Dict[str, Any]) -> Tuple[str, ...]:
    """Normalized defendant name set (sorted, lowercased for matching)."""
    raise NotImplementedError("whiteprint: extract_defendants")


def infer_lifecycle_stage(text: str) -> str:
    """Cheap headline/body cue → indictment | plea | sentencing | other."""
    raise NotImplementedError("whiteprint: infer_lifecycle_stage")


def document_from_case(case: Dict[str, Any]) -> DocumentRef:
    """Map a processed case dict → DocumentRef for clustering."""
    raise NotImplementedError("whiteprint: document_from_case")


# ── Match tiers ───────────────────────────────────────────────────────────────


def match_by_docket(
    docs: Sequence[DocumentRef],
) -> List[List[DocumentRef]]:
    """Tier 1 — group documents that share a normalized docket string."""
    raise NotImplementedError("whiteprint: match_by_docket")


def match_by_district_defendant(
    docs: Sequence[DocumentRef],
    *,
    date_window_days: int = 730,
) -> List[List[DocumentRef]]:
    """Tier 2 — same district + overlapping defendant set + charge-date window."""
    raise NotImplementedError("whiteprint: match_by_district_defendant")


def match_soft_review(
    docs: Sequence[DocumentRef],
) -> List[Tuple[DocumentRef, DocumentRef, float]]:
    """Tier 3 — candidate pairs for human review (do not auto-merge)."""
    raise NotImplementedError("whiteprint: match_soft_review")


# ── Resolve entry points ──────────────────────────────────────────────────────


def merge_features(
    member_feature_dicts: Sequence[Dict[str, Any]],
    *,
    lifecycle_stages: Sequence[str] = (),
) -> Tuple[Dict[str, Any], List[str]]:
    """Fold member document features into one canonical feature bag.

    Returns ``(merged_features, conflicts)``.

    Intended field policy (implement when wiring):
      OR/union   — lists/sets (platforms, agencies, statutes, topics, …)
      AND/check  — scalar identity fields (docket, primary defendant, district)
      prefer     — disposition / sentence / plea from later lifecycle stages
      span       — date_start min, date_end max across members
    """
    raise NotImplementedError("whiteprint: merge_features")


def resolve_documents(
    docs: Sequence[DocumentRef],
    *,
    feature_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
    auto_merge_soft: bool = False,
) -> List[ProsecutionCluster]:
    """Match documents → clusters, then ``merge_features`` per cluster.

    Default: tier 1 + 2 auto-merge; tier 3 emitted as ``needs_review`` pairs
    only (``auto_merge_soft=False``). Singletons stay one-doc clusters with
    features copied through.
    """
    raise NotImplementedError(
        "whiteprint: resolve_documents — wire after extract; see module docstring"
    )


def resolve_cases(
    cases: Iterable[Dict[str, Any]],
    *,
    auto_merge_soft: bool = False,
) -> List[ProsecutionCluster]:
    """Convenience: processed case dicts → clusters with merged features."""
    case_list = list(cases)
    docs = [document_from_case(c) for c in case_list]
    feature_by_id = {
        str(c.get("id", "")): dict(c) for c in case_list if c.get("id") is not None
    }
    return resolve_documents(
        docs, feature_by_id=feature_by_id, auto_merge_soft=auto_merge_soft
    )


def attach_prosecution_ids(
    cases: List[Dict[str, Any]],
    clusters: Sequence[ProsecutionCluster],
) -> List[Dict[str, Any]]:
    """Stamp ``prosecution_id``, ``source_urls``, and ``merged_features`` onto outputs."""
    raise NotImplementedError("whiteprint: attach_prosecution_ids")
