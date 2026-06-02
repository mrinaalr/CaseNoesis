"""
Role-aware gender extraction (victim vs perpetrator).

- victim_gender: sentence-scoped, tied to gate-kept victim ages only; no victim names.
- perpetrator_gender: from perp-age windows (man/woman/male/female tokens); no name inference.

Wired from merge_processing after victim_age_gate; pattern layer sets perpetrator_gender
at extract time. No doc-wide gender field.
"""

from __future__ import annotations

import re
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

# Reuse decoy detection aligned with victim_age_gate
_DECOY_CTX_RE = re.compile(
    r"\b(?:undercover|decoy|sting|pretend(?:ed|ing)?|posing(?:\s+as)?|"
    r"believed\s+(?:he|she|they)\s+(?:was|were|to\s+be)|"
    r"believed\s+(?:to\s+be|was|were)|"
    r"(?:who|whom)\s+(?:he|she|they)\s+thought\s+was|"
    r"thought\s+(?:he|she|they)\s+(?:was|were|to\s+be)|"
    r"thought\s+(?:he|she)\s+was|"
    r"thought\s+to\s+be|"
    r"persona|alias|communicating\s+with\s+a\s+(?:\d+|child|minor)|"
    r"profile\s+of\s+a|"
    r"fictiti(?:ous|ous)|fictious|"
    r"fake\s+(?:\d{1,2}[- ]?year[- ]?olds?|\d{1,2}|a\s+(?:child|minor|girl|boy))|"
    r"posed\s+online|posed\s+as|posing\s+online|"
    r"believed\s+would)\b",
    re.IGNORECASE,
)

# Second pass: fiction / sting-label markers in the voting sentence or local window
_QUOTED_STING_AGE_GENDER_RE = re.compile(
    r'["\u201c]'
    r'[^"\u201d\n]{0,90}?'
    r'\d{1,2}[- ]?year[- ]?olds?\s+(?:girl|boy|girls|boys|male|female)'
    r'[^"\u201d\n]{0,25}?'
    r'["\u201d]',
    re.IGNORECASE,
)
_SQUOTED_STING_AGE_GENDER_RE = re.compile(
    r"['\u2018]"
    r"[^'\u2019\n]{0,90}?"
    r"\d{1,2}[- ]?year[- ]?olds?\s+(?:girl|boy|girls|boys|male|female)"
    r"[^'\u2019\n]{0,25}?"
    r"['\u2019]",
    re.IGNORECASE,
)
_AGE_GENDER_PHRASE_RE = re.compile(
    r"\d{1,2}[- ]?year[- ]?olds?\s+(?:girl|boy|girls|boys|child|minor)",
    re.IGNORECASE,
)
_PURPORTEDLY_RE = re.compile(r"\bpurportedly\b", re.IGNORECASE)

# Curly/smart quotes → straight before quoted-sting-age match (agency-style)
_CURLY_QUOTE_TRANSLATE = str.maketrans(
    {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'}
)

# Case-level: explicit UC/fiction phrase within ~80 chars of a gate-kept age (Change B)
_EXPLICIT_DECOY_NEAR_AGE_RE = re.compile(
    r"\b(?:undercover|decoy|sting|"
    r"(?:posing|posed)\s+(?:as|online)|"
    r"fictiti(?:ous|ous)|fictious|"
    r"fake\s+\d{1,2}|pretend(?:ed|ing)?\s+to\s+be)\b",
    re.IGNORECASE,
)

# Gender tokens (never parse person names)
_FEMALE_TOKEN_RE = re.compile(r"\b(?:female|girl|girls)\b", re.IGNORECASE)
_MALE_TOKEN_RE = re.compile(r"\b(?:male|boy|boys)\b", re.IGNORECASE)

# Perp age + gender token (includes woman/female for offenders; resident excluded — no gender)
_PERP_YO_GENDER_RE = re.compile(
    r"(\d{1,2})\s+year\s+old\s+(?:\w+(?:\s*,\s*\w+)*\s+)?(man|woman|male|female)\b",
    re.IGNORECASE,
)
_PERP_HYPHEN_WOMAN_RE = re.compile(
    r"(\d{1,2})\s*[-\s]*year\s*[-\s]*olds?\s+woman(?:\s+defendant)?\b",
    re.IGNORECASE,
)
_PERP_HYPHEN_MAN_RE = re.compile(
    r"(\d{1,2})\s*[-\s]*year\s*[-\s]*olds?\s+man\b",
    re.IGNORECASE,
)

# Reject gender from non-offender roles in local window
_NON_PERP_WINDOW_RE = re.compile(
    r"\b(?:"
    r"victim|victims|undercover|decoy|sting|posing|pretend|"
    r"investigator|detective|agent|agents|officer|officers|"
    r"prosecutor|attorney|judge|reporter|journalist|spokesperson|"
    r"detectives|troopers|deputies|"
    r"profile\s+of|believed\s+(?:he|she|they)\s+was|"
    r"communicating\s+with\s+a|pretending\s+to\s+be|"
    r"year\s+old\s+(?:female|girl|boy)|"
    r"(?:female|girl|boy)\s+victim|"
    r"female\s+investigator|male\s+investigator"
    r")\b",
    re.IGNORECASE,
)

_YO_WITH_GENDER_RE = re.compile(
    r"(\d{1,2})\s*[-\s]*(?:year|years)\s*[-\s]*olds?\s+(female|male|girl|boy|girls|boys)\b",
    re.IGNORECASE,
)
_VICTIM_GENDER_PHRASE_RE = re.compile(
    r"\b(?:"
    r"(?:female|male|girl|boy|girls|boys)\s+victims?|"
    r"victims?\s+(?:who\s+)?(?:were\s+)?(?:female|male|girls?|boys?)|"
    r"victim,?\s+a\s+(girl|boy|female|male)"
    r")\b",
    re.IGNORECASE,
)

# Hard block: never treat capitalized name runs as gender sources
_VICTIM_NAME_PATTERN_RE = re.compile(
    r"\b(?:victim|child|minor|juvenile)\s*,?\s+[A-Z][a-z]+\s+[A-Z][a-z]+\b",
    re.IGNORECASE,
)


def _sentence_bounds(text: str, pos: int) -> Tuple[int, int]:
    n = len(text)
    left = max(
        text.rfind(".", 0, pos),
        text.rfind("!", 0, pos),
        text.rfind("?", 0, pos),
    )
    right_dots = [text.find(c, pos) for c in ".!?"]
    right_dots = [r for r in right_dots if r != -1]
    start = (left + 1) if left != -1 else max(0, pos - 280)
    end = (min(right_dots) + 1) if right_dots else min(n, pos + 280)
    return start, end


def _age_spans(text: str, age: int) -> List[Tuple[int, int]]:
    return [(m.start(), m.end()) for m in re.finditer(rf"(?<!\d){age}(?!\d)", text)]


def _token_to_gender(token: str) -> Optional[str]:
    t = (token or "").lower()
    if t in ("female", "girl", "girls"):
        return "female"
    if t in ("male", "boy", "boys"):
        return "male"
    if t == "woman":
        return "female"
    if t == "man":
        return "male"
    return None


def _majority(values: List[str]) -> Optional[str]:
    if not values:
        return None
    from collections import Counter

    c = Counter(values)
    top, count = c.most_common(1)[0]
    if len(c) > 1 and count == 1:
        # single vote each side — ambiguous
        if c.most_common(2)[1][1] == count:
            return None
    return top


def _purportedly_near_age_gender(chunk: str, *, proximity: int = 60) -> bool:
    """purportedly within ~proximity chars of an age-gender phrase (either order)."""
    if not _PURPORTEDLY_RE.search(chunk):
        return False
    n = len(chunk)
    for m in _AGE_GENDER_PHRASE_RE.finditer(chunk):
        lo = max(0, m.start() - proximity)
        hi = min(n, m.end() + proximity)
        if _PURPORTEDLY_RE.search(chunk[lo:hi]):
            return True
    for m in _PURPORTEDLY_RE.finditer(chunk):
        lo = max(0, m.start() - proximity)
        hi = min(n, m.end() + proximity)
        if _AGE_GENDER_PHRASE_RE.search(chunk[lo:hi]):
            return True
    return False


def _decoy_vote_extra_block(sentence: str, local: str, age: int) -> bool:
    """Second-pass decoy/fiction markers in the vote sentence or ±60 local window."""
    for chunk in (sentence, local):
        straight = chunk.translate(_CURLY_QUOTE_TRANSLATE)
        if _QUOTED_STING_AGE_GENDER_RE.search(straight) or _SQUOTED_STING_AGE_GENDER_RE.search(
            straight
        ):
            return True
        if _purportedly_near_age_gender(chunk):
            return True
    return False


def _decoy_ages_in_case(text: str, ages: Iterable[int]) -> FrozenSet[int]:
    """
    Ages tied to an explicit UC/fiction phrase anywhere in case_text.

    Only flags when undercover / posing|posed as|online / fictitious|fake N /
    pretend(ed) to be appears within ±80 chars of that age digit. Does not use
    weak shorthand (meet the girl, believed would, quoted labels alone).
    """
    flagged: Set[int] = set()
    for age in sorted(set(int(a) for a in ages if 1 <= int(a) <= 17)):
        for num_start, num_end in _age_spans(text, age):
            window = text[max(0, num_start - 80) : min(len(text), num_end + 80)]
            if _EXPLICIT_DECOY_NEAR_AGE_RE.search(window):
                flagged.add(age)
                break
    return frozenset(flagged)


def _victim_gender_at_span(text: str, age: int, num_start: int, num_end: int) -> Optional[str]:
    win = text[max(0, num_start - 100) : min(len(text), num_end + 100)]
    if _DECOY_CTX_RE.search(win):
        return None
    sent_start, sent_end = _sentence_bounds(text, num_start)
    sentence = text[sent_start:sent_end]
    if _DECOY_CTX_RE.search(sentence) or _VICTIM_NAME_PATTERN_RE.search(sentence):
        return None

    local = text[max(0, num_start - 60) : min(len(text), num_end + 60)]
    if _decoy_vote_extra_block(sentence, local, age):
        return None

    if re.search(r"\b(?:investigator|prosecutor|attorney|agent|detective|reporter)\b", local, re.I):
        if not re.search(r"\b(?:victim|victims|child|children|minor|juvenile)\b", local, re.I):
            return None

    m = re.search(
        rf"(?<!\d){age}\s*[-\s]*(?:year|years)\s*[-\s]*olds?\s+(female|male|girl|boy|girls|boys)\b",
        local,
        re.I,
    )
    if m:
        return _token_to_gender(m.group(1))

    if _VICTIM_GENDER_PHRASE_RE.search(sentence) and re.search(rf"(?<!\d){age}\b", sentence):
        if _FEMALE_TOKEN_RE.search(sentence):
            return "female"
        if _MALE_TOKEN_RE.search(sentence):
            return "male"

    if re.search(rf"\b(?:victim|victims|child|minor)\b", local, re.I):
        if _FEMALE_TOKEN_RE.search(local):
            return "female"
        if _MALE_TOKEN_RE.search(local):
            return "male"

    return None


def extract_victim_gender(
    case_text: str,
    kept_victim_ages: Iterable[int],
) -> Optional[str]:
    """
    Victim gender only when tied to a gate-kept victim age in a non-decoy sentence.

    Never uses doc-wide scan; never parses victim names.
    """
    text = (case_text or "").strip()
    ages = sorted(set(int(a) for a in kept_victim_ages if 1 <= int(a) <= 17))
    if not text or not ages:
        return None

    decoy_ages = _decoy_ages_in_case(text, ages)

    votes: List[str] = []
    for age in ages:
        if age in decoy_ages:
            continue
        for num_start, num_end in _age_spans(text, age):
            g = _victim_gender_at_span(text, age, num_start, num_end)
            if g:
                votes.append(g)

    return _majority(votes)


def extract_perpetrator_gender(
    case_text: str,
    perp_ages: Optional[Iterable[int]] = None,
) -> Optional[str]:
    """
    Perpetrator gender from offender age windows (man/woman/male/female).

    Rejects investigator/agent/prosecutor/decoy windows. No name inference.
    """
    text = (case_text or "").strip()
    if not text:
        return None

    perp_set: Optional[set] = None
    if perp_ages is not None:
        perp_set = {int(a) for a in perp_ages if 18 <= int(a) <= 99}
        if not perp_set:
            # Pattern perp list empty (e.g. age span blocked by decoy-adjacent ctx) —
            # still allow clear offender gender phrases in text.
            perp_set = None
    votes: List[str] = []

    def consider(age: int, gender_token: str, start: int, end: int) -> None:
        if age < 18:
            return
        if perp_set is not None and age not in perp_set:
            return
        window = text[max(0, start - 90) : min(len(text), end + 90)]
        if _NON_PERP_WINDOW_RE.search(window):
            # Allow offender gender when arrest/defendant language anchors the window
            if not re.search(
                r"\b(?:arrested|charged|defendant|suspect|offender|convicted|sentenced|"
                r"pleaded|booked|indicted)\b",
                window,
                re.I,
            ):
                return
        if _DECOY_CTX_RE.search(window) and not re.search(
            r"\b(?:arrested|charged|defendant|suspect|offender|man|woman)\b",
            window,
            re.I,
        ):
            return
        g = _token_to_gender(gender_token)
        if g:
            votes.append(g)

    for m in _PERP_YO_GENDER_RE.finditer(text):
        consider(int(m.group(1)), m.group(2), m.start(), m.end())

    for m in _PERP_HYPHEN_WOMAN_RE.finditer(text):
        consider(int(m.group(1)), "woman", m.start(), m.end())

    for m in _PERP_HYPHEN_MAN_RE.finditer(text):
        consider(int(m.group(1)), "man", m.start(), m.end())

    # "woman defendant" near a known perp age
    if perp_set:
        for m in re.finditer(r"\bwoman\s+defendant\b", text, re.I):
            sent_start, sent_end = _sentence_bounds(text, m.start())
            sentence = text[sent_start:sent_end]
            for age in perp_set:
                if re.search(rf"(?<!\d){age}\b", sentence):
                    window = text[max(0, m.start() - 90) : m.end() + 90]
                    if not _NON_PERP_WINDOW_RE.search(window.replace("victim", "")):
                        votes.append("female")
                    break

    return _majority(votes)


def apply_role_gender_to_case(
    case: Dict[str, Any],
    *,
    kept_victim_ages: Optional[Iterable[int]] = None,
) -> Dict[str, Any]:
    """
    Populate case_demographics.victim_gender and perpetrator_gender on a case dict.
    Removes legacy case_demographics.gender if present.
    """
    text = case.get("case_text") or ""
    demo = case.get("case_demographics") or {}
    if not isinstance(demo, dict):
        demo = {}
    demo = dict(demo)
    demo.pop("gender", None)

    ages = kept_victim_ages
    if ages is None:
        ages = demo.get("ages") or []

    vg = extract_victim_gender(text, ages or [])
    if vg:
        demo["victim_gender"] = vg
    else:
        demo.pop("victim_gender", None)

    pa = case.get("perpetrator_age")
    if isinstance(pa, int):
        pa = [pa]
    elif not isinstance(pa, list):
        pa = []

    pg = extract_perpetrator_gender(text, pa)
    if pg:
        case["perpetrator_gender"] = pg
    else:
        case.pop("perpetrator_gender", None)

    if demo.get("ages") or demo.get("age_range") or demo.get("victim_gender"):
        case["case_demographics"] = demo
    elif demo:
        case["case_demographics"] = demo
    else:
        case.pop("case_demographics", None)

    return case
