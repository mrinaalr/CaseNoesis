"""
Extract explicit perpetrator admissions from ICAC case narrative text.

Identifies attributed offender speech (direct quotes and tight paraphrases) about
harm, recidivism, sexual interest, technology use, or minimization.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

QUOTE_MAX = 250
CONTEXT_MAX = 140
LOOKBACK = 280

_ICAC_TOPICS = frozenset({"csam", "enticement", "sextortion", "trafficking", "ai_csam"})

_ICAC_CONTEXT_RE = re.compile(
    r"\b("
    r"child|children|minor|minors|juvenile|underage|"
    r"csam|pornograph|molest|groom|lure|entic|sextort|traffick|"
    r"sexual\s+(?:abuse|conduct|exploit)|"
    r"predator|icac|cybertip|victim"
    r")\b",
    re.I,
)

_PERP_ROLE = (
    r"(?:the[ ]+)?(?:suspect|defendant|offender|perpetrator|accused|"
    r"teacher|pastor|minister|youth[ ]+minister|coach|"
    r"man|woman|boy|girl)"
)
# Proper names only (4+ chars excludes "The", "And", etc.)
_PERP_NAME = r"[A-Z][a-z]{4,}(?:[ ]+[A-Z][a-z]{2,}){0,2}"
_PERP_NOUN = rf"(?:{_PERP_ROLE}|{_PERP_NAME})"

_AUTHORITY = (
    r"(?:detectives?|investigators?|police|agents?|authorities|"
    r"deputies|troopers|the\s+FBI|FBI|ICE|CBP|prosecutors?)"
)

# Hard reject: victim/family/official attribution in the local window before the match.
_EXCLUSION_RES: Tuple[re.Pattern, ...] = (
    re.compile(
        r"\b(?:victim|survivor|minor|child|girl|boy|"
        r"mother|father|wife|husband|parent|family)\s+(?:said|stated|told)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:Judge|Prosecutor|Attorney|Special\s+Agent|Detective|Officer)\s+"
        r"[A-Z][a-z]+\s+(?:said|stated|wrote)\b",
    ),
    re.compile(r"\bprosecutors?\s+(?:said|stated)\b", re.I),
    re.compile(r"\baccording\s+to\s+(?:the\s+)?(?:affidavit|complaint|court)\b", re.I),
)

# Non-ICAC plea topics — reject when quote/window matches and no ICAC topic on case.
_NON_ICAC_OFFENSE_RE = re.compile(
    r"\b(?:tax(?:able|ation)?|rental\s+income|obscen(?:e|ity)\s+(?:matter|business|"
    r"video\s+arcade)|arcade\s+operations?|credit\s+card\s+billing)\b",
    re.I,
)

_META_QUOTE_RE = re.compile(
    r"\b(?:read\s+a\s+portion|court\s+documents|additional\s+investigations|"
    r"according\s+to|affidavit\s+states|investigation\s+revealed|"
    r"Press\s+Releases?\s+Page)\b",
    re.I,
)

_FIRST_PERSON_RE = re.compile(r"\b(I|my|me|myself)\b")

_THEME_RES: Tuple[Tuple[str, re.Pattern], ...] = (
    (
        "recidivism_escalation",
        re.compile(
            r"\b(out\s+of\s+control|will\s+continue|continue\s+to|habit|addiction|"
            r"can['\u2019]?t\s+stop|dangerous\s+person|again|keep\s+doing)\b",
            re.I | re.S,
        ),
    ),
    (
        "sexual_interest",
        re.compile(
            r"\b(attracted|aroused|lust(?:ing|ed)?|sexually\s+attracted|"
            r"interest\s+in\s+(?:children|minors)|pedophil|prefer(?:red|s)?\s+.*(?:child|minor|girl|boy))\b",
            re.I | re.S,
        ),
    ),
    (
        "tech_use",
        re.compile(
            r"\b(kik|discord|snapchat|instagram|facebook|telegram|whatsapp|"
            r"account|app|download(?:ed|ing)?|upload(?:ed|ing)?|"
            r"dark\s+web|chat(?:ting|ted)?|messenger|wifi|wi-fi|email|internet)\b",
            re.I | re.S,
        ),
    ),
    (
        "harm_conduct",
        re.compile(
            r"\b(molest|abuse[d|s|ing]?|sexual(?:ly)?|lure[d|s|ing]?|groom(?:ed|ing)?|"
            r"possess(?:ed|ing|ion)?|porn(?:ography)?|csam|minor|victim|touch(?:ed|ing)?|"
            r"entic(?:ed|ement|ing)?|exploit)\b",
            re.I | re.S,
        ),
    ),
    (
        "minimization",
        re.compile(
            r"\b(only\s+adult|didn['\u2019]?t\s+know|denied|unaware|"
            r"adult\s+porn(?:ography)?|not\s+guilty|thought\s+(?:she|he)\s+was)\b",
            re.I | re.S,
        ),
    ),
)

_PRON_THAT_WAS = r"(?:that\s+)?(?:(?:he|she)\s+(?:was\s+)?)?"
_PRON_THAT = r"(?:that\s+)?(?:(?:he|she)\s+)?"
_FRAME_PATTERNS: Tuple[Tuple[str, str, re.Pattern], ...] = (
    (
        "told_authority",
        "direct",
        re.compile(
            rf"\b{_PERP_NOUN}\s+told\s+{_AUTHORITY}\s*[:,]?\s*"
            rf'[""\u201c\u2018]([^""\u201d\u2019]{{8,{QUOTE_MAX}}})',
            re.I | re.S,
        ),
    ),
    (
        "perp_proximate_admitted_quote",
        "direct",
        re.compile(
            rf"\b{_PERP_NOUN}\b[^.]{{0,100}}?\badmit(?:ted|s|ting)\s+(?:that\s+)?"
            rf"{_PRON_THAT_WAS}"
            rf'[""\u201c\u2018]([^""\u201d\u2019]{{8,{QUOTE_MAX}}})',
            re.I | re.S,
        ),
    ),
    (
        "admitted_quote",
        "direct",
        re.compile(
            rf"\b{_PERP_NOUN}\s+admit(?:ted|s|ting)\s+{_PRON_THAT_WAS}"
            rf'[""\u201c\u2018]([^""\u201d\u2019]{{8,{QUOTE_MAX}}})',
            re.I | re.S,
        ),
    ),
    (
        "admitted_because_quote",
        "direct",
        re.compile(
            rf"\b{_PERP_NOUN}\s+admit(?:ted|s|ting)\s+{_PRON_THAT}"
            rf"[^.]{{0,160}}?\bbecause\s+"
            rf'[""\u201c\u2018]([^""\u201d\u2019]{{8,{QUOTE_MAX}}})',
            re.I | re.S,
        ),
    ),
    (
        "stated_became_quote",
        "direct",
        re.compile(
            rf"\b{_PERP_NOUN}\b[^.]{{0,220}}?\bstated\b[^.]{{0,100}}?\bbecame\s+a\s+"
            rf'[""\u201c\u2018]([^""\u201d\u2019]{{4,{QUOTE_MAX}}})',
            re.I | re.S,
        ),
    ),
    (
        "stated_quote",
        "direct",
        re.compile(
            rf"\b{_PERP_NOUN}\s+stated\s+{_PRON_THAT}"
            rf'[""\u201c\u2018]([^""\u201d\u2019]{{8,{QUOTE_MAX}}})',
            re.I | re.S,
        ),
    ),
    (
        "confessed_quote",
        "direct",
        re.compile(
            rf"\b{_PERP_NOUN}\s+confess(?:ed|es|ing)\s+{_PRON_THAT}"
            rf'[""\u201c\u2018]([^""\u201d\u2019]{{8,{QUOTE_MAX}}})',
            re.I | re.S,
        ),
    ),
    (
        "post_miranda",
        "direct",
        re.compile(
            r"\bpost[- ]?miranda\b[^.]{0,160}?"
            r"(?:admit(?:ted|s|ting)|confess(?:ed|es|ing)|stated)\b[^.]{0,80}?"
            rf'[""\u201c\u2018]([^""\u201d\u2019]{{8,{QUOTE_MAX}}})',
            re.I | re.S,
        ),
    ),
    (
        "he_admitted_quote",
        "direct",
        re.compile(
            rf"\b(?:He|She)\s+admit(?:ted|s|ting)\s+{_PRON_THAT_WAS}"
            rf'[""\u201c\u2018]([^""\u201d\u2019]{{8,{QUOTE_MAX}}})',
            re.I | re.S,
        ),
    ),
    (
        "admitted_he_she",
        "paraphrase",
        re.compile(
            rf"\b{_PERP_NOUN}\s+admit(?:ted|s|ting)\s+(?:he|she)\s+([^.]{{12,200}})",
            re.I | re.S,
        ),
    ),
    (
        "admitted_to",
        "paraphrase",
        re.compile(
            rf"\b{_PERP_NOUN}\b[^.]{{0,60}}?\badmit(?:ted|s|ting)\s+to\s+([^.]{{12,200}})",
            re.I | re.S,
        ),
    ),
    (
        "admitted_paraphrase",
        "paraphrase",
        re.compile(
            rf"\b{_PERP_NOUN}\s+admit(?:ted|s|ting)\s+{_PRON_THAT}"
            r"((?:was|had|only|would|could|wanted|used|downloaded|uploaded|shared|"
            r"molested|abused|lured|groomed|possessed|viewed|confessed\s+to)[^.]{8,200})",
            re.I | re.S,
        ),
    ),
    (
        "confessed_paraphrase",
        "paraphrase",
        re.compile(
            rf"\b{_PERP_NOUN}\s+confess(?:ed|es|ing)\s+{_PRON_THAT}"
            r"([^.]{12,200})",
            re.I | re.S,
        ),
    ),
    (
        "said_paraphrase",
        "paraphrase",
        re.compile(
            rf"\b{_PERP_NOUN}\s+said\s+(?:that\s+)?(?:he|she)\s+([^.]{{12,200}})",
            re.I | re.S,
        ),
    ),
    (
        "he_admitted_paraphrase",
        "paraphrase",
        re.compile(
            rf"\b(?:He|She)\s+admit(?:ted|s|ting)\s+{_PRON_THAT}"
            r"([^.]{12,200})",
            re.I | re.S,
        ),
    ),
    (
        "he_said_paraphrase",
        "paraphrase",
        re.compile(
            r"\b(?:He|She)\s+(?:also\s+)?said\s+(?:that\s+)?(?:he|she)\s+([^.]{12,200})",
            re.I | re.S,
        ),
    ),
    (
        "interview_admit_quote",
        "direct",
        re.compile(
            r"\b(?:in\s+an?\s+interview|during\s+(?:an?\s+)?interview|while\s+being\s+interviewed)"
            r"[^.]{0,120}?\b(?:admit(?:ted|s|ting)|confess(?:ed|es|ing))\b"
            r"[^.]{0,120}?"
            rf'[""\u201c\u2018]([^""\u201d\u2019]{{4,{QUOTE_MAX}}})',
            re.I | re.S,
        ),
    ),
)

_PERP_LOOKBACK_RE = re.compile(
    rf"\b(?:suspect|defendant|offender|perpetrator|accused|{_PERP_NAME})\b",
    re.I,
)


def _normalize_space(text: str) -> str:
    text = re.sub(r"\s+", " ", text.strip())
    text = text.strip(" \t,;.")
    # Trim journalistic tail clutter from paraphrase captures.
    text = re.split(r"\s+,\s*court records\b", text, maxsplit=1, flags=re.I)[0]
    text = re.split(r"\s+and\s+stated\b", text, maxsplit=1, flags=re.I)[0]
    return text.strip(" \t,;.")


def _trim(text: str, max_len: int) -> str:
    text = _normalize_space(text)
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _case_topics_set(case: Dict[str, Any], case_topics: Optional[List[str]]) -> Set[str]:
    if case_topics is not None:
        return {str(t).lower() for t in case_topics}
    raw = case.get("case_topics") or []
    if isinstance(raw, str):
        return {raw.lower()} if raw else set()
    return {str(t).lower() for t in raw}


def _has_icac_topic(topics: Set[str]) -> bool:
    return bool(topics & _ICAC_TOPICS)


def _icac_context(text: str) -> bool:
    return bool(_ICAC_CONTEXT_RE.search(text))


def _is_excluded_window(window: str) -> bool:
    # Attribution errors: victim/official voice immediately before the admission frame.
    narrow = window[-90:]
    attribution_excl = (
        _EXCLUSION_RES[0],
        _EXCLUSION_RES[1],
        _EXCLUSION_RES[2],
    )
    return any(p.search(narrow) for p in attribution_excl)


def _perp_attributed(window: str, frame: str) -> bool:
    if frame in (
        "told_authority",
        "admitted_quote",
        "admitted_because_quote",
        "perp_proximate_admitted_quote",
        "stated_quote",
        "stated_became_quote",
        "confessed_quote",
        "admitted_paraphrase",
        "confessed_paraphrase",
        "said_paraphrase",
        "admitted_he_she",
        "admitted_to",
        "interview_admit_quote",
    ):
        return True
    if frame.startswith("he_") or frame == "post_miranda":
        return bool(_PERP_LOOKBACK_RE.search(window))
    return False


def _classify_themes(quote: str) -> List[str]:
    themes = [name for name, pat in _THEME_RES if pat.search(quote)]
    return themes or ["other"]


def _confidence(
    frame: str,
    quote_type: str,
    quote: str,
) -> Optional[str]:
    if _META_QUOTE_RE.search(quote):
        return None
    if quote_type == "direct":
        if frame in ("told_authority", "post_miranda", "admitted_because_quote", "stated_became_quote", "perp_proximate_admitted_quote"):
            return "high"
        if _FIRST_PERSON_RE.search(quote):
            return "high"
        return "high"
    # paraphrase
    if frame in ("interview_admit_quote", "admitted_paraphrase", "confessed_paraphrase", "admitted_to", "admitted_he_she"):
        return "medium"
    if frame in ("said_paraphrase", "he_said_paraphrase", "he_admitted_paraphrase"):
        return "medium"
    return "medium"


def _extract_quote_from_match(match: re.Match) -> str:
    for i in range(1, (match.lastindex or 0) + 1):
        g = match.group(i)
        if g and g.strip():
            return _normalize_space(g)
    return ""


def extract_perpetrator_admissions(
    case: Dict[str, Any],
    case_topics: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Extract structured perpetrator admission records from case narrative.

    Args:
        case: Case dict with ``case_text`` (or nested in ``raw_data``).
        case_topics: Optional pre-computed topic list (avoids re-scanning).

    Returns:
        List of admission dicts with quote, frame, themes, confidence, context.
    """
    case_text = case.get("case_text") or ""
    if not case_text:
        raw = case.get("raw_data")
        if isinstance(raw, dict):
            case_text = raw.get("case_text") or ""
    if not case_text or len(case_text) < 80:
        return []

    topics = _case_topics_set(case, case_topics)
    has_topic = _has_icac_topic(topics)

    seen: Set[str] = set()
    results: List[Dict[str, Any]] = []

    for frame, quote_type, pattern in _FRAME_PATTERNS:
        for match in pattern.finditer(case_text):
            quote = _trim(_extract_quote_from_match(match), QUOTE_MAX)
            min_len = 4 if quote_type == "direct" else 10
            if len(quote) < min_len:
                continue

            start = match.start()
            window_start = max(0, start - LOOKBACK)
            window_end = min(len(case_text), match.end() + 80)
            window = case_text[window_start:window_end]
            local_before = case_text[max(0, start - 150) : start + 20]

            if _is_excluded_window(local_before):
                continue
            if not _perp_attributed(window, frame):
                continue
            if _META_QUOTE_RE.search(quote):
                continue

            context_blob = _normalize_space(window)
            icac_ok = has_topic or _icac_context(quote) or _icac_context(context_blob)
            if not icac_ok:
                continue
            if _NON_ICAC_OFFENSE_RE.search(context_blob) and not has_topic:
                continue
            if quote_type == "paraphrase" and not (
                has_topic or _icac_context(quote) or _icac_context(context_blob[:200])
            ):
                continue

            confidence = _confidence(frame, quote_type, quote)
            if confidence is None:
                continue

            dedup_key = quote[:60].lower()
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            context_start = max(0, start - 90)
            context = _trim(case_text[context_start:start] + match.group(0), CONTEXT_MAX)

            results.append(
                {
                    "quote": quote,
                    "quote_type": quote_type,
                    "frame": frame,
                    "themes": _classify_themes(quote),
                    "confidence": confidence,
                    "context": context,
                }
            )

    return results


def perpetrator_admission_themes(admissions: List[Dict[str, Any]]) -> List[str]:
    """Flat deduped theme list for faceting/filter."""
    themes: Set[str] = set()
    for rec in admissions:
        for t in rec.get("themes") or []:
            if t and t != "other":
                themes.add(t)
    return sorted(themes)
