"""The field registry and the span gate.

A field is declared once: its roles, which roles are never stored as a value,
and a typed support check. `gate_assertion` is the single choke point every
assertion passes. It narrows the asserted span to the one typed token inside
it, re-reads the value from the text at that span, and drops the span when the
text does not support the claim. The value a reader sent is never trusted over
the text.

Two shapes of field:

    mention   the value is read from the span (a term, an amount, a citation).
              Readers vote on the role of each span.
    tag       the value is a label from a closed vocabulary (a scheme type, a
              channel). The span is the cue. Readers vote on each label.

To add a field, write a support function and call `register`. Nothing else in
the engine names a field.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dataclass_field
from typing import Any, Callable, Iterator

from extraction import spans as sp

Support = tuple[bool, str, int, int, Any, dict[str, Any]]


@dataclass(frozen=True)
class FieldSpec:
    name: str
    shape: str  # "mention" | "tag"
    roles: tuple[str, ...]
    # Roles a reader may assert that are never stored as a value. They exist so
    # a reader can say "this is not one" and contest another reader.
    excluded_roles: tuple[str, ...] = ()
    support: Callable[[str, int, int, dict[str, Any]], Support] | None = None
    # Closed vocabulary for a tag field. Empty means the profile supplies it.
    vocabulary: tuple[str, ...] = ()
    # True when the role is not from a fixed list: an attribution's role is the
    # person it points at.
    open_roles: bool = False
    description: str = ""
    extras: dict[str, Any] = dataclass_field(default_factory=dict)


_REGISTRY: dict[str, FieldSpec] = {}


def register(spec: FieldSpec) -> FieldSpec:
    _REGISTRY[spec.name] = spec
    return spec


def get(name: str) -> FieldSpec | None:
    return _REGISTRY.get(name)


def all_fields() -> list[FieldSpec]:
    return list(_REGISTRY.values())


# ---------------------------------------------------------------------------
# Typed tokens. Each `iter_*` yields (start, end, value, extras) over a string.
# Readers and the gate use the same iterator, so a reader's candidate span and
# the gate's canonical span are the same span.
# ---------------------------------------------------------------------------

MONEY_RE = re.compile(
    r"\$\s?\d(?:[\d,]*\d)?(?:\.\d+)?"
    r"(?:(?:\s+|-)(?:hundred\s+)?(?:thousand|million|billion|trillion)\b|\s?(?:[MB]|[mb]n)\b)?",
    re.IGNORECASE,
)
_SCALE = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12, "m": 1e6, "mn": 1e6, "b": 1e9, "bn": 1e9}


def money_value(token: str) -> float | None:
    text = sp.normalize_surface(token).lower()
    number = re.match(r"\$\s?([\d,]+(?:\.\d+)?)", text)
    if not number:
        return None
    try:
        amount = float(number.group(1).replace(",", ""))
    except ValueError:
        return None
    rest = text[number.end():].strip(" -")
    if rest.startswith("hundred"):
        amount *= 100
        rest = rest[len("hundred"):].strip()
    if rest:
        amount *= _SCALE.get(rest, 1)
    return round(amount, 2)


def iter_money(text: str) -> Iterator[tuple[int, int, Any, dict[str, Any]]]:
    for match in MONEY_RE.finditer(text):
        amount = money_value(match.group(0))
        if amount is None:
            continue
        # "$5 per share", "$20 bills": a unit price or a denomination, not a total.
        after = text[match.end(): match.end() + 24].lower()
        unit = bool(re.match(r"\s*(?:per|each|an?\s+(?:share|hour|month|day)|bills?\b|/)", after))
        yield match.start(), match.end(), amount, {"unit_price": True} if unit else {}


def iter_duration(text: str) -> Iterator[tuple[int, int, Any, dict[str, Any]]]:
    taken: list[tuple[int, int]] = []
    position = 0
    while True:
        match = sp.DURATION_RE.search(text, position)
        if match is None:
            break
        start, end = match.span()
        months = sp.duration_months(match)
        unit = match.group("unit").lower()
        if match.group("n2") and not unit.startswith(("year", "yr")):
            # "48 months, 44 months" is two terms, not one term in two units.
            end = match.end("unit")
            months = sp.duration_months(sp.DURATION_RE.fullmatch(text, start, end) or match) if sp.DURATION_RE.fullmatch(text, start, end) else None
        position = max(end, start + 1)
        if months is None:
            continue
        taken.append((start, end))
        value = re.sub(r"\s+", " ", sp.normalize_surface(text[start:end])).strip()
        yield start, end, value, {
            "months": months,
            "approx": bool(match.group("approx")),
            # "twenty-five years" has two number words and is one number, not a range.
            "range_low": match.group("low") is not None and not (
                match.group("low").lower() in sp._TENS and text[match.end("low"): match.start("n")].strip() == "-"
            ),
        }
    for match in sp.LIFE_RE.finditer(text):
        if any(s <= match.start() < e for s, e in taken):
            continue
        value = re.sub(r"\s+", " ", sp.normalize_surface(match.group(0))).strip()
        yield match.start(), match.end(), value, {"months": None, "life": True}


_SECTION = r"\d{1,5}[A-Za-z]?(?:-\d+[a-z]?)?"
_SUBSECTION = r"(?:\([A-Za-z0-9]{1,4}\))*"
STATUTE_RE = re.compile(
    # "18 U.S.C. § 1343", "18 U.S.C. §§ 1343 and 1349", and the charging-document
    # form "Title 18, United States Code, Section 1343".
    rf"(?:\b(?P<title>\d{{1,2}})\s*U\.?\s?S\.?\s?C\.?(?:\s?A\.?)?\s*,?\s*(?P<mark>§+|Sections?|Secs?\.|Subsections?)?"
    rf"|\bTitle\s+(?P<title2>\d{{1,2}})\s*,?\s+United\s+States\s+Code\s*,?\s+(?P<mark2>§+|Sections?)"
    # The judgment form's "Title & Section" column: "18:1343", "21:841(a)(1)".
    rf"|(?<![\d:.-])(?P<title3>\d{{1,2}}):(?=\d{{3,4}}[A-Za-z]?(?![\d:-])))\s*"
    rf"(?P<list>{_SECTION}{_SUBSECTION}(?:\s*(?:,\s*and|,|and|&)\s*{_SECTION}{_SUBSECTION})*)",
    re.IGNORECASE,
)
_SECTION_IN_LIST = re.compile(rf"(?P<section>{_SECTION})(?P<sub>{_SUBSECTION})")


def statute_value(title: str, section: str, sub: str = "") -> str:
    return f"{int(title)} U.S.C. § {section.upper()}{sub}"


def iter_statute(text: str) -> Iterator[tuple[int, int, Any, dict[str, Any]]]:
    """One hit per section. "18 U.S.C. §§ 1343 and 1349" is two citations."""
    for match in STATUTE_RE.finditer(text):
        title = match.group("title") or match.group("title2") or match.group("title3")
        mark = (match.group("mark") or match.group("mark2") or "").lower()
        base = match.start("list")
        plural = mark.startswith("§§") or mark.endswith("s")
        for index, part in enumerate(_SECTION_IN_LIST.finditer(match.group("list"))):
            if index and not plural:
                break  # "18 U.S.C. § 1343 and 2 others": only the first is a section
            section = part.group("section")
            start = match.start() if index == 0 else base + part.start()
            end = base + part.end()
            yield start, end, statute_value(title, section, part.group("sub")), {
                "title": str(int(title)),
                "section": section.upper(),
            }


CASE_NUMBER_RE = re.compile(
    r"\b(?P<office>\d{1,2})\s?:\s?(?P<year>\d{2}(?:\d{2})?)\s?-\s?(?P<type>cr|cv|mj|mc|po|md|CR|CV|MJ|MC|PO|MD)\s?-\s?(?P<seq>\d{1,6})\b"
)


def case_number_value(office: str, year: str, kind: str, seq: str) -> str:
    return f"{int(office)}:{year[-2:]}-{kind.lower()}-{int(seq):05d}"


def iter_case_number(text: str) -> Iterator[tuple[int, int, Any, dict[str, Any]]]:
    for match in CASE_NUMBER_RE.finditer(text):
        value = case_number_value(match["office"], match["year"], match["type"], match["seq"])
        yield match.start(), match.end(), value, {"case_type": match["type"].lower()}


_MONTHS = {
    name: number
    for number, names in enumerate(
        (
            ("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"), ("may",),
            ("june", "jun"), ("july", "jul"), ("august", "aug"), ("september", "sept", "sep"),
            ("october", "oct"), ("november", "nov"), ("december", "dec"),
        ),
        start=1,
    )
    for name in names
}
_MONTH_NAME = r"(?:Jan(?:uary|\.)?|Feb(?:ruary|\.)?|Mar(?:ch|\.)?|Apr(?:il|\.)?|May|June?|July?|Aug(?:ust|\.)?|Sep(?:tember|t\.?|\.)?|Oct(?:ober|\.)?|Nov(?:ember|\.)?|Dec(?:ember|\.)?)"
DATE_RE = re.compile(
    rf"\b(?P<mname>{_MONTH_NAME})\s+(?P<mday>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<myear>(?:19|20)\d{{2}})\b"
    rf"|\b(?P<dday>\d{{1,2}})\s+(?P<dname>{_MONTH_NAME})\s+(?P<dyear>(?:19|20)\d{{2}})\b"
    r"|(?<![\d/-])(?P<iyear>(?:19|20)\d{2})-(?P<imonth>\d{2})-(?P<iday>\d{2})(?![\d-])"
    r"|(?<![\d/])(?P<smonth>\d{1,2})/(?P<sday>\d{1,2})/(?P<syear>\d{2}(?:\d{2})?)(?![\d/])"
    # A month and a year with no day: "in March 2024". Tried last, so a full date wins.
    rf"|\b(?P<pname>{_MONTH_NAME})\s+(?:of\s+)?(?P<pyear>(?:19|20)\d{{2}})\b(?!\s*[-–]\s*\d)",
    re.IGNORECASE,
)


def _iso(year: int, month: int, day: int) -> str | None:
    if not (1 <= month <= 12 and 1 <= day <= 31 and 1900 <= year <= 2100):
        return None
    if day > (29 if month == 2 else 30 if month in (4, 6, 9, 11) else 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def iter_date(text: str) -> Iterator[tuple[int, int, Any, dict[str, Any]]]:
    for match in DATE_RE.finditer(text):
        if match["pname"]:
            # "may 2024 reports" is a verb. A month name is capitalized.
            month = _MONTHS[match["pname"].lower().rstrip(".")]
            if text[match.start()].isupper() and not re.search(r"\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?$", text[max(0, match.start() - 8): match.start()]):
                yield match.start(), match.end(), f"{int(match['pyear']):04d}-{month:02d}", {"precision": "month"}
            continue
        if match["mname"]:
            parts = (int(match["myear"]), _MONTHS[match["mname"].lower().rstrip(".")], int(match["mday"]))
        elif match["dname"]:
            parts = (int(match["dyear"]), _MONTHS[match["dname"].lower().rstrip(".")], int(match["dday"]))
        elif match["iyear"]:
            parts = (int(match["iyear"]), int(match["imonth"]), int(match["iday"]))
        else:
            year = int(match["syear"])
            if year < 100:
                year += 2000 if year <= 30 else 1900
            parts = (year, int(match["smonth"]), int(match["sday"]))
        value = _iso(*parts)
        if value:
            yield match.start(), match.end(), value, {}


_COUNT_NOUN = (
    r"(?:(?:elderly|older|additional|other|known|identified|individual|alleged|unsuspecting|vulnerable|minor|adult|foreign)\s+)*"
    r"(?:victims?|investors?|customers?|clients?|consumers?|seniors?|patients?|people|individuals?|"
    r"workers?|employees?|women|girls|men|boys|children|minors|businesses|companies|account\s+holders?)"
)
VICTIM_COUNT_RE = re.compile(
    rf"(?<![\d$.,])(?P<n>\d{{1,3}}(?:,\d{{3}})+|\d{{1,6}}|{sp.WORD_NUMBER_RE}|hundreds|thousands|dozens)\s+(?P<noun>{_COUNT_NOUN})\b",
    re.IGNORECASE,
)
_VAGUE = {"dozens": 24, "hundreds": 200, "thousands": 2000}


def iter_count(text: str) -> Iterator[tuple[int, int, Any, dict[str, Any]]]:
    for match in VICTIM_COUNT_RE.finditer(text):
        token = match["n"].lower()
        if token in _VAGUE:
            value, extras = _VAGUE[token], {"lower_bound": True, "vague": token}
        elif token.replace(",", "").isdigit():
            value, extras = int(token.replace(",", "")), {}
        else:
            parsed = sp.parse_number(token)
            if parsed is None:
                continue
            value, extras = parsed, {}
        extras["noun"] = re.sub(r"\s+", " ", match["noun"].lower())
        # The span is the number; the noun is context the reader reads.
        yield match.start("n"), match.end("n"), value, extras


# What a record says happened in the case. The value is the kind of trigger;
# a reader decides which event it reports, or that it reports none.
EVENT_TRIGGERS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern, re.IGNORECASE))
    for name, pattern in (
        ("sentence", r"\b(?:re-?)?sentenced\b|\bimposed\s+(?:the|a)\s+sentence\b|\bDate\s+of\s+Imposition\s+of\s+Judgment\b"),
        ("plead", r"\b(?:pleaded|pled|pleads|plead)\s+guilty\b|\bentered\s+(?:a|the|his|her|their)\s+(?:guilty\s+)?pleas?\b|\bguilty\s+pleas?\b"),
        ("convict", r"\bconvicted\b|\bfound\s+guilty\b|\bguilty\s+verdicts?\b"),
        ("indict", r"\bindicted\b|\b(?:returned|unsealed|handed\s+(?:up|down))\s+an?\s+(?:[\w-]+\s+){0,3}indictment\b|\bindictment\s+(?:was\s+)?(?:returned|unsealed)\b"),
        ("charge", r"\bcharged\b"),
        ("arrest", r"\barrested\b|\btaken\s+into\s+(?:federal\s+)?custody\b"),
    )
)


def iter_event(text: str) -> Iterator[tuple[int, int, Any, dict[str, Any]]]:
    hits: list[tuple[int, int, str]] = []
    for name, pattern in EVENT_TRIGGERS:
        hits += [(match.start(), match.end(), name) for match in pattern.finditer(text)]
    last_end = -1
    for start, end, name in sorted(hits):
        if start >= last_end:  # "found guilty" inside a longer trigger is one trigger
            last_end = end
            yield start, end, name, {}


def iter_conduct(text: str) -> Iterator[tuple[int, int, Any, dict[str, Any]]]:
    """Words that may report an act of the offense. The value is the words, lower case."""
    from extraction import acts

    for match in acts.TRIGGER.finditer(text):
        yield match.start(), match.end(), re.sub(r"\s+", " ", match.group(0).lower()), {}


ITERATORS: dict[str, Callable[[str], Iterator[tuple[int, int, Any, dict[str, Any]]]]] = {
    "conduct": iter_conduct,
    "event": iter_event,
    "money": iter_money,
    "sentence": iter_duration,
    "statute": iter_statute,
    "case_number": iter_case_number,
    "date": iter_date,
    "victim_count": iter_count,
}

_WINDOW = 200


def _typed_support(field_name: str) -> Callable[[str, int, int, dict[str, Any]], Support]:
    """Support check for a mention field: the span must hold one typed token.

    The window around the span is re-read with the field's iterator. The token
    that overlaps the asserted span the most becomes the span, and its parsed
    value becomes the value.
    """
    iterate = ITERATORS[field_name]

    def support(text: str, start: int, end: int, assertion: dict[str, Any]) -> Support:
        base = max(0, start - _WINDOW)
        window = text[base: min(len(text), end + _WINDOW)]
        best: tuple[int, int, int, Any, dict[str, Any]] | None = None
        for s, e, value, extras in iterate(window):
            s, e = s + base, e + base
            overlap = min(e, end) - max(s, start)
            if overlap > 0 and (best is None or overlap > best[0]):
                best = (overlap, s, e, value, extras)
        if best is None:
            return False, f"no_{field_name}_token_in_span", start, end, None, {}
        _, s, e, value, extras = best
        return True, f"{field_name}_token", s, e, value, extras

    return support


def _party_support(text: str, start: int, end: int, assertion: dict[str, Any]) -> Support:
    """A party span must be a person's name. The name itself is never the
    value: the pipeline numbers the people in a record and stores the number."""
    from extraction import names

    if not names.is_name(text[start:end]):
        return False, "span_is_not_a_person_name", start, end, None, {}
    return True, "person_name", start, end, "person", {}


ATTRIBUTABLE = ("sentence", "money", "event", "conduct")


def _attribution_support(text: str, start: int, end: int, assertion: dict[str, Any]) -> Support:
    """An attribution says a value belongs to a person. Both ends must be in
    the text: the span must hold a value of the field it names, and every
    person span must be a name. The pipeline then replaces the names with the
    record's person numbers, and that is the role the vote is on."""
    from extraction import names

    extras = assertion.get("extras") or {}
    of = str(extras.get("of") or "")
    if of not in ATTRIBUTABLE:
        return False, "attribution_of_unknown_field", start, end, None, {}
    ok, _, s, e, _, _ = _REGISTRY[of].support(text, start, end, assertion)
    if not ok:
        return False, f"attributed_span_is_not_a_{of}", start, end, None, {}
    people = extras.get("people") or []
    if not people or not all(
        isinstance(a, int) and isinstance(b, int) and 0 <= a < b <= len(text) and names.is_name(text[a:b]) for a, b in people
    ):
        return False, "attributed_person_is_not_a_name", start, end, None, {}
    return True, "attribution", s, e, f"{of}:{s}-{e}", {}


def _tag_support(text: str, start: int, end: int, assertion: dict[str, Any]) -> Support:
    """Support check for a tag field: the cue must be real text, and a reader
    that claims a cue pattern must have matched it at that span."""
    cue = text[start:end]
    if not cue.strip():
        return False, "empty_cue", start, end, None, {}
    pattern = (assertion.get("extras") or {}).get("cue_pattern")
    if pattern and not re.fullmatch(pattern, cue, re.IGNORECASE | re.DOTALL):
        return False, "cue_does_not_match_span", start, end, None, {}
    return True, "cue_span", start, end, assertion.get("value"), {}


register(FieldSpec(
    "sentence", "mention",
    roles=("imposed", "exposure", "supervised_release", "probation", "custody", "prior", "not_sentence"),
    excluded_roles=("not_sentence",),
    support=_typed_support("sentence"),
    description="A term: a duration or life. The role says which kind of term.",
))
register(FieldSpec(
    "money", "mention",
    roles=(
        "loss", "intended_loss", "restitution", "forfeiture", "fine", "exposure_fine", "proceeds",
        "special_assessment", "bail", "civil_penalty", "not_case_amount",
    ),
    excluded_roles=("not_case_amount",),
    support=_typed_support("money"),
    description="A dollar amount. The role says what the amount is.",
))
register(FieldSpec(
    "statute", "mention", roles=("cited",), support=_typed_support("statute"),
    description="A U.S. Code citation, one per section.",
))
register(FieldSpec(
    "case_number", "mention", roles=("cited",), support=_typed_support("case_number"),
    description="A federal docket number, normalized to office:yy-type-sequence.",
))
register(FieldSpec(
    "date", "mention",
    roles=("published", "filed", "sentencing", "offense", "arrest", "plea", "indictment", "verdict", "scheduled"),
    support=_typed_support("date"),
    description="A calendar date, or a month and year. The role says what happened on it. `scheduled` is a date something is set for.",
))
register(FieldSpec(
    "victim_count", "mention", roles=("victims", "not_victims"), excluded_roles=("not_victims",),
    support=_typed_support("victim_count"),
    description="A count of people or firms harmed.",
))
register(FieldSpec(
    "party", "mention", roles=("defendant", "official", "victim", "not_person"),
    excluded_roles=("official", "victim", "not_person"),
    support=_party_support,
    description="A person the record names, by number. The role says who they are in the case. The name is not stored.",
))
register(FieldSpec(
    "event", "mention",
    roles=("arrest", "complaint", "indictment", "information", "charge", "plea", "verdict", "conviction", "sentencing",
           "scheduled", "not_event"),
    excluded_roles=("scheduled", "not_event"),
    support=_typed_support("event"),
    description=(
        "Something the record says happened in the case, anchored on the words that say it. `conviction` is a "
        "conviction the record does not say came by plea or by verdict. `scheduled` and `not_event` are never stored."
    ),
))
register(FieldSpec(
    "conduct", "mention",
    roles=("setup", "contact", "deception", "demand", "threat", "transfer", "movement", "access", "recruit", "transport",
           "control", "exploit", "supply", "concealment", "detection", "not_conduct"),
    excluded_roles=("not_conduct",),
    support=_typed_support("conduct"),
    description=(
        "An act of the offense, anchored on the words that report it. The role is the kind of act. "
        "`not_conduct` is a recital of what a statute requires, which uses the same verbs."
    ),
))
register(FieldSpec(
    "attribution", "mention", roles=(), open_roles=True, support=_attribution_support,
    description=(
        "Whose a term, an amount, or an event is. The span is the value's span; the role is the record's person "
        "number, or several joined by '+' when the text gives the value to several people."
    ),
))
for _name, _vocabulary, _description in (
    ("stage", ("arrested", "charged", "plea", "convicted", "sentenced"), "A procedural stage the record reports."),
    (
        "document_type",
        (
            "complaint", "indictment", "information", "plea_agreement", "factual_basis", "judgment",
            "sentencing_memorandum", "verdict", "transcript", "order", "motion", "docket",
        ),
        "What kind of court filing the record is.",
    ),
    ("offense", (), "An offense named in words or by its statute. Vocabulary: the statute table."),
    ("scheme", (), "How the offense was carried out. Vocabulary: the domain profile."),
    ("channel", (), "The technology or medium the offender used to reach people. Vocabulary: the domain profile."),
    ("platform", (), "A named service or product the record says was used. Vocabulary: the common profile."),
):
    register(FieldSpec(
        _name, "tag", roles=("present", "boilerplate"), excluded_roles=("boilerplate",),
        support=_tag_support, vocabulary=_vocabulary, description=_description,
    ))


def gate_assertion(text: str, assertion: dict[str, Any]) -> dict[str, Any]:
    """Enforce span support. Returns a copy with `span_ok`, the canonical span,
    the value re-read from the text, and `gate_reason`. A failed assertion
    keeps its claim and loses its span."""
    out = dict(assertion)
    extras = dict(assertion.get("extras") or {})
    spec = get(str(assertion.get("field")))
    start, end = assertion.get("span_start"), assertion.get("span_end")
    ok, reason = False, "bad_offsets"
    if spec is None:
        reason = "unknown_field"
    elif not spec.open_roles and assertion.get("role") not in (None, "unknown", *spec.roles):
        reason = "role_not_in_field"
    elif start is None and end is None:
        reason = "no_span"
    elif isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(text):
        ok, reason, start, end, value, info = spec.support(text, start, end, assertion)
        if ok:
            if spec.shape == "mention":
                out["value"] = value
            extras.update(info)
    extras["gate_reason"] = reason
    out["extras"] = extras
    out["span_ok"] = 1 if ok else 0
    if ok:
        out["span_start"], out["span_end"], out["span_text"] = start, end, text[start:end]
    else:
        out["span_start"] = out["span_end"] = out["span_text"] = None
    return out
