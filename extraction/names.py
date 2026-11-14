"""People's names: finding them, and keeping them out of derived data.

Source text is public record and contains names. Nothing derived from it
does: no graph, no stored assertion, no tool output. Two mechanisms:

- The engine's own graph is built from typed values only (a term, an amount,
  a citation, a label). It has no free text to carry a name.
- Anything that does carry text from the record (the SDK's record graph, a
  review window shown to a person or an agent) passes through `scrub`.

`find_names` is rule-based: case captions, the "Name, 45, of City" phrasing
of a press release, honorifics and role words, and the names the SDK tagged.
It is tuned to over-mask. A capitalized phrase it wrongly takes for a name
costs a redacted word; a name it misses is a leak.
"""

from __future__ import annotations

import re
from typing import Iterable

MASK = "[name]"

_PART = r"[A-Z][a-zA-Z'’\-]+"
_INITIAL = r"[A-Z]\."
_NAME = rf"{_PART}(?:\s+(?:{_INITIAL}|{_PART})){{1,3}}(?:,?\s+(?:Jr|Sr|II|III|IV)\.?)?"
_CAPS_NAME = r"[A-Z][A-Z'’\-]+(?:\s+(?:[A-Z]\.|[A-Z][A-Z'’\-]+)){1,3}(?:,?\s+(?:JR|SR|II|III|IV)\.?)?"

_PROSECUTION = (
    r"pleaded|pled|pleads|was\s+(?:sentenced|convicted|charged|indicted|arrested|ordered|found\s+guilty|extradited)|"
    r"were\s+(?:sentenced|convicted|charged|indicted|arrested)|admitted|is\s+(?:charged|accused)|faces|agreed\s+to\s+plead"
)
_OFFICIAL_TITLE = (
    r"Judge|Justice|Attorney|Attorneys|Agent|Agents|Officer|Detective|Inspector|Sheriff|Chief|Director|Trooper|Sergeant|"
    r"Lieutenant|Captain|Counsel|Prosecutor|Investigator|Deputy|Marshal|Magistrate|Clerk|Reporter|Foreperson|Secretary|"
    r"Commissioner|General|Charge|Administrator"
)

# (hint, pattern). The hint is what the phrasing itself says about the person:
# "defendant", "official", or "person" when it says nothing.
_HINTED = tuple((hint, re.compile(p)) for hint, p in (
    # United States v. NAME / NAME, Defendant
    ("defendant", rf"(?:UNITED\s+STATES(?:\s+OF\s+AMERICA)?|United\s+States(?:\s+of\s+America)?|USA|U\.S\.)\s*,?\s+(?:v|vs|V|VS)\.?\s+(?P<n>{_CAPS_NAME}|{_NAME})"),
    ("defendant", rf"(?P<n>{_CAPS_NAME})\s*,?\s*\n?\s*(?:Defendant|DEFENDANT)s?\b"),
    ("defendant", rf"\b(?:Defendant|defendant|Co-defendant|co-defendant)\s+(?P<n>{_NAME})"),
    # A verb a release puts right after the person prosecuted
    ("defendant", rf"(?P<n>{_NAME})(?:,\s+(?:age[d]?\s+)?\d{{2}},(?:\s+(?:of|from)\s+[A-Z][\w .]+?,(?:\s+[A-Z][\w.]+,)?)?)?\s+(?:{_PROSECUTION})\b"),
    # A bare surname before the same verbs: "Sample faces a maximum penalty of"
    ("defendant", rf"(?P<n>{_PART})\s+(?:{_PROSECUTION})\b"),
    # Officials
    ("official", rf"\b(?:{_OFFICIAL_TITLE})\s+(?P<n>{_NAME})"),
    ("official", rf"/s/\s*(?P<n>{_NAME}|{_CAPS_NAME})"),
    # Phrasings that name a person and say nothing about their part
    ("person", rf"(?P<n>{_NAME}),\s+(?:age[d]?\s+)?\d{{2}}\b"),
    ("person", rf"(?P<n>{_NAME})\s+\(\d{{2}}\)"),
    ("person", rf"(?P<n>{_NAME}),\s+(?:of|from|formerly\s+of|a\s+resident\s+of|a\s+citizen\s+of|also\s+known\s+as|aka|a/k/a)\b"),
    ("person", rf"(?:also\s+known\s+as|a/k/a|aka|a\.k\.a\.)\s+[\"“]?(?P<n>{_NAME}|{_CAPS_NAME}|{_PART})"),
    ("person", rf"\b(?:Mr|Mrs|Ms|Dr|Hon)\.\s+(?P<n>{_PART}(?:\s+{_PART})?)"),
    ("person", rf"\b(?:President|CEO|Founder|Owner)\s+(?P<n>{_NAME})"),
))
_PATTERNS = tuple(pattern for _, pattern in _HINTED)
_NAME_SHAPED = re.compile(rf"(?:{_NAME}|{_CAPS_NAME}|{_PART})")

# Capitalized words that open a phrase the patterns would take for a name.
_NOT_NAMES = frozenset("""
united states america district court department justice attorney attorneys office general assistant special agent
federal bureau investigation internal revenue service homeland security postal inspection secret drug enforcement
administration northern southern eastern western central middle division county city state commonwealth government
january february march april may june july august september october november december monday tuesday wednesday thursday
friday saturday sunday count counts indictment information complaint judgment order motion plea agreement exhibit
the and for with from this that these those according court judge honorable grand jury social security medicare medicaid
bank national american first new york los angeles san francisco diego jose antonio north south east west carolina dakota
virginia hampshire jersey mexico rhode island puerto rico washington columbia chief acting deputy senior supervisory
paycheck protection program task force project safe childhood operation company corporation inc llc ltd group services
wire fraud mail money laundering conspiracy identity theft sentencing guidelines code title section act criminal civil
he she they who each both all one two three four five defendant defendants co-defendant jury court courts government
prosecutors agents investigators officers victims victim company companies it its his her their if when after before
while although according also additionally today yesterday instead however further finally then there here what which
another others some many most several former current individual individuals person persons man woman men women
investigation office bureau agency police sheriff trooper officials authorities everyone anyone nobody someone
""".split())


def _clean(name: str) -> str | None:
    name = re.sub(r"\s+", " ", name).strip(" ,.;:\"“”")
    words = [w for w in re.split(r"[\s,]+", name) if w]
    # Drop leading words that are titles or institutions, not parts of a name.
    while words and words[0].lower().strip(".") in _NOT_NAMES:
        words.pop(0)
    while words and words[-1].lower().strip(".") in _NOT_NAMES:
        words.pop()
    if not words or all(len(w.strip(".")) <= 1 for w in words):
        return None
    if sum(w.lower().strip(".") in _NOT_NAMES for w in words) * 2 > len(words):
        return None
    return " ".join(words)


def find_names(text: str, known: Iterable[str] = ()) -> set[str]:
    """Names of people in `text`, plus `known` names from another witness."""
    found: set[str] = set()
    for candidate in known:
        cleaned = _clean(str(candidate))
        if cleaned:
            found.add(cleaned)
    for pattern in _PATTERNS:
        for match in pattern.finditer(text):
            cleaned = _clean(match.group("n"))
            if cleaned:
                found.add(cleaned)
    return found


def iter_people(text: str) -> list[tuple[int, int, str]]:
    """Spans that name a person, with what the phrasing says about them:
    `(start, end, hint)`. One row per span; the most specific hint wins."""
    rank = {"defendant": 0, "official": 1, "person": 2}
    best: dict[tuple[int, int], str] = {}
    for hint, pattern in _HINTED:
        for match in pattern.finditer(text):
            if _clean(match.group("n")) is None:
                continue
            span = match.span("n")
            if span not in best or rank[hint] < rank[best[span]]:
                best[span] = hint
    return [(start, end, hint) for (start, end), hint in sorted(best.items())]


def is_name(value: str) -> bool:
    """True when `value` is shaped like a person's name and is not an institution."""
    return bool(_NAME_SHAPED.fullmatch(value.strip())) and _clean(value) is not None


def person_key(value: str) -> tuple[str, str]:
    """`(surname, given)` in lower case, for telling two mentions of one person apart."""
    parts = [part.strip(".,'’-").lower() for part in (_clean(value) or value).split()]
    parts = [part for part in parts if part and part not in ("jr", "sr", "ii", "iii", "iv")]
    return (parts[-1], parts[0]) if len(parts) > 1 else (parts[0] if parts else "", "")


def name_tokens(names: Iterable[str]) -> set[str]:
    """Full names plus each distinctive part, so a later bare surname is masked too."""
    tokens: set[str] = set()
    for name in names:
        tokens.add(name)
        parts = [part.strip(".'’-") for part in re.split(r"[\s,]+", name)]
        parts = [part for part in parts if part and part.lower() not in ("jr", "sr", "ii", "iii", "iv")]
        for index, bare in enumerate(parts):
            # The surname is masked whatever its length ("Doe", "Wu"). Other
            # parts need four letters, so a middle initial masks nothing else.
            minimum = 2 if index == len(parts) - 1 and len(parts) > 1 else 4
            if len(bare) >= minimum and bare.lower() not in _NOT_NAMES:
                tokens.add(bare)
    return tokens


def mask_pattern(names: Iterable[str]) -> re.Pattern[str] | None:
    tokens = sorted(name_tokens(names), key=len, reverse=True)
    if not tokens:
        return None
    body = "|".join(r"\s+".join(re.escape(part) for part in token.split()) for token in tokens)
    # Bounded by anything that is not a letter or digit, so a short surname
    # cannot match inside a hash or an identifier.
    return re.compile(rf"(?<![A-Za-z0-9])(?:{body})(?:['’]s)?(?![A-Za-z0-9])", re.IGNORECASE)


def scrub(value: str, pattern: re.Pattern[str] | None) -> str:
    """`value` with every name replaced by the mask. Consecutive masks collapse."""
    if pattern is None or not value:
        return value
    masked = pattern.sub(MASK, value)
    return re.sub(rf"{re.escape(MASK)}(?:[\s,.]*{re.escape(MASK)})+", MASK, masked)


def scrub_text(text: str, known: Iterable[str] = ()) -> str:
    """Convenience: find the names in `text` and mask them in it."""
    return scrub(text, mask_pattern(find_names(text, known)))


def leaks(value: str, names: Iterable[str]) -> list[str]:
    """Full names from `names` that still occur in `value` as whole words.
    Empty means clean."""
    remaining = []
    for name in names:
        if " " not in name:
            continue
        body = r"\s+".join(re.escape(part) for part in name.split())
        if re.search(rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])", value, re.IGNORECASE):
            remaining.append(name)
    return sorted(remaining)
