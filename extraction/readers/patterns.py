"""Surface patterns: fixed phrasings anchored on the value.

For a mention field this reader finds each typed token and assigns a role only
when a known phrasing touches the token ("sentenced to", "in restitution").
For a tag field it matches the profile's cue for each label.
"""

from __future__ import annotations

import re
from typing import Any

from extraction import acts, fields, names, profiles, spans as sp, statutes
from extraction.readers import Doc, assertion, register_reader

VERSION = "patterns_1.2"
METHOD = "regex"

_A = r"(?:(?:more\s+than|over|nearly|approximately|about|almost|at\s+least|roughly|in\s+excess\s+of|some|a\s+total\s+of|totall?ing)\s+)?"

# (role, confidence, left context ending at the token, right context starting after it)
_MONEY: tuple[tuple[str, float, str | None, str | None], ...] = (
    ("exposure_fine", 0.85, rf"(?:fine\s+of\s+up\s+to|maximum\s+(?:\w+\s+){{0,2}}fine\s+of|fine\s+of\s+not\s+more\s+than)\s+{_A}$", None),
    ("exposure_fine", 0.85, r"(?:up\s+to|maximum\s+of)\s+(?:an?\s+)?$", r"^\s+(?:fine|in\s+fines)\b"),
    ("special_assessment", 0.85, None, r"^\s+(?:mandatory\s+)?special\s+assessment"),
    ("special_assessment", 0.85, r"special\s+assessment\s+of\s+$", None),
    ("bail", 0.85, None, r"^\s+(?:\w+\s+){0,2}(?:bond|bail)\b"),
    ("bail", 0.85, r"(?:bond|bail)\s+(?:of|at|was\s+set\s+at|in\s+the\s+amount\s+of)\s+$", None),
    ("restitution", 0.85, None, r"^\s+in\s+(?:\w+\s+){0,2}restitution\b"),
    ("restitution", 0.85, None, r"^\s+(?:as\s+)?restitution\b"),
    ("restitution", 0.85, rf"restitution\s+(?:(?:order|payment)\s+)?(?:of|in\s+the\s+amount\s+of|totall?ing|amounting\s+to)\s+{_A}$", None),
    ("forfeiture", 0.85, rf"forfeit(?:ure|ed|ing)?\s+(?:of\s+|(?:money\s+)?judgment\s+(?:of|in\s+the\s+amount\s+of)\s+)?{_A}$", None),
    ("forfeiture", 0.85, None, r"^\s+(?:(?:forfeiture|money)\s+judgment|in\s+forfeiture)\b"),
    ("fine", 0.85, rf"\bfine[ds]?\s+(?:of\s+|him\s+|her\s+|them\s+)?{_A}$", None),
    ("fine", 0.85, None, r"^\s+(?:criminal\s+)?fine\b"),
    ("civil_penalty", 0.8, rf"(?:agreed\s+to\s+pay|will\s+pay|pay)\s+{_A}$", r"^\s+(?:to\s+(?:resolve|settle)|in\s+civil\s+penalt|civil\s+penalt)"),
    ("intended_loss", 0.8, rf"intended\s+loss(?:es)?\s+(?:of\s+|was\s+|were\s+)?{_A}$", None),
    ("intended_loss", 0.8, rf"attempt\w*\s+to\s+(?:steal|obtain|collect|defraud\w*\s+[^.$]{{0,60}}?(?:of|out\s+of))\s+{_A}$", None),
    ("loss", 0.8, rf"loss(?:es)?\s+(?:of|totall?ing|exceeding|amounting\s+to|was|were|is|in\s+excess\s+of)\s+{_A}$", None),
    ("loss", 0.8, None, r"^\s+in\s+(?:actual\s+|total\s+|financial\s+|victim\s+)?loss(?:es)?\b"),
    ("loss", 0.8, rf"(?:defraud\w*|swindl\w*|bilk\w*|scamm\w*|cheat\w*)\s+[^.$]{{0,90}}?\s(?:of|out\s+of)\s+{_A}$", None),
    ("loss", 0.8, rf"(?:stole|stolen|steal(?:ing)?|embezzl\w*|misappropriat\w*|divert\w*)\s+{_A}$", None),
    ("loss", 0.8, rf"(?:victims?|investors?|customers?|clients?)\s+(?:\w+\s+){{0,3}}lost\s+{_A}$", None),
    # Who was out the money: "Medicare paid $7.9 million on the false claims", "17 victims paid a total of $2 million"
    ("loss", 0.8, rf"(?:Medicare|Medicaid|TRICARE|lenders?|banks?|insurers?|compan(?:y|ies)|victims?|investors?|agenc(?:y|ies)|program|government|practice)\s+"
                  rf"(?:\w+\s+){{0,2}}(?:paid(?:\s+out)?|lost|sent|wired|transferred)\s+(?:the\s+\w+\s+)?{_A}$", None),
    ("loss", 0.75, None, r"^\s+(?:(?:wire|bank|mail|health\s*care|investment|securities)\s+)?(?:fraud|Ponzi|scam|embezzlement)\b"),
    ("proceeds", 0.75, rf"(?:obtained|received|netted|collected|laundered|pocketed|profited|gained)\s+{_A}$", None),
    ("proceeds", 0.75, None, r"^\s+in\s+(?:fraud\w*\s+|criminal\s+|illicit\s+|illegal\s+|ill-gotten\s+)?(?:proceeds|gains)\b"),
)
_MONEY = tuple((role, conf, re.compile(left, re.I) if left else None, re.compile(right, re.I) if right else None) for role, conf, left, right in _MONEY)

_TERM = r"(?:a\s+)?(?:total\s+(?:of\s+)?)?(?:(?:prison\s+)?(?:term|sentence)\s+of\s+)?(?:imprisonment\s+(?:of|for)\s+)?"
_SENTENCE: tuple[tuple[str, float, re.Pattern[str] | None, re.Pattern[str] | None], ...] = tuple(
    (role, conf, re.compile(left, re.I) if left else None, re.compile(right, re.I) if right else None)
    for role, conf, left, right in (
        ("exposure", 0.85, rf"(?:faces?|facing|up\s+to|not\s+more\s+than|maximum\s+(?:penalty|sentence|term)?(?:\s+of)?|punishable\s+by(?:\s+up\s+to)?|mandatory\s+minimum(?:\s+(?:sentence|term|penalty))?(?:\s+of)?|minimum\s+of)\s+{_TERM}{_A}$", None),
        ("supervised_release", 0.85, None, r"^\s*(?:of\s+|on\s+|years?\s+of\s+|term\s+of\s+)?supervised\s+release\b"),
        ("supervised_release", 0.85, r"supervised\s+release\s+(?:for|of)\s+(?:a\s+(?:term|period)\s+of\s*:?\s+)?$", None),
        ("probation", 0.85, None, r"^\s*(?:of\s+|on\s+|'?\s*)?probation\b"),
        ("probation", 0.85, r"probation\s+(?:for|of)\s+(?:a\s+(?:term|period)\s+of\s*:?\s+)?$", None),
        ("imposed", 0.85, r"imprisoned\s+for\s+a\s+(?:total\s+)?term\s+of\s*:?\s*$", None),
        ("imposed", 0.85, rf"sentenced\s+(?:[^.;]{{0,90}}?\s)?to\s+(?:serve\s+)?{_TERM}{_A}$", None),
        ("imposed", 0.8, None, r"^\s+(?:in|of)\s+(?:federal\s+|state\s+)?(?:prison|imprisonment|incarceration|custody|jail)\b"),
    )
)

_DATE: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (role, re.compile(left, re.I))
    for role, left in (
        ("filed", r"(?:\bfiled|date\s+filed|entered)\s*:?\s*(?:on\s+)?$"),
        ("scheduled", r"(?:(?:scheduled|set|slated)\s+(?:(?:sentencing|trial|a\s+hearing)\s+)?for\s+|(?:scheduled|set|slated|expected)\s+to\s+(?:be\s+)?(?:\w+\s+){0,3}on\s+|will\s+be\s+sentenced\s+(?:on\s+)?)$"),
        ("sentencing", r"(?:sentenced\s+(?:on\s+)?|date\s+of\s+imposition\s+of\s+judgment\s*:?\s*)$"),
        ("arrest", r"arrested\s+(?:on\s+)?$"),
        ("indictment", r"(?:indicted|indictment\s+(?:was\s+)?(?:returned|unsealed))\s+(?:on\s+)?$"),
        ("plea", r"(?:pleaded|pled)\s+guilty\s+(?:on\s+)?$"),
        ("verdict", r"(?:convicted|found\s+guilty)\s+(?:on\s+)?$"),
        ("offense", r"(?:\bfrom|between|beginning|since|starting|through|until)\s+(?:in\s+or\s+(?:about|around)\s+|on\s+or\s+about\s+|at\s+least\s+|approximately\s+|about\s+)?$|\b(?:on|in)\s+or\s+(?:about|around)\s+$"),
    )
)

# Event triggers. Each rule: (trigger kind, role, left context ending at the
# trigger, right context starting after it). First match wins; a trigger no
# rule reads gets no role.
_SOON = r"(?:scheduled|expected|set|slated|due)\s+to\s+(?:be\s+)?$|\bwill\s+(?:be\s+)?$|\bis\s+to\s+be\s+$|\bagree(?:s|d|ing)?\s+to\s+$|\bintends?\s+to\s+$|\bawaiting\s+$"
_HYPOTHETICAL = r"\bif\s+$|\bcould\s+be\s+$|\bmay\s+be\s+$|\buntil\s+(?:proven\s+)?$|\bunless\s+(?:and\s+until\s+)?(?:proven\s+)?$|☐\s*(?:was\s+)?$"
_EVENT: tuple[tuple[str, str, re.Pattern[str] | None, re.Pattern[str] | None], ...] = tuple(
    (kind, role, re.compile(left, re.I) if left else None, re.compile(right, re.I) if right else None)
    for kind, role, left, right in (
        ("*", "scheduled", _SOON, None),
        ("*", "not_event", _HYPOTHETICAL, None),
        ("convict", "not_event", r"\b(?:previously|prior|earlier)\s+(?:been\s+)?$", None),
        ("sentence", "sentencing", None, None),
        ("plead", "plea", r"(?:^|[^-\w])$", r"^(?!\s+(?:agreement|hearing|negotiations|offer))"),
        ("convict", "verdict", r"\bjury\s+(?:\w+\s+){0,2}$", None),
        ("convict", "verdict", None, r"^[^.;]{0,140}\b(?:jury|trial)\b"),
        ("convict", "verdict", r"\b(?:jury|trial)\b[^.;]{0,140}$", None),
        ("convict", "conviction", None, None),
        ("indict", "indictment", None, None),
        ("charge", "complaint", None, r"^(?:\s+\w+){0,4}\s+(?:in|by)\s+an?\s+(?:[\w-]+\s+){0,2}(?:criminal\s+)?complaint\b"),
        ("charge", "information", None, r"^(?:\s+\w+){0,4}\s+(?:in|by)\s+an?\s+(?:[\w-]+\s+){0,2}(?:criminal\s+)?information\b"),
        ("charge", "indictment", None, r"^(?:\s+\w+){0,4}\s+(?:in|by)\s+an?\s+(?:[\w-]+\s+){0,2}(?:superseding\s+)?indictment\b"),
        ("charge", "charge", r"\b(?:is|are|was|were|been)\s+(?:also\s+|each\s+|both\s+)?$", r"^(?:\s+(?:today|yesterday))?\s+(?:with|in|by|on)\b"),
        ("arrest", "arrest", None, None),
    )
)

_VICTIM_NOUN = re.compile(r"victims?|investors?|customers?|clients?|consumers?|seniors?|patients?|account\s+holders?", re.I)
_VICTIM_CUE = re.compile(r"victim\w*|defraud\w*|target\w*|traffick\w*|exploit\w*|harm\w*|scamm\w*|stole\s+from|lost\b|identit(?:y|ies)\s+of", re.I)

_STAGE = {
    "sentenced": r"(?:was|were|has\s+been|been|today)\s+sentenced|sentenced\s+(?:today|to|in\s+federal\s+court)",
    "plea": r"(?:pleaded|pled|pleads)\s+guilty|guilty\s+pleas?|entered\s+a\s+(?:guilty\s+)?plea",
    "convicted": r"(?:was|were|been)\s+convicted|found\s+guilty|jury\s+(?:\w+\s+){0,3}(?:convicted|returned\s+(?:a\s+)?guilty\s+verdicts?)|convicted\s+(?:today|by\s+a)",
    "charged": r"(?:was|were|been)\s+(?:indicted|charged)|indictment\s+(?:was\s+)?(?:unsealed|returned|charg\w+|alleg\w+)|charged\s+(?:today|with|in\s+(?:a|an))|criminal\s+complaint|grand\s+jury\s+(?:\w+\s+){0,4}(?:returned|indicted|charged)",
    "arrested": r"(?:was|were|been)\s+arrested|arrested\s+(?:today|on|in)|taken\s+into\s+custody",
}
_STAGE = {label: re.compile(rf"\b(?:{cue})\b", re.I) for label, cue in _STAGE.items()}

_DOCUMENT = {
    "judgment": r"JUDGMENT\s+IN\s+A\s+CRIMINAL\s+CASE|AMENDED\s+JUDGMENT",
    "plea_agreement": r"PLEA\s+AGREEMENT",
    "indictment": r"(?:(?:SECOND|THIRD|FOURTH|FIFTH)\s+)?(?:SUPERSEDING\s+)?INDICTMENT",
    "information": r"(?:SUPERSEDING\s+)?(?:CRIMINAL\s+)?INFORMATION",
    "complaint": r"CRIMINAL\s+COMPLAINT|AFFIDAVIT\s+IN\s+SUPPORT\s+OF\s+(?:AN?\s+)?(?:CRIMINAL\s+)?COMPLAINT",
    "sentencing_memorandum": r"SENTENCING\s+MEMORANDUM|MEMORANDUM\s+IN\s+AID\s+OF\s+SENTENCING",
    "factual_basis": r"FACTUAL\s+BASIS|STATEMENT\s+OF\s+(?:FACTS|THE\s+OFFENSE|OFFENSE)|FACTUAL\s+RESUME|FACTUAL\s+PROFFER|STIPULAT(?:ION\s+OF|ED)\s+FACTS",
    "verdict": r"VERDICT(?:\s+FORM)?",
    "transcript": r"TRANSCRIPT\s+OF|REPORTER'S\s+TRANSCRIPT",
    "docket": r"CRIMINAL\s+DOCKET\s+FOR\s+CASE",
    "motion": r"MOTION\s+(?:TO|FOR|IN\s+LIMINE)",
}
# Case-sensitive on purpose: a filing's title is in capitals, its body is not.
_DOCUMENT = {label: re.compile(rf"\b(?:{cue})\b") for label, cue in _DOCUMENT.items()}
_HEADER_CHARS = 4000


def _role(rules, text: str, start: int, end: int) -> tuple[str | None, float]:
    before = sp.normalize_surface(text[max(0, start - 160): start])
    after = sp.normalize_surface(text[end: end + 80])
    for role, confidence, left, right in rules:
        if left is not None and not left.search(before):
            continue
        if right is not None and not right.search(after):
            continue
        return role, confidence
    return None, 0.5


def _hypothetical(text: str, start: int, end: int) -> bool:
    """True when the clause before the token speaks of what could be imposed,
    and nothing in it says a sentence was."""
    cs, _ = sp.clause_at(text, start, end)
    before = sp.normalize_surface(text[cs:start])
    if sp.in_penalty_list(text, start):
        return True
    return bool(sp._EXPOSURE_CUES.search(before)) and not re.search(r"\bsentenced\b|\bordered\b", before, re.I)


def _tags(doc: Doc, field_name: str, vocabulary: dict[str, re.Pattern[str]], *, limit: int | None = None,
          confidence: float = 0.8, check_boilerplate: bool = True) -> list[dict[str, Any]]:
    text = doc.text if limit is None else doc.text[:limit]
    out: list[dict[str, Any]] = []
    for label, cue in vocabulary.items():
        real: list[re.Match[str]] = []
        boiler: list[re.Match[str]] = []
        for match in cue.finditer(text):
            if check_boilerplate:
                s, e = sp.sentence_at(doc.text, match.start(), match.end())
                # Bounded: a page with no sentence breaks is one "sentence" of any length.
                s, e = max(s, match.start() - 600), min(e, match.end() + 600)
                if profiles.BOILERPLATE.search(doc.text[s:e]):
                    boiler.append(match)
                    continue
            real.append(match)
        # A family that says both "present" and "boilerplate" for one label
        # abstains. Say "boilerplate" only when no real cue exists.
        role, hits = ("present", real) if real else ("boilerplate", boiler)
        for match in hits[:3]:
            out.append(assertion(
                field_name, label, role, METHOD, VERSION, confidence, match.start(), match.end(),
                cue_pattern=cue.pattern, mentions=len(hits),
            ))
    return out


def read(doc: Doc) -> list[dict[str, Any]]:
    text = doc.text
    out: list[dict[str, Any]] = []

    for start, end, value, extras in fields.iter_duration(text):
        role, confidence = _role(_SENTENCE, text, start, end)
        if role in ("imposed", "supervised_release", "probation") and _hypothetical(text, start, end):
            role = "exposure"  # "faces up to 20 years in prison and three years of supervised release"
        if role == "exposure":
            before = sp.normalize_surface(text[max(0, start - 60): start]).lower()
            extras = {**extras, "bound": "minimum" if "minimum" in before else "maximum"}
        out.append(assertion("sentence", value, role, METHOD, VERSION, confidence, start, end, **extras))

    for start, end, value, extras in fields.iter_money(text):
        role, confidence = _role(_MONEY, text, start, end)
        if role == "fine" and _hypothetical(text, start, end):
            role = "exposure_fine"
        row = sp.totals_row(text, start)
        if row:
            # A cell of the judgment form's penalties table. Its column says what it is,
            # and only when the row has one amount per column: a blank cell shifts the rest.
            cells = [s + row[0] for s, _, _, _ in fields.iter_money(text[row[0]: row[1]])]
            columns = sp.totals_columns(text, row[0])
            role, confidence = (columns[cells.index(start)], 0.85) if len(cells) == len(columns) and start in cells else (None, 0.5)
            if role is None:
                confidence = 0.5
        if extras.get("unit_price") or value == 0:
            role, confidence = "not_case_amount", 0.8
        out.append(assertion("money", value, role, METHOD, VERSION, confidence, start, end, **extras))

    for start, end, value, extras in fields.iter_statute(text):
        out.append(assertion("statute", value, "cited", METHOD, VERSION, 0.9, start, end, **extras))

    for start, end, value, extras in fields.iter_case_number(text):
        out.append(assertion("case_number", value, "cited", METHOD, VERSION, 0.9, start, end, **extras))

    for start, end, value, extras in fields.iter_date(text):
        before = sp.normalize_surface(text[max(0, start - 70): start])
        role = next((name for name, left in _DATE if left.search(before)), None)
        after = text[end: end + 60]
        if role is None and re.match(r"[ \t]*\n[ \t]*Date\s+of\s+Imposition\s+of\s+Judgment", after, re.I):
            role = "sentencing"  # the judgment form prints the date above its label
        elif role is None and re.match(r"[ \t]+\d{1,2}[a-z]{0,2}[ \t]*(?:\n|$)", after) and re.search(r"Offense\s+Ended", text[max(0, start - 600): start]):
            role = "offense"  # the form's "Offense Ended" column, followed by the count number
        out.append(assertion("date", value, role, METHOD, VERSION, 0.8 if role else 0.5, start, end))

    for start, end, value, extras in fields.iter_count(text):
        cs, ce = sp.clause_at(text, start, end)
        named = bool(_VICTIM_NOUN.fullmatch(extras["noun"].split()[-1])) or "account holder" in extras["noun"]
        role = "victims" if named and _VICTIM_CUE.search(text[cs:ce]) else None
        out.append(assertion("victim_count", value, role, METHOD, VERSION, 0.75 if role else 0.5, start, end, **extras))

    for start, end, kind, extras in fields.iter_event(text):
        before = sp.normalize_surface(text[max(0, start - 60): start])
        after = sp.normalize_surface(text[end: end + 170])
        role = None
        for trigger, candidate, left, right in _EVENT:
            if trigger not in ("*", kind):
                continue
            if left is not None and not left.search(before):
                continue
            if right is not None and not right.search(after):
                continue
            role = candidate
            break
        again = "resentenced" in text[start:end].lower().replace("-", "") or None
        out.append(assertion("event", kind, role, METHOD, VERSION, 0.8 if role else 0.5, start, end, resentencing=again))

    if doc.kind != "reference":
        for start, end, value, _ in fields.iter_conduct(text):
            ss, se = sp.sentence_at(text, start, end)
            after = text[end: min(se, end + 160)]
            role = "not_conduct" if acts.RECITAL.search(text[max(ss, start - 300): start]) else acts.by_verb(text[start:end], after)
            out.append(assertion("conduct", value, role, METHOD, VERSION, 0.8 if role else 0.5, start, end))

    for start, end, hint in names.iter_people(text):
        if hint == "person":
            # "Name, 45, of City" introduces the accused and also anyone else.
            # The phrasing says a person is named; it does not say who they are.
            out.append(assertion("party", None, None, METHOD, VERSION, 0.5, start, end))
        else:
            out.append(assertion("party", None, hint, METHOD, VERSION, 0.85, start, end))

    out += _tags(doc, "stage", _STAGE)
    for label, cue in statutes.OFFENSE_WORDS.items():
        out += _tags(doc, "offense", {label: cue})
    for field_name in ("scheme", "channel", "platform"):
        out += _tags(doc, field_name, profiles.vocabulary(doc.domain, field_name))

    if doc.kind == "court":
        # The first title in the header is the filing's own. Later ones are
        # filings it refers to, so they are asserted weakly.
        found = _tags(doc, "document_type", _DOCUMENT, limit=_HEADER_CHARS, check_boilerplate=False)
        if found:
            first = min(found, key=lambda a: a["span_start"])["value"]
            for item in found:
                if item["value"] != first:
                    item["confidence"] = 0.5
                    item["extras"]["weak"] = "later_title_in_header"
        out += found
    return out


register_reader("patterns", ("press", "court", "reference"), read, version=VERSION, order=10)
