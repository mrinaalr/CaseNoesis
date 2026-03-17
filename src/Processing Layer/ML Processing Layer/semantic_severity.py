"""
Semantic Severity Phrases (ML)

Goal: Identify key severity phrases **semantically** rather than purely
via regex, so we can capture the same conceptual signals even when the
exact words differ.

Target phrases match or extend the keys used by pattern processing in
`extract_severity_phrases` (see Pattern Processing Layer):
- dangerous
- stated
- told
- continue
- attacked
- out_of_control
- violent
- obscene
- assault
- abuse
- depictions

Implementation:
- Uses a sentence-transformer semantic model (via MLModelManager) when
  available.
- Encodes the whole case text and compares it to short natural-language
  descriptions of each severity concept.
- Returns phrases whose similarity scores exceed a configurable threshold.

This module is intentionally self-contained so it can be tested directly
and later merged into the Merge Processing layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import warnings

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy is optional
    np = None  # type: ignore


@dataclass
class SeverityPhraseScore:
    """Score for a single semantic severity phrase."""

    key: str
    score: float


class SemanticSeverity:
    """
    Semantic severity phrase detector using sentence embeddings.

    Usage:
        from semantic_severity import SemanticSeverity
        from ml_models import get_global_ml_manager

        ml_manager = get_global_ml_manager(enable_ml=True)
        semantic_model = ml_manager.get_model("semantic")
        severity = SemanticSeverity(semantic_model)

        phrases = severity.get_severity_phrases(case_text)
    """

    # Map phrase keys → natural language descriptions for embedding
    _SEVERITY_CONCEPTS: Dict[str, str] = {
        # Matches pattern key: 'dangerous'
        "dangerous": (
            "The offender is described as dangerous, high risk, escalating, "
            "or likely to seriously harm victims."
        ),
        # Matches pattern key: 'stated'
        "stated": (
            "The victim or witnesses made clear statements or disclosures "
            "about the abuse or exploitation."
        ),
        # Matches pattern key: 'told'
        "told": (
            "The victim told someone about the abuse, reported it, or "
            "communicated clear disclosures."
        ),
        # Matches pattern key: 'continue'
        "continue": (
            "The abuse or exploitation continued over time, repeated conduct, "
            "or ongoing behavior rather than a single incident."
        ),
        # Matches pattern key: 'attacked'
        "attacked": (
            "Physical or violent attack against the victim, including assault, "
            "beating, or hands-on abuse."
        ),
        # Matches pattern key: 'out_of_control'
        "out_of_control": (
            "The situation or behavior is described as out of control, "
            "escalating, or unable to be stopped."
        ),
        # Additional severity concepts (not yet wired into pattern regex):
        "violent": (
            "Explicit descriptions of violence or violent behavior, including "
            "physical harm, threats of violence, or extremely aggressive acts."
        ),
        "obscene": (
            "Obscene, graphic, or extremely explicit sexual content, including "
            "obscene material or obscene communications involving minors."
        ),
        "assault": (
            "Sexual abuse or physical assault against the victim, including "
            "forcible contact, penetration, or repeated assaultive conduct."
        ),
        "abuse": (
            "Ongoing or serious abuse of the victim, including sexual abuse, "
            "physical abuse, emotional abuse, or exploitation over time."
        ),
        # Matches pattern key: 'depictions'
        "depictions": (
            "Depictions, images, or visual recordings of child sexual abuse or "
            "exploitation, including child sexual abuse material and explicit "
            "imagery of minors."
        ),
    }

    def __init__(self, semantic_model: Optional[Any] = None, enable_ml: bool = True):
        """
        Initialize SemanticSeverity.

        Args:
            semantic_model: Optional sentence-transformers model instance.
                If provided, we use it directly (e.g., from MLModelManager).
                If None and enable_ml is True, we will try MLModelManager
                first, then fall back to a local SentenceTransformer.
            enable_ml: If False, disables ML entirely and always returns [].
        """
        self.enable_ml = enable_ml
        self.model = semantic_model
        self._concept_embeddings: Optional[Any] = None
        self._concept_keys: List[str] = list(self._SEVERITY_CONCEPTS.keys())

        if not self.enable_ml:
            return

        # 1) If caller passed a model (e.g. via MLModelManager), use it.
        # 2) Otherwise, try MLModelManager to keep centralized control.
        # 3) If that fails (e.g., import issues in ad‑hoc scripts), fall back
        #    to a local SentenceTransformer instance.
        if self.model is None:
            # Try MLModelManager first (centralized, configurable)
            try:
                from .ml_models import get_global_ml_manager

                ml_manager = get_global_ml_manager(enable_ml=True)
                self.model = ml_manager.get_model("semantic")
            except Exception as exc:  # pragma: no cover - defensive
                warnings.warn(
                    f"SemanticSeverity: failed to obtain semantic model from "
                    f"MLModelManager: {exc}"
                )
                self.model = None

        if self.model is None:
            # Fallback: manage our own lightweight sentence-transformer
            try:
                from sentence_transformers import SentenceTransformer

                self.model = SentenceTransformer("all-MiniLM-L6-v2")
            except Exception as exc:  # pragma: no cover - defensive
                warnings.warn(
                    f"SemanticSeverity: failed to load semantic model via "
                    f"sentence-transformers: {exc}"
                )
                self.model = None

        if self.model is None or np is None:
            warnings.warn(
                "SemanticSeverity: semantic model or numpy unavailable. "
                "Semantic severity phrases will be disabled."
            )
        else:
            self._precompute_concept_embeddings()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def is_available(self) -> bool:
        """Return True if semantic severity detection is available."""
        return bool(self.model is not None and self._concept_embeddings is not None and np is not None)

    def get_severity_scores(
        self,
        text: str,
        min_score: float = 0.35,
    ) -> List[SeverityPhraseScore]:
        """
        Compute similarity scores between case text and severity concepts.

        Args:
            text: Full case text.
            min_score: Minimum cosine similarity to return a phrase.

        Returns:
            List of SeverityPhraseScore sorted by descending score.
            Empty list if model is unavailable or text is empty.
        """
        if not text or not self.is_available():
            return []

        try:
            # Encode case text and compute cosine similarity to each concept
            case_emb = self.model.encode(  # type: ignore[attr-defined]
                text,
                normalize_embeddings=True,
            )
            concept_embs = self._concept_embeddings
            if concept_embs is None:
                return []

            # Cosine similarity for normalized vectors is just dot product
            # Ensure arrays are numpy arrays
            case_vec = np.asarray(case_emb)
            concept_mat = np.asarray(concept_embs)

            # concept_mat: (num_concepts, dim)
            # case_vec: (dim,)
            sims = concept_mat @ case_vec  # type: ignore[operator]

            scores: List[SeverityPhraseScore] = []
            for key, sim in zip(self._concept_keys, sims):
                score = float(sim)
                if score >= min_score:
                    scores.append(SeverityPhraseScore(key=key, score=score))

            scores.sort(key=lambda s: s.score, reverse=True)
            return scores
        except Exception as exc:  # pragma: no cover - defensive
            warnings.warn(f"SemanticSeverity: error computing scores: {exc}")
            return []

    def get_severity_phrases(
        self,
        text: str,
        min_score: float = 0.35,
        top_k: Optional[int] = None,
    ) -> List[str]:
        """
        Get semantic severity phrase keys for a case.

        Args:
            text: Full case text.
            min_score: Minimum cosine similarity to return a phrase.
            top_k: Optional max number of phrases to return.

        Returns:
            List of phrase keys (e.g., ['dangerous', 'continue']).
        """
        scores = self.get_severity_scores(text, min_score=min_score)
        if top_k is not None and top_k > 0:
            scores = scores[:top_k]
        return [s.key for s in scores]

    def enhance_case_with_semantic_severity(
        self,
        case: Dict[str, Any],
        min_score: float = 0.35,
        top_k: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Add semantic severity information to a case dict.

        Writes to:
            case['ml_features']['semantic_severity'] = {
                'phrases': [...],          # phrase keys (aligned with pattern layer)
                'scores': {key: float},    # cosine scores
            }

        Does **not** modify existing regex-based 'severity_phrases'; this can
        be merged later in the Merge Processing layer.
        """
        if not case:
            return case

        if not self.is_available():
            # Ensure ml_features exists even if we couldn't compute anything
            if "ml_features" not in case:
                case["ml_features"] = {}
            case["ml_features"].setdefault("semantic_severity", {"phrases": [], "scores": {}})
            return case

        # Get text in the same flexible way as other ML modules
        case_text = (
            case.get("case_text")
            or (case.get("raw_data") or {}).get("case_text")  # type: ignore[union-attr]
            or (case.get("extracted_features") or {}).get("case_text")  # type: ignore[union-attr]
            or ""
        )

        if not isinstance(case_text, str) or not case_text.strip():
            if "ml_features" not in case:
                case["ml_features"] = {}
            case["ml_features"].setdefault("semantic_severity", {"phrases": [], "scores": {}})
            return case

        scores = self.get_severity_scores(case_text, min_score=min_score)
        if top_k is not None and top_k > 0:
            scores = scores[:top_k]

        phrases = [s.key for s in scores]
        score_map: Dict[str, float] = {s.key: s.score for s in scores}

        if "ml_features" not in case:
            case["ml_features"] = {}

        case["ml_features"]["semantic_severity"] = {
            "phrases": phrases,
            "scores": score_map,
        }

        return case

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _precompute_concept_embeddings(self) -> None:
        """Precompute normalized embeddings for severity concepts."""
        if self.model is None or np is None:
            return

        try:
            sentences = [self._SEVERITY_CONCEPTS[k] for k in self._concept_keys]
            emb = self.model.encode(  # type: ignore[attr-defined]
                sentences,
                normalize_embeddings=True,
            )
            self._concept_embeddings = emb
        except Exception as exc:  # pragma: no cover - defensive
            warnings.warn(f"SemanticSeverity: failed to precompute embeddings: {exc}")
            self._concept_embeddings = None


def enhance_case_with_semantic_severity(
    case: Dict[str, Any],
    min_score: float = 0.35,
    top_k: Optional[int] = None,
    semantic_model: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Convenience function for one-off enhancement of a single case.

    This is primarily for testing and quick experiments; production code
    should prefer creating a `SemanticSeverity` instance and reusing it.
    """
    detector = SemanticSeverity(semantic_model=semantic_model)
    return detector.enhance_case_with_semantic_severity(case, min_score=min_score, top_k=top_k)

