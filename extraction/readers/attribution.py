"""Whose a value is, read from the order of the sentence.

A record with one defendant needs no reader for this. A record with several
says "A was sentenced to 87 months. B received 24 months and was ordered to
pay $2 million", and each term and amount belongs to one of them.

This reader takes every term, amount and event trigger and looks for the
person it belongs to:

1. The nearest person named before it in the same sentence, or the people
   joined with that one ("A, B and C were each sentenced to").
2. If the sentence names no one before the value and opens with a pronoun or
   "the defendant", the person the sentence before it was about.
3. In a court filing, the person named in the nearest "DEFENDANT:" line above.

Officials are never the answer: a judge who imposes a sentence is named in
the same sentence as the term. A person is taken for an official when any
mention of them carries a title.

It asserts spans, not names. The pipeline turns each person span into the
record's person number, and that number is the role the vote is on.
"""

from __future__ import annotations

import re
from typing import Any

from extraction import fields, names, spans as sp
from extraction.readers import Doc, assertion, register_reader
from extraction.readers.clause import _OFFICIAL_AFTER, _OFFICIAL_BEFORE, _VICTIM_BEFORE

VERSION = "clause_subject_1.0"
METHOD = "clause_subject"

_BETWEEN = names.LIST_GAP
_CARRIED = re.compile(
    r"^\W*(?:(?:In\s+addition|Additionally|Also|Further|Finally|According\s+to\s+[^,]{3,60}),\s+)?"
    r"(?:He|She|They|The\s+defendants?|Both\s+(?:men|women|defendants)|Each\s+defendant)\b"
)
_OBJECT_PRONOUN = re.compile(r"\b(?:sentenced|ordered|directed|required)\s+(?:him|her|them)\b", re.I)
_DEFENDANT_LINE = re.compile(r"^\s*DEFENDANT(?:'S\s+NAME|\s+NAME)?\s*:\s*", re.M)


def people_in(text: str) -> list[tuple[int, int, str]]:
    """Mentions of people who are not officials or victims: `(start, end, surname)`."""
    mentions = names.iter_mentions(text)
    excluded = set()
    for start, end, surname in mentions:
        before, after = text[max(0, start - 70): start], text[end: end + 110]
        if _OFFICIAL_BEFORE.search(before) or _OFFICIAL_AFTER.match(after) or _VICTIM_BEFORE.search(before):
            excluded.add(surname)
    return [mention for mention in mentions if mention[2] not in excluded]


def _group(text: str, mentions: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """The last mention, with the names joined to it by commas and "and"."""
    group = [mentions[-1]]
    for mention in reversed(mentions[:-1]):
        if not _BETWEEN.match(text[mention[1]: group[0][0]]):
            break
        group.insert(0, mention)
    return group


def _one_per_person(group: list[tuple[int, int, str]]) -> list[list[int]]:
    seen, out = set(), []
    for start, end, surname in group:
        if surname not in seen:
            seen.add(surname)
            out.append([start, end])
    return out


def subjects(doc: Doc, people: list[tuple[int, int, str]], start: int, end: int) -> tuple[list[list[int]], float, str]:
    """Person spans a value at `[start, end)` belongs to, with a confidence and the rule used."""
    text = doc.text
    ss, se = sp.sentence_at(text, start, end)
    ss = max(ss, start - 900)
    inside = [m for m in people if ss <= m[0] and m[1] <= start]
    if inside:
        return _one_per_person(_group(text, inside)), 0.75, "same_sentence"
    sentence = text[ss:se]
    if _CARRIED.match(sentence) or _OBJECT_PRONOUN.search(sentence):
        previous = [span for span in sp.sentence_spans(text) if span[1] <= ss][-2:]
        for ps, pe in reversed(previous):
            earlier = [m for m in people if ps <= m[0] and m[1] <= pe]
            if earlier:
                # The sentence before was about its first-named person or group.
                first = [earlier[0]]
                for mention in earlier[1:]:
                    if not _BETWEEN.match(text[first[-1][1]: mention[0]]):
                        break
                    first.append(mention)
                return _one_per_person(first), 0.6, "carried_from_previous_sentence"
    if doc.kind == "court":
        lines = [match.end() for match in _DEFENDANT_LINE.finditer(text, 0, start)]
        if lines:
            named = [m for m in people if lines[-1] <= m[0] <= lines[-1] + 3]
            if named:
                return _one_per_person(named[:1]), 0.7, "defendant_line"
    return [], 0.0, "none"


def read(doc: Doc) -> list[dict[str, Any]]:
    people = people_in(doc.text)
    if not people:
        return []
    out: list[dict[str, Any]] = []
    for field_name in fields.ATTRIBUTABLE:
        for start, end, _value, _extras in fields.ITERATORS[field_name](doc.text):
            spans, confidence, rule = subjects(doc, people, start, end)
            if spans:
                out.append(assertion("attribution", None, None, METHOD, VERSION, confidence, start, end,
                                     of=field_name, people=spans, rule=rule))
    return out


register_reader("attribution", ("press", "court"), read, version=VERSION, order=30)
