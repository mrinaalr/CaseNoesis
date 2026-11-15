"""Documents written from an invented case, with the facts each one states.

Six document shapes, modeled on the structure of the real records the engine
reads and written from scratch:

    press_charged       a U.S. Attorney's Office release announcing charges
    press_disposed      a release announcing a guilty plea or a jury verdict
    press_sentenced     a release announcing a sentence
    indictment          a charging document (indictment or information)
    plea_agreement      a plea agreement
    judgment            a judgment in a criminal case (form AO 245B)

A `Rec` collects the text and, beside it, the truth: every amount, term,
date, citation and count the text states, with the role it plays and whose it
is. A typed token the truth does not claim is a distractor, something a
reader should see and leave alone: a statutory maximum, a unit price, the
length of a trial.
"""

from __future__ import annotations

import hashlib
import random
from datetime import date, timedelta
from typing import Any

from gold.world import MAXIMUM_YEARS, OFFENSES, Case, Outcome, Person

TAG_FIELDS = ("stage", "document_type", "offense", "scheme", "channel", "platform")
NOTICE = "Invented test record. The people, the case and the events in it do not exist. Not a public record."
_WORDS = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen "
    "eighteen nineteen twenty"
).split()
_TENS = {20: "twenty", 30: "thirty", 40: "forty", 50: "fifty", 60: "sixty", 70: "seventy", 80: "eighty", 90: "ninety"}
_MONTH = "January February March April May June July August September October November December".split()
_AP = "Jan. Feb. March April May June July Aug. Sept. Oct. Nov. Dec.".split()
_ORDINAL = "ONE TWO THREE FOUR FIVE".split()


_SCHEME_OF_OFFENSE = {
    "bank_fraud": "bank_fraud", "health_care_fraud": "health_care_fraud", "securities_fraud": "securities",
    "tax_evasion": "tax", "false_return": "tax", "sex_trafficking": "sex_trafficking", "forced_labor": "forced_labor",
    "enticement": "enticement", "csam_distribution": "distribution", "agg_id_theft": "identity_theft",
    "money_laundering": "money_laundering",
}


def words(number: int) -> str:
    if number <= 20:
        return _WORDS[number]
    if number < 100:
        tens, unit = number // 10 * 10, number % 10
        return _TENS[tens] + (f"-{_WORDS[unit]}" if unit else "")
    return str(number)


def statute(title: str, section: str) -> str:
    return f"{int(title)} U.S.C. § {section.upper()}"


class Rec:
    """One document being written, and what it states."""

    def __init__(self, case: Case, kind: str, shape: str, rng: random.Random, dated: date) -> None:
        self.case, self.kind, self.shape, self.rng, self.dated = case, kind, shape, rng, dated
        self.paragraphs: list[str] = []
        self.values: list[dict[str, Any]] = []
        self.optional: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.tags: dict[str, set[str]] = {name: set() for name in TAG_FIELDS}
        self.unscored: set[str] = set()
        self.names: dict[str, set[str]] = {}
        self.entry: dict[str, Any] = {}

    # -- text -----------------------------------------------------------------
    def add(self, *paragraphs: str) -> None:
        self.paragraphs.extend(p for p in paragraphs if p)

    @property
    def text(self) -> str:
        return "\n\n".join(self.paragraphs) if self.kind == "press" else "\n".join(self.paragraphs)

    # -- truth ----------------------------------------------------------------
    def _note(self, field: str, value: Any, role: str | list[str] | None, persons: list[str] | None, optional: bool) -> None:
        if role is None:
            return  # a distractor: stated in the text, not a value of the case
        item = {"field": field, "value": value, "roles": [role] if isinstance(role, str) else list(role)}
        if persons is not None:
            item["persons"] = sorted(persons)
        (self.optional if optional else self.values).append(item)

    def event(self, kind: str, when: date | str | None, persons: list[str]) -> None:
        stamp = when.isoformat() if isinstance(when, date) else when
        item = {"type": kind, "date": stamp, "persons": sorted(persons)}
        if item not in self.events:
            self.events.append(item)

    def tag(self, field: str, *labels: str) -> None:
        self.tags[field].update(labels)

    # -- typed tokens ------------------------------------------------------------
    def money(self, amount: float, role: str | list[str] | None, persons: list[str] | None = None, *,
              approx: bool = False, optional: bool = False, exact: bool = False) -> str:
        self._note("money", round(float(amount), 2), role, persons, optional)
        if self.kind == "court" or exact:
            body = f"${amount:,.2f}"
        elif amount >= 1_000_000 and amount % 100_000 == 0 and self.rng.random() < 0.75:
            body = f"${amount / 1_000_000:g} million"
        elif float(amount).is_integer():
            body = f"${amount:,.0f}"
        else:
            body = f"${amount:,.2f}"
        prefix = self.rng.choice(("more than ", "approximately ", "nearly ", "over ")) if approx else ""
        return prefix + body

    def term(self, months: int, role: str | list[str] | None, persons: list[str] | None = None, *,
             adjective: bool = False, optional: bool = False) -> str:
        self._note("sentence", float(months), role, persons, optional)
        if months % 12 == 0 and self.rng.random() < 0.55:
            years = months // 12
            number = words(years) if self.rng.random() < 0.6 else str(years)
            return f"{number}-year" if adjective else f"{number} year{'s' if years != 1 else ''}"
        return f"{months}-month" if adjective else f"{months} months"

    def life(self, role: str | None) -> str:
        self._note("sentence", "life", role, None, False)
        return "life in prison"

    def day(self, when: date, role: str | list[str] | None, style: str = "ap", *, optional: bool = False) -> str:
        self._note("date", when.isoformat(), role, None, optional)
        if style == "slash2":
            return f"{when.month:02d}/{when.day:02d}/{when.year % 100:02d}"
        if style == "slash4":
            return f"{when.month:02d}/{when.day:02d}/{when.year}"
        month = _AP[when.month - 1] if style == "ap" else _MONTH[when.month - 1]
        return f"{month} {when.day}, {when.year}"

    def month(self, when: date, role: str | None) -> str:
        self._note("date", f"{when.year:04d}-{when.month:02d}", role, None, False)
        return f"{_MONTH[when.month - 1]} {when.year}"

    def cite(self, offense: str, form: str = "usc") -> str:
        title, section, _, label = OFFENSES[offense]
        self._note("statute", statute(title, section), "cited", None, False)
        self.tag("offense", label)
        self._named(offense)
        if form == "title":
            return f"Title {title}, United States Code, Section {section}"
        if form == "short":
            return f"{title}:{section}"
        return f"{title} U.S.C. § {section}"

    def offense(self, offense: str) -> str:
        self.tag("offense", OFFENSES[offense][3])
        self._named(offense)
        return OFFENSES[offense][2]

    def _named(self, offense: str) -> None:
        """Naming an offense is not describing a scheme. Several scheme labels are
        also the names of offenses, so a record that names the offense neither
        earns nor owes that scheme label."""
        label = _SCHEME_OF_OFFENSE.get(offense)
        if label:
            self.unscored.add(f"scheme:{label}")

    def docket(self, form: str = "plain") -> str:
        office, rest = self.case.docket.split(":")
        year, kind, sequence = rest.split("-")
        self._note("case_number", f"{int(office)}:{year}-{kind}-{int(sequence):05d}", "cited", None, False)
        if form == "court":
            return f"{office}:{year}-{kind}-{sequence}-{self.case.judge.given[0]}{self.case.judge.surname[0]}{self.case.judge.surname[1].upper()}"
        if form == "caps":
            return self.case.docket.upper()
        return self.case.docket

    def count(self, number: int, noun: str, role: str | None = "victims") -> str:
        self._note("victim_count", number, role, None, False)
        spelled = words(number) if number < 10 and self.rng.random() < 0.6 else f"{number:,}"
        return f"{spelled} {noun}"

    # -- people -------------------------------------------------------------------
    def person(self, person: Person, surface: str) -> str:
        self.names.setdefault(person.key, set()).add(surface)
        return surface

    def intro(self, person: Person) -> str:
        style = self.rng.random()
        if style < 0.75:
            return f"{self.person(person, person.full)}, {person.age}, of {person.city}, {person.state},"
        if style < 0.9:
            return f"{self.person(person, person.full)}, {person.age}, of {person.city},"
        return f"{self.person(person, person.full)}, of {person.city}, {person.state},"

    def last(self, person: Person) -> str:
        return self.person(person, person.surname)


def pick(rng: random.Random, *options: Any) -> str:
    """One of several phrasings. Each option is a function, so only the one
    chosen writes text and notes truth."""
    return rng.choice(options)()


def _join(items: list[str]) -> str:
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _official(case: Case, rng: random.Random, title: str) -> str:
    """A name for someone who is not in the case's cast of defendants."""
    from gold.world import GIVEN, MIDDLE, SURNAMES

    taken = {p.surname for p in (*case.defendants, case.judge, case.prosecutor, case.agent)} | set(case.notes.get("extra", ()))
    surname = next(s for s in rng.sample(SURNAMES, len(SURNAMES)) if s not in taken)
    case.notes.setdefault("extra", []).append(surname)
    return f"{title} {rng.choice(GIVEN)} {rng.choice(MIDDLE)}. {surname}"


def _story(rec: Rec, people: list[Person]) -> str:
    """The narrative paragraph, with its amounts, counts and dates noted."""
    case, rng, story = rec.case, rec.rng, rec.case.narrative
    start, end = case.offense_start, case.offense_end
    form = rng.random()
    if form < 0.5:
        period = f"from {rec.month(start, 'offense')} through {rec.month(end, 'offense')}"
        rec.event("offense", f"{start.year:04d}-{start.month:02d}", [p.key for p in people])
    elif form < 0.75:
        period = f"between {start.year} and {end.year if end.year != start.year else start.year + 1}"
    else:
        period = f"beginning in {rec.month(start, 'offense')}"
        rec.event("offense", f"{start.year:04d}-{start.month:02d}", [p.key for p in people])
    names = _join([rec.last(p) for p in people])
    generic = "the defendants" if len(people) > 1 else "the defendant"
    text = story.text
    text = text.replace("{period}, {D}", f"{period[0].upper()}{period[1:]}, {names}", 1)
    text = text.replace("{period} {D}", f"{period}, {names}", 1)
    out, rest = "", text
    while "{D}" in rest:
        before, rest = rest.split("{D}", 1)
        out += before
        phrase = names if rng.random() < 0.55 else generic
        starts_sentence = not out.rstrip() or out.rstrip()[-1] in ".!?"
        if phrase == generic and starts_sentence:
            phrase = phrase.capitalize()
        out += phrase
    text = out + rest
    if "{loss}" in text:
        text = text.replace("{loss}", rec.money(case.loss, ["loss", "proceeds"] if story.key.startswith(("ppp", "health", "embezzle_a")) else "loss", approx=rng.random() < 0.4))
    if "{victims}" in text:
        text = text.replace("{victims}", rec.count(case.victims, story.counted).rsplit(" ", 1)[0])
    rec.tag("scheme", *story.scheme)
    rec.tag("channel", *story.channel)
    rec.tag("platform", *story.platform)
    for offense in story.offenses:
        if OFFENSES[offense][2] in text.lower():
            rec.tag("offense", OFFENSES[offense][3])
            rec._named(offense)
    rec.unscored.update(story.arguable)
    if story.arrested:
        rec.tag("stage", "arrested")
        rec.event("arrest", None, [p.key for p in people])
    return text


def _credits(rec: Rec) -> list[str]:
    case, rng = rec.case, rec.rng
    agencies = _join(list(case.agencies))
    lines = [
        pick(
            rng,
            lambda: f"{agencies[0].upper()}{agencies[1:]} investigated the case.",
            lambda: f"The case was investigated by {agencies}.",
            lambda: f"{_official(case, rng, 'Special Agent in Charge')} of {case.agencies[0].removeprefix('the ')} joined in the announcement.",
        ),
        rng.choice((
            f"Assistant U.S. Attorney {case.prosecutor.full} is prosecuting the case.",
            f"The case is being prosecuted by Assistant U.S. Attorney {case.prosecutor.full}.",
            f"Assistant U.S. Attorney {case.prosecutor.full} of the Economic Crimes Unit prosecuted the case.",
        )),
    ]
    return [" ".join(lines)]


def _exposure(rec: Rec, offenses: tuple[str, ...]) -> str:
    """The statutory maximum paragraph: every figure in it is exposure."""
    rng = rec.rng
    parts = []
    for offense in offenses:
        name = OFFENSES[offense][2]
        if offense == "agg_id_theft":
            parts.append(f"The charge of {name} carries a mandatory {rec.term(24, 'exposure', adjective=True)} prison term, to run after any other sentence.")
        elif offense in ("sex_trafficking", "enticement"):
            parts.append(f"The charge of {name} carries a mandatory minimum of {rec.term(120, 'exposure')} and a maximum of {rec.life('exposure')}.")
        else:
            years = MAXIMUM_YEARS[offense]
            parts.append(pick(
                rng,
                lambda: f"The charge of {name} carries a maximum penalty of {rec.term(years * 12, 'exposure')} in prison and a fine of up to {rec.money(250_000, 'exposure_fine')}.",
                lambda: f"If convicted of {name}, each defendant faces up to {rec.term(years * 12, 'exposure')} in prison.",
                lambda: f"{name.capitalize()} is punishable by up to {rec.term(years * 12, 'exposure')} in prison, {rec.term(36, 'exposure')} of supervised release and a fine of {rec.money(250_000, 'exposure_fine')}.",
            ))
        rec.tag("offense", OFFENSES[offense][3])
    parts.append("A federal district court judge will determine any sentence after considering the U.S. Sentencing Guidelines and other statutory factors.")
    return " ".join(parts)


def _press_entry(rec: Rec, slug: str, title: str, stage: str) -> None:
    case = rec.case
    url = f"https://gold.example/{case.district[0].lower().replace(' ', '').replace(',', '-')}/pr/{slug}-{case.case_id}"
    rec.entry = {
        "kind": "press", "domain": case.domain, "source_url": url, "agency": case.district[0],
        "pub_date": rec.dated.isoformat(), "stage": stage, "bucket": "classic", "title": title, "notice": NOTICE,
    }


def _when(rec: Rec, happened: date, role: str) -> tuple[str, str]:
    """How a release dated `rec.dated` says when something happened: the phrase,
    and the date a reader can recover from it."""
    gap = (rec.dated - happened).days
    if gap == 0:
        return "today", happened.isoformat()
    if gap == 1:
        return "yesterday", happened.isoformat()
    return f"on {rec.day(happened, role)}", happened.isoformat()


def _earlier(rec: Rec, happened: date, role: str) -> tuple[str, str]:
    """An earlier step, mentioned in passing: a month, or a full date."""
    if rec.rng.random() < 0.55:
        return f"in {rec.month(happened, role)}", f"{happened.year:04d}-{happened.month:02d}"
    return f"on {rec.day(happened, role)}", happened.isoformat()


def _charged_how(out: Outcome) -> str:
    return {"indictment": "indictment", "complaint": "indictment", "information": "information"}[out.charge_kind]


# ---------------------------------------------------------------------------
# Press releases
# ---------------------------------------------------------------------------

def press_charged(case: Case, rng: random.Random) -> Rec:
    first = case.outcomes[case.defendants[0].key]
    by_complaint = first.charge_kind == "complaint" and rng.random() < 0.5
    happened = first.complaint if by_complaint else first.charge
    rec = Rec(case, "press", "press_charged", rng, happened + timedelta(days=rng.choice((0, 0, 0, 1, 3))))
    people, keys = case.defendants, [p.key for p in case.defendants]
    announcer = _official(case, rng, "U.S. Attorney")
    when, stamp = _when(rec, happened, "indictment" if not by_complaint else "filed")
    offenses = first.offenses
    plural = len(people) > 1
    noun = f"{words(len(people)).capitalize()} people" if plural else f"A {people[0].city} resident"
    noun_inline = noun[0].lower() + noun[1:]
    verb = "were" if plural else "was"

    if by_complaint:
        lead = f"{case.district[2]} – {noun} {verb} arrested and charged in a criminal complaint {when} with {_join([rec.offense(o) for o in offenses])}, {announcer} announced."
        rec.event("complaint", stamp, keys)
        if first.arrest == happened:
            rec.event("arrest", stamp, keys)
        else:
            rec.event("arrest", None, keys)
        rec.tag("stage", "charged", "arrested")
    elif first.charge_kind == "information":
        lead = f"{case.district[2]} – {noun} {verb} charged {when} in a criminal information with {_join([rec.offense(o) for o in offenses])}, {announcer} announced."
        rec.event("information", stamp, keys)
        rec.tag("stage", "charged")
    else:
        lead = rng.choice((
            f"{case.district[2]} – {noun} {verb} indicted {when} on charges of {_join([rec.offense(o) for o in offenses])}, {announcer} announced.",
            f"{case.district[2]} – A federal grand jury returned an indictment {when} charging {noun_inline} with {_join([rec.offense(o) for o in offenses])}, {announcer} announced.",
        ))
        rec.event("indictment", stamp, keys)
        rec.tag("stage", "charged")
    rec.add(lead)

    counts = len(offenses)
    intro = _join([rec.intro(p).rstrip(",") for p in people]) if plural else rec.intro(people[0])
    cited = rng.random() < 0.4
    charge_list = _join([f"{rec.offense(o)}" + (f" ({rec.cite(o)})" if cited else "") for o in offenses])
    body = f"{intro}{',' if plural else ''} {'are' if plural else 'is'} charged in {'a' if counts != 8 else 'an'} {words(counts)}-count {'complaint' if by_complaint else _charged_how(first)} with {charge_list}."
    if first.arrest and not by_complaint and rng.random() < 0.7:
        arrested, arrested_stamp = _when(rec, first.arrest, "arrest") if (rec.dated - first.arrest).days <= 1 else (f"on {rec.day(first.arrest, 'arrest')}", first.arrest.isoformat())
        body += f" {_join([rec.last(p) for p in people])} {verb} arrested {arrested}."
        rec.event("arrest", arrested_stamp, keys)
        rec.tag("stage", "arrested")
    if rng.random() < 0.3:
        body += f" The case is docketed as No. {rec.docket()}."
    rec.add(body, "According to the charging documents:", _story(rec, people), _exposure(rec, offenses))
    rec.add(*_credits(rec))
    rec.add(rng.choice((
        "The charges and allegations contained in the charging documents are merely accusations. The defendants are presumed innocent unless and until proven guilty.",
        "An indictment is merely an allegation. All defendants are presumed innocent until proven guilty beyond a reasonable doubt in a court of law.",
    )))
    title = f"{noun} Charged with {OFFENSES[offenses[0]][2].title()}"
    _press_entry(rec, "charged", title, "early")
    return rec


def press_disposed(case: Case, rng: random.Random) -> Rec:
    people = case.defendants
    lead_person = people[0]
    first = case.outcomes[lead_person.key]
    rec = Rec(case, "press", "press_disposed", rng, first.disposition_date + timedelta(days=rng.choice((0, 0, 0, 1, 2))))
    announcer = _official(case, rng, "U.S. Attorney")
    when, stamp = _when(rec, first.disposition_date, "plea" if first.disposition == "plea" else "verdict")
    together = [p for p in people if case.outcomes[p.key].disposition == first.disposition
                and case.outcomes[p.key].disposition_date == first.disposition_date]
    keys = [p.key for p in together]
    offenses = first.offenses
    plural = len(together) > 1
    noun = f"{words(len(together)).capitalize()} {lead_person.state} residents" if plural else f"A {lead_person.city} resident"
    noun_inline = noun[0].lower() + noun[1:]

    if first.disposition == "plea":
        rec.add(f"{case.district[2]} – {noun} pleaded guilty {when} to {_join([rec.offense(o) for o in offenses])}, {announcer} announced.")
        rec.event("plea", stamp, keys)
        rec.tag("stage", "plea")
        intro = _join([rec.intro(p).rstrip(",") for p in together]) if plural else rec.intro(lead_person)
        body = f"{intro}{',' if plural else ''} entered the plea{'s' if plural else ''} before U.S. District Judge {case.judge.full}."
    else:
        days = rng.choice((3, 4, 5, 7, 9))
        rec.add(f"{case.district[2]} – A federal jury convicted {noun_inline} {when} of {_join([rec.offense(o) for o in offenses])} after a {words(days)}-day trial, {announcer} announced.")
        rec.event("verdict", stamp, keys)
        rec.tag("stage", "convicted")
        intro = _join([rec.intro(p).rstrip(",") for p in together]) if plural else rec.intro(lead_person)
        body = f"{intro}{',' if plural else ''} {'were' if plural else 'was'} found guilty on all counts. U.S. District Judge {case.judge.full} presided over the trial."
    if rng.random() < 0.55:
        how = "indicted" if first.charge_kind != "information" else "charged"
        earlier, earlier_stamp = _earlier(rec, first.charge, "indictment")
        body += f" {_join([rec.last(p) for p in together])} {'were' if plural else 'was'} {how} {earlier}."
        rec.event("indictment" if how == "indicted" else "information", earlier_stamp, keys)
        rec.tag("stage", "charged")
    if first.scheduled_sentencing:
        body += " " + pick(
            rng,
            lambda: f"Sentencing is scheduled for {rec.day(first.scheduled_sentencing, 'scheduled')}.",
            lambda: f"Judge {case.judge.surname} scheduled sentencing for {rec.day(first.scheduled_sentencing, 'scheduled')}.",
            lambda: f"{rec.last(lead_person)} is scheduled to be sentenced on {rec.day(first.scheduled_sentencing, 'scheduled')}.",
        )
    rec.add(body)

    for person in people:
        if person in together:
            continue
        other = case.outcomes[person.key]
        if other.disposition == "plea":
            earlier, earlier_stamp = _earlier(rec, other.disposition_date, "plea")
            rec.add(f"A co-defendant, {rec.intro(person)} pleaded guilty {earlier} and is awaiting sentencing.")
            rec.event("plea", earlier_stamp, [person.key])
            rec.tag("stage", "plea")
        else:
            earlier, earlier_stamp = _earlier(rec, other.disposition_date, "verdict")
            rec.add(f"A co-defendant, {rec.intro(person)} was convicted by a jury {earlier}.")
            rec.event("verdict", earlier_stamp, [person.key])
            rec.tag("stage", "convicted")

    rec.add("According to court documents and statements made in court:", _story(rec, people))
    if first.disposition == "plea" and case.loss and rng.random() < 0.35:
        agreed = case.loss
        rec.add(f"As part of the plea agreement, {rec.last(lead_person)} agreed to pay {rec.money(agreed, 'restitution', [lead_person.key], optional=True)} in restitution.")
    rec.add(_exposure(rec, offenses))
    rec.add(*_credits(rec))
    verb = "Pleads Guilty to" if first.disposition == "plea" else "Convicted of"
    _press_entry(rec, "plea" if first.disposition == "plea" else "verdict", f"{lead_person.city} Resident {verb} {OFFENSES[offenses[0]][2].title()}", "plea_or_convicted")
    return rec


def _sentence_clause(rec: Rec, person: Person, out: Outcome, *, months: int | None = None) -> str:
    """"to 87 months in federal prison" or "to three years of probation", noted as this person's."""
    months = out.months if months is None else months
    if months is None:
        return f"to {rec.term(out.probation_years * 12, 'probation', [person.key])} of probation"
    place = rec.rng.choice(("in federal prison", "in prison", "of imprisonment", "in federal prison"))
    return f"to {rec.term(months, 'imposed', [person.key])} {place}"


def _orders(rec: Rec, person: Person, out: Outcome, subject: str) -> str:
    """Supervised release and money orders for one person, as one or two sentences."""
    rng, judge, pieces = rec.rng, rec.case.judge, []
    if out.supervised_years:
        pieces.append(f"to serve {rec.term(out.supervised_years * 12, 'supervised_release', [person.key])} of supervised release")
    if out.restitution:
        pieces.append(pick(
            rng,
            lambda: f"to pay {rec.money(out.restitution, 'restitution', [person.key])} in restitution",
            lambda: f"to pay restitution of {rec.money(out.restitution, 'restitution', [person.key])}",
        ))
    if out.forfeiture:
        pieces.append(f"to forfeit {rec.money(out.forfeiture, 'forfeiture', [person.key])}")
    if out.fine:
        pieces.append(f"to pay a {rec.money(out.fine, 'fine', [person.key])} fine")
    if not pieces:
        return ""
    return rng.choice((
        f"U.S. District Judge {judge.full} also ordered {subject} {_join(pieces)}.",
        f"In addition, Judge {judge.surname} ordered {subject} {_join(pieces)}.",
        f"{subject[0].upper()}{subject[1:]} was also ordered {_join(pieces)}.",
    ))


def press_sentenced(case: Case, rng: random.Random) -> Rec:
    people = case.defendants
    lead = people[0]
    first = case.outcomes[lead.key]
    resentenced = case.planted == "resentencing"
    happened = first.resentencing if resentenced else max(case.outcomes[p.key].sentencing for p in people)
    rec = Rec(case, "press", "press_sentenced", rng, happened + timedelta(days=rng.choice((0, 0, 0, 0, 1, 4))))
    announcer = _official(case, rng, "U.S. Attorney")
    today = [p for p in people if (case.outcomes[p.key].resentencing if resentenced and p is lead else case.outcomes[p.key].sentencing) == happened]
    when, stamp = _when(rec, happened, "sentencing")
    keys = [p.key for p in today]
    offense_words = _join([rec.offense(o) for o in first.offenses])
    rec.tag("stage", "sentenced")

    if resentenced:
        original, original_stamp = _earlier(rec, first.sentencing, "sentencing")
        rec.add(
            f"{case.district[2]} – A {lead.city} resident was resentenced {when} to {rec.term(first.resentenced_months, 'imposed', [lead.key])} in federal prison for {offense_words}, {announcer} announced.",
            f"{rec.intro(lead)} was first sentenced {original} to {rec.term(first.months, ['imposed', 'prior'], [lead.key])} in prison. The court of appeals vacated that sentence and returned the case to U.S. District Judge {case.judge.full}.",
        )
        rec.event("sentencing", original_stamp, [lead.key])
        rec.event("sentencing", stamp, [lead.key])
    elif len(today) == 1:
        rec.add(f"{case.district[2]} – A {today[0].city} resident was sentenced {when} {_sentence_clause(rec, today[0], case.outcomes[today[0].key])} for {offense_words}, {announcer} announced.")
        rec.event("sentencing", stamp, keys)
    else:
        rec.add(f"{case.district[2]} – {words(len(today)).capitalize()} people were sentenced {when} for their roles in a scheme involving {offense_words}, {announcer} announced.")
        rec.event("sentencing", stamp, keys)

    for person in people:
        out = case.outcomes[person.key]
        if person in today and len(today) == 1 and not resentenced:
            how = "pleaded guilty" if out.disposition == "plea" else "was convicted by a federal jury"
            earlier, earlier_stamp = _earlier(rec, out.disposition_date, "plea" if out.disposition == "plea" else "verdict")
            if case.planted == "date_inconsistency" and person is lead:
                # The document states a plea date that falls after the sentencing date.
                wrong = out.sentencing + timedelta(days=rng.randint(20, 90))
                earlier, earlier_stamp = f"on {rec.day(wrong, 'plea')}", wrong.isoformat()
                rec.values = [v for v in rec.values if not (v["field"] == "date" and v["roles"] == ["plea"] and v["value"] != wrong.isoformat())]
            line = f"{rec.intro(person)} {how} {earlier}."
            if case.planted == "plea_withdrawn" and person is lead:
                withdrawn, withdrawn_stamp = _earlier(rec, out.withdrawn_plea, "plea")
                line = f"{rec.intro(person)} pleaded guilty {withdrawn} but was later allowed to withdraw the plea. A federal jury convicted {rec.last(person)} {earlier}."
                rec.event("plea", withdrawn_stamp, [person.key])
                rec.tag("stage", "plea")
            rec.event("plea" if out.disposition == "plea" else "verdict", earlier_stamp, [person.key])
            rec.tag("stage", "plea" if out.disposition == "plea" else "convicted")
            rec.add(f"{line} {_orders(rec, person, out, rec.last(person))}".strip())
        elif person in today and not resentenced:
            line = f"{rec.intro(person)} was sentenced {_sentence_clause(rec, person, out)}."
            rec.add(f"{line} {_orders(rec, person, out, rec.last(person))}".strip())
        elif resentenced and person is lead:
            rec.add(_orders(rec, person, out, rec.last(person)))
        else:
            earlier, earlier_stamp = _earlier(rec, out.sentencing, "sentencing")
            rec.add(f"A co-defendant, {rec.intro(person)} was sentenced {earlier} {_sentence_clause(rec, person, out)}.")
            rec.event("sentencing", earlier_stamp, [person.key])

    if len(today) > 1:
        out = case.outcomes[today[0].key]
        if all(case.outcomes[p.key].disposition == out.disposition and case.outcomes[p.key].disposition_date == out.disposition_date for p in today):
            how = "pleaded guilty" if out.disposition == "plea" else "were convicted at trial"
            earlier, earlier_stamp = _earlier(rec, out.disposition_date, "plea" if out.disposition == "plea" else "verdict")
            rec.add(f"{_join([rec.last(p) for p in today])} {how} {earlier}.")
            rec.event("plea" if out.disposition == "plea" else "verdict", earlier_stamp, keys)
            rec.tag("stage", "plea" if out.disposition == "plea" else "convicted")

    rec.add("According to court documents and evidence presented in court:", _story(rec, people))
    if rng.random() < 0.3:
        weeks = rng.choice((2, 3, 6))
        rec.add(f"The sentence follows a {words(weeks)}-year investigation by {case.agencies[0]}.")
    if rng.random() < 0.25 and first.offenses[0] in MAXIMUM_YEARS:
        rec.add(f"The offense of {OFFENSES[first.offenses[0]][2]} carried a maximum penalty of {rec.term(MAXIMUM_YEARS[first.offenses[0]] * 12, 'exposure')} in prison.")
    if rng.random() < 0.2:
        rec.add("If you or someone you know is age 60 or older and has been a victim of financial fraud, help is available through the National Elder Fraud Hotline at 1-833-372-8311.")
    rec.add(*_credits(rec))
    shown = first.resentenced_months if resentenced else first.months
    title = f"{lead.city} Resident Sentenced" + (f" to {shown} Months in Prison" if shown else " to Probation") + f" for {OFFENSES[first.offenses[0]][2].title()}"
    _press_entry(rec, "sentenced", title, "sentenced")
    return rec


# ---------------------------------------------------------------------------
# Court filings
# ---------------------------------------------------------------------------

def _court_entry(rec: Rec, press: Rec | None, number: int) -> None:
    case = rec.case
    digest = hashlib.sha256(rec.text.encode("utf-8")).hexdigest()
    rec.entry = {
        "kind": "court", "domain": case.domain, "domains": [case.domain],
        "source_url": f"https://gold.example/docket/{case.case_id}/{number}/",
        "agency": f"District Court, {case.district[1]}", "docket_number": case.docket,
        "press_url": press.entry["source_url"] if press else None, "sha256": digest, "notice": NOTICE,
    }


def _header(rec: Rec, document: int, filed: date, page: int, pages: int) -> str:
    return f"Case {rec.docket('court')} Document {document} Filed {rec.day(filed, 'filed', 'slash2')} Page {page} of {pages}"


def _caption(rec: Rec, people: list[Person], title: str) -> list[str]:
    case = rec.case
    names = [rec.person(p, p.caps) for p in people]
    lines = ["UNITED STATES DISTRICT COURT", case.district[1].upper(), "", "UNITED STATES OF AMERICA,", "Plaintiff,", f"v. Case No. {rec.docket()}"]
    lines += [f"{name}," if index == len(names) - 1 else f"{name}, and" for index, name in enumerate(names)]
    lines += ["Defendants." if len(names) > 1 else "Defendant.", "", title, ""]
    return lines


def indictment(case: Case, rng: random.Random, press: Rec | None) -> Rec:
    first = case.outcomes[case.defendants[0].key]
    information = first.charge_kind == "information"
    rec = Rec(case, "court", "indictment", rng, first.charge)
    people, keys = case.defendants, [p.key for p in case.defendants]
    rec.add(_header(rec, 1 if not information else 3, first.charge, 1, 6), "")
    rec.add(*_caption(rec, people, "INFORMATION" if information else "INDICTMENT"))
    rec.tag("document_type", "information" if information else "indictment")
    rec.event("information" if information else "indictment", first.charge.isoformat(), keys)
    rec.add("THE UNITED STATES ATTORNEY CHARGES:" if information else "THE GRAND JURY CHARGES:", "")
    names = _join([rec.person(p, p.caps) for p in people])
    noun = "the defendants" if len(people) > 1 else "the defendant"
    start, end = case.offense_start, case.offense_end
    rec.event("offense", f"{start.year:04d}-{start.month:02d}", keys)
    for index, offense in enumerate(first.offenses):
        title, section, name, _ = OFFENSES[offense]
        rec.add(f"COUNT {_ORDINAL[index]}", f"({name.title()})", "")
        if index == 0:
            rec.add(
                f"1. Beginning in or about {rec.month(start, 'offense')} and continuing through in or about {rec.month(end, 'offense')}, in the "
                f"{case.district[1]} and elsewhere, {noun}, {names}, knowingly devised and intended to devise a scheme and "
                "artifice to defraud and to obtain money and property by means of materially false and fraudulent pretenses, "
                "representations and promises." if case.narrative.financial else
                f"1. Beginning in or about {rec.month(start, 'offense')} and continuing through in or about {rec.month(end, 'offense')}, in the "
                f"{case.district[1]} and elsewhere, {noun}, {names}, knowingly committed the offense described in this count."
            )
            act = start + timedelta(days=rng.randint(40, 200))
            if case.narrative.financial:
                amount = float(rng.choice((4_800, 9_950, 12_500, 27_300, 48_500, 96_000)))
                rec.add(
                    f"2. On or about {rec.day(act, 'offense', 'long')}, for the purpose of executing the scheme, {noun} caused to be "
                    f"transmitted by means of wire communication in interstate commerce a transfer of {rec.money(amount, ['loss', 'proceeds'], optional=True)} "
                    "from an account held by a person known to the grand jury."
                )
            else:
                rec.add(f"2. On or about {rec.day(act, 'offense', 'long')}, {noun} committed an act in furtherance of the offense.")
        else:
            rec.add(f"{index + 2}. The allegations of Count One are incorporated here. From in or about {rec.month(start, 'offense')} through in or about {rec.month(end, 'offense')}, {noun} committed the offense of {rec.offense(offense)}.")
        form = "title" if rng.random() < 0.6 else "usc"
        rec.add(f"All in violation of {rec.cite(offense, form)}.", "")
    if case.loss:
        rec.add(
            "FORFEITURE ALLEGATION", "",
            f"Upon conviction of the offenses alleged in this {'Information' if information else 'Indictment'}, {noun} shall forfeit to the United States any property, real or "
            f"personal, which constitutes or is derived from proceeds traceable to the offenses, including a money judgment in the amount of {rec.money(case.loss, 'forfeiture', optional=True)}.",
            "",
        )
    if not information:
        rec.add("A TRUE BILL", "/s/ Foreperson", "FOREPERSON", "")
    rec.add(f"/s/ {case.prosecutor.full}", case.prosecutor.caps, "Assistant United States Attorney")
    rec.unscored.add("stage")
    _court_entry(rec, press, 1)
    return rec


def plea_agreement(case: Case, rng: random.Random, press: Rec | None, person: Person) -> Rec:
    out = case.outcomes[person.key]
    filed = out.disposition_date
    rec = Rec(case, "court", "plea_agreement", rng, filed)
    offense = out.offenses[0]
    name, caps = OFFENSES[offense][2], rec.person(person, person.caps)
    rec.add(_header(rec, rng.randint(18, 60), filed, 1, 14), "")
    rec.add(*_caption(rec, [person], f"PLEA AGREEMENT FOR DEFENDANT {caps}"))
    rec.tag("document_type", "plea_agreement")
    rec.add(
        f"1. This constitutes the plea agreement between {caps} (\"defendant\") and the United States Attorney's Office for the {case.district[1]} "
        "(the \"USAO\") in the above-captioned case. This agreement is limited to the USAO and cannot bind any other federal, state, local, or foreign "
        "prosecuting, enforcement, administrative, or regulatory authorities.",
        "", "DEFENDANT'S OBLIGATIONS", "",
        f"2. Defendant agrees to plead guilty to Count One of the {'information' if out.charge_kind == 'information' else 'indictment'}, which charges defendant with {name} in violation of {rec.cite(offense)}.",
        "", "PENALTIES", "",
    )
    if offense in MAXIMUM_YEARS:
        rec.add(
            f"3. Defendant understands that the statutory maximum sentence that the Court can impose for a violation of {rec.cite(offense, 'title')} is: "
            f"{rec.term(MAXIMUM_YEARS[offense] * 12, 'exposure')} of imprisonment; a {rec.term(36, 'exposure', adjective=True)} period of supervised release; a fine of "
            f"{rec.money(250_000, 'exposure_fine')} or twice the gross gain or gross loss resulting from the offense, whichever is greatest; and a mandatory special "
            f"assessment of {rec.money(100, 'special_assessment')}."
        )
    else:
        rec.add(
            f"3. Defendant understands that the statutory mandatory minimum sentence that the Court must impose for a violation of {rec.cite(offense, 'title')} is "
            f"{rec.term(120, 'exposure')} of imprisonment, and that the Court must also impose a mandatory special assessment of {rec.money(100, 'special_assessment')}."
        )
    if case.loss:
        rec.add(
            "", "RESTITUTION", "",
            "4. Defendant understands that defendant will be required to pay full restitution to the victims of the offense. The parties currently believe that the "
            f"applicable amount of restitution is approximately {rec.money(case.loss, 'restitution', [person.key])}, but recognize and agree that this amount could change.",
        )
    start, end = case.offense_start, case.offense_end
    rec.add(
        "", "FACTUAL BASIS", "",
        f"5. Defendant admits that defendant is, in fact, guilty of the offense to which defendant is agreeing to plead guilty. Beginning in or about {rec.month(start, 'offense')} "
        f"and continuing until in or about {rec.month(end, 'offense')}, defendant knowingly participated in the conduct charged in Count One.",
    )
    rec.event("offense", f"{start.year:04d}-{start.month:02d}", [person.key])
    if case.loss:
        rec.add(f"6. The parties agree that the loss resulting from the offense was {rec.money(case.loss, 'loss')}.")
    signed = filed - timedelta(days=rng.randint(2, 12))
    rec.add("", f"Dated: {rec.day(signed, None, 'long')}", f"/s/ {case.prosecutor.full}", "Assistant United States Attorney", f"/s/ {person.full}", "Defendant")
    rec.person(person, person.full)
    rec.unscored.add("stage")
    _court_entry(rec, press, 2)
    return rec


def judgment(case: Case, rng: random.Random, press: Rec | None, person: Person) -> Rec:
    out = case.outcomes[person.key]
    resentenced = case.planted == "resentencing" and out.resentencing is not None
    imposed = out.resentencing if resentenced else out.sentencing
    months = out.resentenced_months if resentenced else out.months
    filed = imposed + timedelta(days=rng.randint(1, 9))
    rec = Rec(case, "court", "judgment", rng, filed)
    caps = rec.person(person, person.caps)
    number = case.defendants.index(person) + 1
    document = rng.randint(70, 190)
    attorney = _official(case, rng, "").strip().upper().replace(".", "")
    short = rng.random() < 0.5

    rec.add(
        _header(rec, document, filed, 1, 7), "",
        "AO 245B (Rev. 09/19) Judgment in a Criminal Case", "Sheet 1", "",
        "UNITED STATES DISTRICT COURT", case.district[1],
        f"UNITED STATES OF AMERICA {'AMENDED ' if resentenced else ''}JUDGMENT IN A CRIMINAL CASE", "v.",
        f"{caps} Case Number: {rec.docket('caps')}({number})", f"USM Number: {rng.randint(10000, 99999)}-{rng.randint(100, 599)}",
        attorney, "Defendant's Attorney", "", "THE DEFENDANT:",
    )
    rec.tag("document_type", "judgment")
    counts = ", ".join(str(i + 1) for i in range(len(out.offenses)))
    if out.disposition == "plea":
        rec.add(f"☒ pleaded guilty to count(s) {counts}", "☐ pleaded nolo contendere to count(s)", "which was accepted by the court.", "☐ was found guilty on count(s)", "after a plea of not guilty.")
    else:
        rec.add("☐ pleaded guilty to count(s)", "☐ pleaded nolo contendere to count(s)", "which was accepted by the court.", f"☒ was found guilty on count(s) {counts}", "after a plea of not guilty.")
    rec.add("", "The defendant is adjudicated guilty of these offenses:", "Title & Section / Nature of Offense Offense Ended Count")
    for index, offense in enumerate(out.offenses):
        rec.tag("offense", OFFENSES[offense][3])
        rec.add(f"{rec.cite(offense, 'short' if short else 'usc')} {OFFENSES[offense][2].title()} {rec.day(case.offense_end, 'offense', 'slash4')} {index + 1}")
    rec.add(
        "", "The defendant is sentenced as provided in pages 2 through 7 of this judgment. The sentence is imposed pursuant to",
        "the Sentencing Reform Act of 1984.", "",
        "It is ordered that the defendant must notify the United States attorney for this district within 30 days of any change of name,",
        "residence, or mailing address until all fines, restitution, costs, and special assessments imposed by this judgment are fully paid.",
        rec.day(imposed, "sentencing", "long"), "Date of Imposition of Judgment",
        f"s/ {case.judge.full}", "Signature of Judge", f"{case.judge.caps}, UNITED STATES DISTRICT JUDGE", "Name and Title of Judge",
        rec.day(filed - timedelta(days=rng.randint(0, 1)), None, "slash4"), "Date", "",
    )
    rec.event("sentencing", imposed.isoformat(), [person.key])

    rec.add(_header(rec, document, filed, 2, 7), "", "Sheet 2 — Imprisonment" if months is not None else "Sheet 4 — Probation", f"DEFENDANT: {caps}", f"CASE NUMBER: {rec.docket('caps')}({number})", "")
    if months is not None:
        rec.add(
            "IMPRISONMENT",
            "The defendant is hereby committed to the custody of the Federal Bureau of Prisons to be imprisoned for a total term of:",
            f"{rec.term(months, 'imposed', [person.key])}.", "",
            "☒ The defendant is remanded to the custody of the United States Marshal.", "",
            "SUPERVISED RELEASE",
            f"Upon release from imprisonment, you will be on supervised release for a term of: {rec.term(out.supervised_years * 12, 'supervised_release', [person.key])}.", "",
        )
    else:
        rec.add("PROBATION", f"You are hereby sentenced to probation for a term of: {rec.term(out.probation_years * 12, 'probation', [person.key])}.", "")
    rec.add(
        _header(rec, document, filed, 5, 7), "", "Sheet 5 — Criminal Monetary Penalties", f"DEFENDANT: {caps}", "",
        "CRIMINAL MONETARY PENALTIES",
        "The defendant must pay the total criminal monetary penalties under the schedule of payments on Sheet 6.",
        "Assessment Restitution Fine",
        f"TOTALS {rec.money(100.0 * len(out.offenses), 'special_assessment', [person.key])} "
        + (rec.money(out.restitution, 'restitution', [person.key]) if out.restitution else "$0.00") + " "
        + (rec.money(out.fine, 'fine', [person.key]) if out.fine else "$0.00"), "",
    )
    if out.forfeiture:
        rec.add(f"The defendant shall forfeit the defendant's interest in the following property to the United States: a money judgment in the amount of {rec.money(out.forfeiture, 'forfeiture', [person.key])}.", "")
    if out.restitution:
        rate = rng.choice((100, 150, 200, 250))
        rec.add("SCHEDULE OF PAYMENTS", f"Payment to begin immediately. Any balance shall be paid in installments of not less than ${rate} per month, to commence 60 days after release from imprisonment.")
    rec.unscored.add("stage")
    _court_entry(rec, press, 3)
    return rec
