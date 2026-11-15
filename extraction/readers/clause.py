"""Clause reader: the role of a typed token, read from the clause around it.

Where the pattern reader needs a fixed phrasing to touch the value, this one
takes every token and asks what the clause it sits in is about. It is the
grammar-free stand-in for a dependency parse: it reads which cue is nearest
the token inside the clause, not which word governs it. A parser-backed
reader would join the `dependency` family beside it.

The sentence logic is CaseLinker's clause classifier, unchanged.
"""

from __future__ import annotations

import re
from typing import Any

from extraction import acts, fields, names, spans as sp
from extraction.readers import Doc, assertion, register_reader

VERSION = "clause_1.4"
METHOD = "clause_cue"

_MONEY_CUES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (role, re.compile(cue, re.I))
    for role, cue in (
        ("special_assessment", r"\bspecial\s+assessment\b"),
        ("restitution", r"\brestitution\b"),
        ("forfeiture", r"\bforfeit\w*\b|\bmoney\s+judgment\b"),
        ("fine", r"\bfine[ds]?\b"),
        ("bail", r"\bbail\b|\bbond\b"),
        ("civil_penalty", r"\bcivil\s+penalt(?:y|ies)\b|\bsettle(?:ment|d)?\b|\bto\s+resolve\b|\bconsent\s+(?:order|decree)\b"),
        ("intended_loss", r"\bintended\s+loss\w*\b|\battempt\w*\b"),
        ("loss", r"\bloss(?:es)?\b|\blost\b|\bdefraud\w*\b|\bstole\b|\bstolen\b|\bsteal\w*\b|\bembezzl\w*\b|\bmisappropriat\w*\b|\bswindl\w*\b|\bbilk\w*\b|\bscamm?\w*\b|\bfraudulent(?:ly)?\b"),
        ("proceeds", r"\bproceeds\b|\blaunder\w*\b|\bobtained\b|\breceived\b|\bprofit\w*\b|\bnetted\b|\bgains?\b"),
        ("not_case_amount", r"\breward\b|\bgrants?\b|\bbudget\b|\bfunding\b|\bsalar(?:y|ies)\b|\bappropriat\w+\b|\bawarded\b"),
    )
)
_NEAR = 45

_DATE_CUES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (role, re.compile(cue, re.I))
    for role, cue in (
        ("filed", r"\bfiled\b|\bentered\b"),
        ("sentencing", r"\bsentenc\w+\b|\bimposition\s+of\s+judgment\b"),
        ("arrest", r"\barrest\w*\b"),
        ("indictment", r"\bindict\w+\b"),
        ("plea", r"\bple(?:aded|d|a)\b"),
        ("verdict", r"\bconvicted\b|\bverdict\b|\bfound\s+guilty\b"),
        ("offense", r"\b(?:on|in)\s+or\s+(?:about|around)\b|\bbetween\b|\bbeginning\b|\bcontinuing\b|\bthrough\b|\buntil\b"),
    )
)

_SCHEDULED_CUE = re.compile(r"\bscheduled\b|\bslated\b|\bset\s+(?:for|to)\b|\bwill\s+be\b|\bis\s+expected\b|\bawaiting\b|\bagree(?:s|d|ing)?\s+to\b", re.I)
_HYPOTHETICAL_CUE = re.compile(
    r"\bif\s+convicted\b|\bfaces?\b|\bcould\b|\bmaximum\b|\bpunishable\b|\bpresumed\s+innocent\b|\bunless\s+and\s+until\b|"
    r"\buntil\s+proven\b|\bmerely\s+(?:an?\s+)?(?:accusations?|allegations?)\b", re.I)
_TRIAL_CUE = re.compile(r"\bjur(?:y|ors)\b|\btrial\b|\bverdict\b", re.I)
_EVENT_ROLE = {"sentence": "sentencing", "plead": "plea", "convict": "conviction", "indict": "indictment", "charge": "charge", "arrest": "arrest"}

_VICTIM_CUE = re.compile(r"\bvictim\w*\b|\bdefraud\w*\b|\btarget\w*\b|\btraffick\w*\b|\bexploit\w*\b|\bharm\w*\b|\bscamm\w*\b|\bidentit(?:y|ies)\s+of\b", re.I)
_NOT_VICTIM_CUE = re.compile(
    r"\bdefendants?\b|\bco-?conspirators?\b|\b(?:were|was|been)\s+(?:charged|indicted|arrested)\b|\bagents?\b|\bofficers?\b|"
    r"\bemployees\s+of\b|\bmembers\s+of\b|\bprosecutors?\b|\bjur(?:y|ors)\b",
    re.I,
)


_OFFICIAL_BEFORE = re.compile(
    r"(?:Judge|Justice|Attorney|Attorneys|Agent|Agents|Officer|Detective|Inspector|Sheriff|Chief|Director|Trooper|Counsel|"
    r"Prosecutor|Investigator|Marshal|Magistrate|Secretary|Commissioner|General|Charge|Administrator|/s/)\s+$"
)
_OFFICIAL_AFTER = re.compile(
    r"^[ \t]*\n[ \t]*Defendant['’]s\s+Attorney|"
    r"^,?\s+(?:(?:of|for)\s+the\s+|the\s+)?(?:U\.S\.|United\s+States|Acting|Assistant|Special\s+Agent|District\s+Attorney|"
    r"Attorney\s+General|Inspector)|^\s+(?:announced|said|stated|is\s+prosecuting|prosecuted|presided|imposed|handed\s+down)\b"
)
_VICTIM_BEFORE = re.compile(r"\bvictim,?\s+$", re.I)
_DEFENDANT_BEFORE = re.compile(
    r"(?:\bdefendants?\s*:?|\bagainst|\bsentenced|\bconvicted|\bcharged|\bcharging|\bindicted|\barrested|\bv\.|\bvs\.)\s+$", re.I
)
_DEFENDANT_AFTER = re.compile(
    r"^(?:,[^.;]{0,90}?,)?\s+(?:(?:has|had|have)\s+)?(?:also\s+|today\s+|previously\s+)?(?:pleaded|pled|pleads|"
    r"(?:was|were)\s+(?:sentenced|resentenced|convicted|charged|indicted|arrested|ordered|found\s+guilty)|"
    r"admitted|faces|(?:is|are)\s+(?:charged|accused)|agreed\s+to\s+plead|entered\s+(?:a|the|his|her|their)\s+(?:guilty\s+)?pleas?|"
    r"defrauded|stole|operated|ran\s+a)\b"
    r"|^\s*,?\s*\n?\s*(?:Defendant|DEFENDANT)s?\b(?!['’])|^[ \t]+Case\s+Number\s*:|^[ \t]*,(?:[ \t]*and)?[ \t]*\n"
)


def _nearest(cues, clause: str, rel_start: int, rel_end: int) -> tuple[str | None, int]:
    best_role, best_distance = None, 1 << 30
    for role, cue in cues:
        for match in cue.finditer(clause):
            if match.end() <= rel_start:
                distance = rel_start - match.end()
            else:
                # A cue after the amount belongs to it only when it follows at
                # once ("$5,000 fine", "$2 million in restitution"). Otherwise it
                # is the next item in a list: "restitution of $X and a fine of $Y".
                distance = max(match.start() - rel_end, 0) * 3
            distance = max(distance, 0)
            if distance < best_distance:
                best_role, best_distance = role, distance
    return best_role, best_distance


def read(doc: Doc) -> list[dict[str, Any]]:
    text = doc.text
    out: list[dict[str, Any]] = []

    for start, end, value, extras in fields.iter_duration(text):
        kind = sp.sentence_kind(text, start, end)
        role = None if kind in ("unknown", "fine") else kind
        out.append(assertion("sentence", value, role, METHOD, VERSION, 0.75 if role else 0.5, start, end, clause_kind=kind))

    for start, end, value, extras in fields.iter_money(text):
        cs, ce = sp.clause_at(text, start, end)
        clause = sp.normalize_surface(text[cs:ce])
        if len(clause) != ce - cs:  # normalization changed the length; read the raw clause
            clause = text[cs:ce]
        role, distance = _nearest(_MONEY_CUES, clause, start - cs, end - cs)
        if extras.get("unit_price") or value == 0:
            role, distance = "not_case_amount", 0
        elif sp.totals_row(text, start):
            role = None  # a table cell: the words around it are other columns' headers
        if role == "fine" and (sp._EXPOSURE_CUES.search(clause) or sp.in_penalty_list(text, start)):
            role = "exposure_fine"
        confidence = 0.5 if role is None else 0.75 if distance <= _NEAR else 0.6
        out.append(assertion("money", value, role, METHOD, VERSION, confidence, start, end,
                             cue_distance=None if role is None else distance))

    for start, end, value, extras in fields.iter_date(text):
        cs, ce = sp.clause_at(text, start, end)
        role, distance = _nearest(_DATE_CUES, text[cs:ce], start - cs, end - cs)
        if role is not None and distance > _NEAR:
            role = None
        if role in ("sentencing", "plea", "verdict", None) and _SCHEDULED_CUE.search(text[cs:start]):
            role = "scheduled"  # "is scheduled to be sentenced on Aug. 3": a date set, not a date it happened
        out.append(assertion("date", value, role, METHOD, VERSION, 0.7 if role else 0.5, start, end))

    for start, end, value, extras in fields.iter_count(text):
        cs, ce = sp.clause_at(text, start, end)
        clause = text[cs:ce]
        noun_end = end + 1 + len(extras["noun"])
        local = text[max(cs, start - 60): min(ce, noun_end + 60)]
        if _NOT_VICTIM_CUE.search(text[end:noun_end + 2]) or re.search(r"defendants?|co-?conspirators?", extras["noun"]):
            role = "not_victims"
        elif _VICTIM_CUE.search(local):
            role = "victims"
        elif _NOT_VICTIM_CUE.search(local):
            role = "not_victims"
        else:
            role = "victims" if _VICTIM_CUE.search(clause) else None
        out.append(assertion("victim_count", value, role, METHOD, VERSION, 0.7 if role else 0.5, start, end))
    for start, end, kind, extras in fields.iter_event(text):
        # The whole clause decides: is this reported as done, as planned, or as a possibility?
        cs, ce = sp.clause_at(text, start, end)
        ss, se = sp.sentence_at(text, start, end)
        # Bounded: a page with no sentence breaks is one "sentence" of any length.
        cs, ss, se = max(cs, start - 600), max(ss, start - 600), min(se, end + 400)
        lead, sentence = text[cs:start], text[ss:se]
        role: str | None = _EVENT_ROLE[kind]
        if "☐" in text[max(ss, start - 30): start]:
            role = "not_event"
        elif _HYPOTHETICAL_CUE.search(sentence) and not re.search(r"\b(?:was|were|has\s+been|have\s+been)\s+(?:\w+\s+)?$", lead):
            role = "not_event"
        elif _SCHEDULED_CUE.search(lead[-60:]):
            role = "scheduled"
        elif kind == "convict":
            if re.search(r"\b(?:previously|prior)\b", lead[-40:], re.I):
                role = "not_event"
            elif _TRIAL_CUE.search(sentence):
                role = "verdict"
        elif kind == "charge":
            follow = text[end: min(se, end + 120)]
            if not re.search(r"\b(?:is|are|was|were|been)\s+(?:\w+\s+)?$", lead[-30:], re.I):
                role = None  # "the conduct charged in Count One": not a report that someone was charged
            elif re.search(r"\bcomplaint\b", follow, re.I):
                role = "complaint"
            elif re.search(r"\binformation\b", follow, re.I):
                role = "information"
            elif re.search(r"\bindictment\b", follow, re.I):
                role = "indictment"
        elif kind == "plead" and re.match(r"\s+(?:agreement|hearing|negotiations|offer)\b", text[end:end + 20], re.I):
            role = None
        out.append(assertion("event", kind, role, METHOD, VERSION, 0.75 if role else 0.5, start, end))

    if doc.kind != "reference":
        for start, end, value, _ in fields.iter_conduct(text):
            # What the verb acts on, read from the rest of its clause.
            cs, ce = sp.clause_at(text, start, end)
            ss, se = sp.sentence_at(text, start, end)
            cs, ss, ce = max(cs, start - 300), max(ss, start - 300), min(ce, end + 200)
            if acts.RECITAL.search(text[ss:start]) or acts.RECITAL.search(text[end:ce]) or acts.in_verb_list(text[ss:ce], start - ss, end - ss):
                role: str | None = "not_conduct"
            elif acts.GENERAL.match(text[start:end]) or acts.SELLS.match(text[start:end]):
                # These verbs name an act only through their object; this reader reads the same object.
                role = acts.by_verb(text[start:end], text[end:ce], text[max(0, start - 20): start])
            elif acts.AMBIGUOUS.match(text[start:end]):
                role = acts.by_object(text[start:ce])
            else:
                role = None
            role = acts.settle(role, text[max(cs, start - 160): start], text[end:ce])
            out.append(assertion("conduct", value, role, METHOD, VERSION, 0.7 if role else 0.5, start, end))

    parties: list[list[Any]] = []
    for start, end, _hint in names.iter_people(text):
        before = text[max(0, start - 70): start]
        after = text[end: end + 110]
        if _OFFICIAL_BEFORE.search(before) or _OFFICIAL_AFTER.match(after):
            role = "official"
        elif _VICTIM_BEFORE.search(before):
            role = "victim"
        elif _DEFENDANT_BEFORE.search(before) or _DEFENDANT_AFTER.match(after):
            role = "defendant"
        else:
            role = None
        parties.append([start, end, role])
    # A list of names shares the role its last name is given: "A, B and C were each sentenced".
    for index in range(len(parties) - 2, -1, -1):
        here, following = parties[index], parties[index + 1]
        if here[2] is None and following[2] == "defendant" and names.LIST_GAP.match(text[here[1]: following[0]]):
            here[2] = "defendant"
    for start, end, role in parties:
        out.append(assertion("party", None, role, METHOD, VERSION, 0.75 if role else 0.5, start, end))
    return out


register_reader("clause", ("press", "court", "reference"), read, version=VERSION, order=20)
