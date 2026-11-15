"""People's names: finding them, and keeping them out of derived data.

Source text is public record and contains names. Nothing derived from it
does: no graph, no stored assertion, no tool output. Two mechanisms:

- The engine's own graph is built from typed values only (a term, an amount,
  a citation, a label). It has no free text to carry a name.
- Anything that does carry text from the record (the SDK's record graph, a
  review window shown to a person or an agent) passes through `scrub`.

`find_names` is rule-based: case captions, the "Name, 45, of City" phrasing
of a press release, honorifics and role words, and the names the SDK tagged.
`find_unlabeled` adds, for masking only, any run of two to four capitalized
words inside a sentence: a name with no label before it ("told Maria Lopez",
"an account held by Robert Chen"). Such a phrase is masked whole and as
written, never word by word, so "Child Exploitation Unit" does not mask the
word "child". It is tuned to over-mask. A capitalized
phrase it wrongly takes for a name costs a redacted word; a name it misses is
a leak.

`person_entities` is a second, independent detector: Stanza's named-entity
model, when it is installed. The final check of anything that leaves the
engine runs both, so a name the rules miss is still caught.
"""

from __future__ import annotations

import re
from typing import Iterable

MASK = "[name]"

_PART = r"[A-Z][a-zA-Z'’\-]+"
_INITIAL = r"[A-Z]\."
_NAME = rf"{_PART}(?:\s+(?:{_INITIAL}|{_PART})){{1,3}}(?:,?\s+(?:Jr|Sr|II|III|IV)\.?)?"
_CAPS_NAME = r"[A-Z][A-Z'’\-]+(?:\s+(?:[A-Z][A-Z'’\-]+|[A-Z]\.?(?![A-Za-z]))){1,3}(?:,?\s+(?:JR|SR|II|III|IV)\.?)?"
# What may stand between two names of one list: ", 44, of Tampa, Florida, and ".
LIST_GAP = re.compile(
    r"^(?:,\s+(?:age[d]?\s+)?\d{2})?(?:,\s+(?:of|from)\s+[A-Z][\w.' -]+?(?:,\s+[A-Z][\w.' -]+?)?)?\s*,?\s*(?:and\s+|both\s+of\s+)?$"
)

_PROSECUTION = (
    r"pleaded|pled|pleads|was\s+(?:sentenced|resentenced|convicted|charged|indicted|arrested|ordered|found\s+guilty|extradited)|"
    r"were\s+(?:sentenced|convicted|charged|indicted|arrested|found\s+guilty|ordered)|admitted|(?:is|are)\s+(?:charged|accused)|"
    r"faces|agreed\s+to\s+plead|entered\s+(?:a|the|his|her|their)\s+(?:guilty\s+)?pleas?"
)
# A name in capitals on one line of a caption or a form.
_CAPS_LINE = r"[A-Z][A-Z'’\-]+(?:[ \t]+(?:[A-Z][A-Z'’\-]+|[A-Z]\.?(?![A-Za-z]))){1,3}(?:,?[ \t]+(?:JR|SR|II|III|IV)\.?)?"
_OFFICIAL_TITLE = (
    r"Judge|Justice|Attorney|Attorneys|Agent|Agents|Officer|Detective|Inspector|Sheriff|Chief|Director|Trooper|Sergeant|"
    r"Lieutenant|Captain|Counsel|Prosecutor|Investigator|Deputy|Marshal|Magistrate|Clerk|Reporter|Foreperson|Secretary|"
    r"Commissioner|General|Charge|Administrator"
)

# (hint, pattern). The hint is what the phrasing itself says about the person:
# "defendant", "official", or "person" when it says nothing.
_HINTED = tuple((hint, re.compile(p, re.MULTILINE)) for hint, p in (
    # United States v. NAME / NAME, Defendant
    ("defendant", rf"(?:UNITED\s+STATES(?:\s+OF\s+AMERICA)?|United\s+States(?:\s+of\s+America)?|USA|U\.S\.)\s*,?\s+(?:v|vs|V|VS)\.?\s+(?P<n>{_CAPS_NAME}|{_NAME})"),
    ("defendant", rf"(?P<n>{_CAPS_NAME})\s*,?\s*\n?\s*(?:Defendant|DEFENDANT)s?\b(?!['’])"),
    # The judgment form prints counsel's name above the words "Defendant's Attorney".
    ("official", rf"(?P<n>{_CAPS_LINE}|{_NAME})[ \t]*\n[ \t]*Defendant['’]s\s+Attorney"),
    ("defendant", rf"\b(?:Defendant|defendant|Co-defendant|co-defendant)\s+(?P<n>{_NAME})"),
    # A verb a release puts right after the person prosecuted
    ("defendant", rf"(?P<n>{_NAME})(?:,\s+(?:age[d]?\s+)?\d{{2}})?(?:,\s+(?:of|from)\s+[A-Z][\w .]+?(?:,\s+[A-Z][\w .]+?)?)?,?\s+(?:{_PROSECUTION})\b"),
    # Names joined before the same verbs: "A and B are charged", "A, B and C pleaded guilty"
    ("defendant", rf"(?P<n>{_NAME})(?=(?:,\s+{_NAME}){{0,4}},?\s+and\s+{_NAME}(?:,[^.;]{{0,60}}?,)?\s+(?:{_PROSECUTION})\b)"),
    # Captions and forms: every defendant line above "Defendants.", the line under "v.", "DEFENDANT: NAME"
    ("defendant", rf"^[ \t]*(?P<n>{_CAPS_LINE})[ \t]*,(?:[ \t]*and)?[ \t]*\n(?=(?:[ \t]*{_CAPS_LINE}[ \t]*,(?:[ \t]*and)?[ \t]*\n){{0,6}}[ \t]*Defendants?\b)"),
    ("defendant", rf"^[ \t]*[vV][sS]?\.[ \t]*\n[ \t]*(?P<n>{_CAPS_LINE})(?=[ \t]+Case\s+N|[ \t]*,?[ \t]*\n)"),
    ("defendant", rf"\bDEFENDANT(?:'S\s+NAME|\s+NAME)?[ \t]*:[ \t]+(?P<n>{_CAPS_LINE})"),
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
# Two to four capitalized words inside a sentence, after a lower-case word or a comma: a name the
# phrasing gives no label. Used for masking only, never to find the people a record is about.
_UNLABELED = re.compile(rf"(?<=[a-z,;:)] )(?P<n>{_PART}(?:\s+(?:{_INITIAL}|{_PART})){{1,3}})")
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
tax evasion false return returns statement statements health care medicare medicaid securities bank
sex trafficking child children minor minors exploitation abuse sexual pornography material enticement coercion
production possession receipt distribution transportation business email compromise romance investment scam scams
elder fraud extortion sextortion kidnapping robbery firearm firearms weapon weapons drug drugs controlled substance
substances unit center centre program programs network crimes crime cyber computer intrusion access device devices
racketeering corrupt organizations influenced travel act forced labor labour smuggling alien aliens human
economic injury disaster loan loans relief cash app venmo zelle paypal western union moneygram bitcoin crypto
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


def find_unlabeled(text: str) -> set[str]:
    """Capitalized runs of two to four words inside a sentence, after a lower-case word or a comma:
    names the phrasing gives no label. Too loose to say who a record is about; right for masking."""
    found: set[str] = set()
    for match in _UNLABELED.finditer(text):
        cleaned = _clean(match.group("n"))
        if cleaned and " " in cleaned:
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
    people = [[start, end, hint] for (start, end), hint in sorted(best.items())]
    # "A, 38, of X, B, 61, of Y, and C, 35, of Z, are charged": what the phrasing
    # says of the last name in a list, it says of every name in it.
    for index in range(len(people) - 2, -1, -1):
        here, after = people[index], people[index + 1]
        if here[2] == "person" and after[2] == "defendant" and here[1] <= after[0] and LIST_GAP.match(text[here[1]: after[0]]):
            here[2] = "defendant"
    return [(start, end, hint) for start, end, hint in people]


def iter_mentions(text: str, known: Iterable[str] = ()) -> list[tuple[int, int, str]]:
    """Every place a person the record names is mentioned again, by full name
    or by surname: `(start, end, surname)`. The surname is lower case and is
    only ever held in memory, to tell one person's mentions from another's."""
    found = find_names(text, known)
    surnames = {person_key(name)[0] for name in found if " " in name}
    pattern = mask_pattern(found)
    if pattern is None:
        return []
    out = []
    for match in pattern.finditer(text):
        surface = re.sub(r"['’]s$", "", match.group(0))
        surname = person_key(surface)[0]
        if surname in surnames and surface[:1].isupper():
            out.append((match.start(), match.start() + len(surface), surname))
    return out


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


def mask_pattern(names: Iterable[str], whole: Iterable[str] = ()) -> re.Pattern[str] | None:
    """One pattern for every name: `names` with each distinctive part, in any case; `whole` only as
    written."""
    tokens = sorted(name_tokens(names), key=len, reverse=True)
    phrases = sorted(set(whole) - set(tokens), key=len, reverse=True)
    if not tokens and not phrases:
        return None
    join = lambda items: "|".join(r"\s+".join(re.escape(part) for part in item.split()) for item in items)  # noqa: E731
    body = "|".join(([f"(?i:{join(tokens)})"] if tokens else []) + ([join(phrases)] if phrases else []))
    # Bounded by anything that is not a letter or digit, so a short surname
    # cannot match inside a hash or an identifier.
    return re.compile(rf"(?<![A-Za-z0-9])(?:{body})(?:['’]s)?(?![A-Za-z0-9])")


def masker(text: str, known: Iterable[str] = ()) -> re.Pattern[str] | None:
    """The pattern that masks every name in `text`: labeled names and their parts, unlabeled ones whole."""
    return mask_pattern(find_names(text, known), find_unlabeled(text))


def scrub(value: str, pattern: re.Pattern[str] | None) -> str:
    """`value` with every name replaced by the mask. Consecutive masks collapse."""
    if pattern is None or not value:
        return value
    masked = pattern.sub(MASK, value)
    return re.sub(rf"{re.escape(MASK)}(?:[\s,.]*{re.escape(MASK)})+", MASK, masked)


def scrub_text(text: str, known: Iterable[str] = ()) -> str:
    """Convenience: find the names in `text` and mask them in it."""
    return scrub(text, masker(text, known))


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


_NER = None


def person_entities(text: str) -> list[str]:
    """Person names in `text` by Stanza's named-entity model: a detector independent of the rules
    above. Empty when Stanza or its English model is not installed."""
    global _NER
    if not text.strip():
        return []
    if _NER is None:
        try:
            import stanza

            _NER = stanza.Pipeline("en", processors="tokenize,ner", device="cpu", verbose=False, download_method=None)
        except Exception:  # not installed: the rules stand alone
            _NER = False
    if _NER is False:
        return []
    found = []
    for entity in _NER(text).ents:
        if entity.type == "PERSON" and MASK not in entity.text and _clean(entity.text) is not None:
            found.append(entity.text)
    return sorted(set(found))


def ner_available() -> bool:
    person_entities("Jane Roe wrote.")
    return bool(_NER)


def text_values(serialized: str) -> str:
    """The free text in a serialized graph: every JSON string with a space in it, one per line."""
    import json

    out: list[str] = []

    def walk(node) -> None:
        if isinstance(node, str):
            if " " in node and any(c.isalpha() for c in node):
                out.append(node)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    decoder, index = json.JSONDecoder(), 0
    while index < len(serialized):
        while index < len(serialized) and serialized[index].isspace():
            index += 1
        if index >= len(serialized):
            break
        node, index = decoder.raw_decode(serialized, index)
        walk(node)
    return "\n".join(out)


def independent_leaks(serialized: str) -> list[str]:
    """Person names Stanza finds in a serialized graph's free text, after masking."""
    return person_entities(text_values(serialized))
