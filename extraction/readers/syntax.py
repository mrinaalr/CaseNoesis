"""Parser-backed readers: a dependency parse and named-entity types.

Two more evidence families, both from one Stanza pass over the sentences that
hold something to read:

    dependency   what governs each value, and who its subject is. "Judge A
                 sentenced B to 87 months" and "B was sentenced by Judge A to
                 87 months" give the same answer here and different ones to a
                 reader that goes by word order.
    ner          entity types only. A span is a person, or it is an
                 organization or a place that a name rule took for a person.
                 An entity type says nothing about a role, so on roles this
                 family abstains.

Both are off unless `CASENOESIS_SYNTAX=1`, like the LLM reader: a parse costs
about a thousand times what a pattern costs, and a run records which readers
were on. The models are Stanza's English `default_fast` package, loaded from
the local Stanza resources directory and never downloaded by this module.

Only sentences with a typed token, an event trigger or a name are parsed, and
at most `MAX_CHARS` characters of a record. A long filing is read in part by
these two families and in full by the others.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from extraction import fields, names, spans as sp
from extraction.readers import Doc, assertion, register_reader

VERSION = "stanza_1.12_default_fast_1.0"
MAX_CHARS = 14000
MAX_SENTENCE = 900


def enabled() -> bool:
    return os.environ.get("CASENOESIS_SYNTAX", "") == "1"


@dataclass
class Word:
    index: int
    start: int
    end: int
    text: str
    lemma: str
    upos: str
    deprel: str
    head: int  # index into Parse.words, -1 at a root


@dataclass
class Parse:
    text: str = ""
    words: list[Word] = field(default_factory=list)
    entities: list[tuple[int, int, str]] = field(default_factory=list)
    children: dict[int, list[int]] = field(default_factory=dict)

    def kids(self, word: Word) -> list[Word]:
        return [self.words[i] for i in self.children.get(word.index, [])]

    def parent(self, word: Word) -> Word | None:
        return self.words[word.head] if word.head >= 0 else None

    def inside(self, start: int, end: int) -> list[Word]:
        return [w for w in self.words if w.start < end and w.end > start]

    def head_of(self, start: int, end: int) -> Word | None:
        """The word of a span that the rest of the span hangs from."""
        inside = self.inside(start, end)
        ids = {w.index for w in inside}
        for word in inside:
            if word.head not in ids:
                return word
        return inside[0] if inside else None

    def governing_verb(self, word: Word) -> tuple[list[Word], Word | None]:
        """Words from `word` up to the first verb above it, and that verb."""
        path, current = [], word
        for _ in range(12):
            current = self.parent(current)
            if current is None:
                return path, None
            path.append(current)
            if current.upos in ("VERB", "AUX"):
                return path, current
        return path, None


_NLP = None
_CACHE: tuple[str, Parse] | None = None


def _pipeline():
    global _NLP
    if _NLP is None:
        import stanza
        import torch

        torch.set_num_threads(int(os.environ.get("CASENOESIS_SYNTAX_THREADS", "1")))
        _NLP = stanza.Pipeline(
            "en", processors="tokenize,pos,lemma,depparse,ner",
            package=os.environ.get("CASENOESIS_STANZA_PACKAGE", "default_fast"),
            device="cpu", verbose=False, download_method=None,
        )
    return _NLP


def _worth_parsing(text: str) -> list[tuple[int, int]]:
    marks = [start for name in ("sentence", "money", "date", "event") for start, *_ in fields.ITERATORS[name](text)]
    marks += [start for start, _, _ in names.iter_people(text)]
    marks.sort()
    chosen, used, position = [], 0, 0
    for start, end in sp.sentence_spans(text):
        while position < len(marks) and marks[position] < start:
            position += 1
        if position < len(marks) and marks[position] < end:
            end = min(end, start + MAX_SENTENCE)
            if used + (end - start) > MAX_CHARS:
                break
            chosen.append((start, end))
            used += end - start
    return chosen


def parse(doc: Doc) -> Parse:
    """One parse per record, shared by both readers."""
    global _CACHE
    if _CACHE is not None and _CACHE[0] is doc.text:
        return _CACHE[1]
    import stanza

    out = Parse(text=doc.text)
    chosen = _worth_parsing(doc.text)
    if chosen:
        parsed = _pipeline()([stanza.Document([], text=doc.text[start:end]) for start, end in chosen])
        for (base, _), document in zip(chosen, parsed):
            for sentence in document.sentences:
                offset = len(out.words)
                for word in sentence.words:
                    token = word.parent
                    start = word.start_char if word.start_char is not None else token.start_char
                    end = word.end_char if word.end_char is not None else token.end_char
                    out.words.append(Word(
                        offset + word.id - 1, base + start, base + end, word.text, (word.lemma or word.text).lower(),
                        word.upos or "", word.deprel or "", offset + word.head - 1 if word.head else -1,
                    ))
            out.entities += [(base + e.start_char, base + e.end_char, e.type) for e in document.ents]
        for word in out.words:
            if word.head >= 0:
                out.children.setdefault(word.head, []).append(word.index)
    _CACHE = (doc.text, out)
    return out


# ---------------------------------------------------------------------------
# What the parse says about a value
# ---------------------------------------------------------------------------

_TITLES = {
    "judge", "justice", "attorney", "agent", "officer", "detective", "inspector", "sheriff", "chief", "director",
    "prosecutor", "investigator", "marshal", "magistrate", "counsel", "foreperson", "general", "secretary",
}
_JUDICIAL = {"sentence", "resentence", "convict", "charge", "indict", "arrest", "order", "find", "extradite", "direct"}
_ADMITS = {"plead", "admit", "face", "agree"}
_PLANNED_HEAD = {"schedule", "expect", "set", "slate", "agree", "intend", "plan", "await"}
_EXPOSURE_WORD = {"maximum", "minimum", "penalty", "mandatory", "statutory", "punishable"}
_EXPOSURE_VERB = {"face", "carry", "punish", "provide"}
_IMPOSED_VERB = {"sentence", "resentence", "imprison", "commit", "impose", "receive", "jail"}
_MONEY_NEAR = (
    ("special_assessment", {"assessment"}), ("restitution", {"restitution"}), ("forfeiture", {"forfeit", "forfeiture"}),
    ("fine", {"fine"}), ("bail", {"bond", "bail"}),
    ("loss", {"loss", "lose", "defraud", "steal", "embezzle", "swindle", "bilk", "misappropriate"}),
    ("proceeds", {"proceeds", "obtain", "receive", "launder", "gain", "net", "generate", "pocket", "profit"}),
)
_DATE_VERB = {
    "sentence": "sentencing", "resentence": "sentencing", "plead": "plea", "indict": "indictment", "charge": "indictment",
    "arrest": "arrest", "convict": "verdict", "file": "filed", "schedule": "scheduled", "set": "scheduled", "slate": "scheduled",
}
_EVENT_VERB = {
    "sentence": "sentencing", "resentence": "sentencing", "plead": "plea", "indict": "indictment", "arrest": "arrest",
}


def _lemmas(words: list[Word]) -> set[str]:
    return {w.lemma for w in words}


def _mood(parse: Parse, verb: Word | None) -> str | None:
    """`scheduled`, `hypothetical`, or None for something reported as done."""
    for _ in range(3):
        if verb is None:
            return None
        kids = parse.kids(verb)
        if any(k.deprel == "mark" and k.lemma in ("if", "unless", "until") for k in kids):
            return "hypothetical"
        if any(k.deprel.startswith("aux") and k.lemma in ("could", "may", "might", "would", "can") for k in kids):
            return "hypothetical"
        if any(k.deprel.startswith("aux") and k.lemma == "will" for k in kids):
            return "scheduled"
        above = parse.parent(verb)
        if above is not None and verb.deprel in ("xcomp", "ccomp", "advcl", "csubj", "acl") and above.lemma in _PLANNED_HEAD:
            return "scheduled"
        if verb.deprel not in ("xcomp", "conj", "aux:pass"):
            return None
        verb = above
    return None


def _statute_list(parse: Parse, word: Word) -> bool:
    """True when the sentence's subject is what a statute allows: "the statutory
    maximum sentence ... is: 20 years; a three-year period of supervised release; a fine"."""
    root = word
    for _ in range(40):
        above = parse.parent(root)
        if above is None:
            break
        root = above
    for kid in parse.kids(root):
        if kid.deprel.startswith("nsubj") and kid.lemma in ("sentence", "penalty", "punishment", "term"):
            if _lemmas(parse.kids(kid)) & _EXPOSURE_WORD:
                return True
    return False


def _exposure(parse: Parse, word: Word, path: list[Word], verb: Word | None) -> bool:
    if _statute_list(parse, word) or sp.in_penalty_list(parse.text, word.start):
        return True
    nearby = _lemmas(path) | _lemmas(parse.kids(word))
    for node in path[:3]:
        nearby |= _lemmas(parse.kids(node))
    if nearby & _EXPOSURE_WORD:
        return True
    return verb is not None and (verb.lemma in _EXPOSURE_VERB or _mood(parse, verb) == "hypothetical")


def _term_role(parse: Parse, word: Word) -> str | None:
    path, verb = parse.governing_verb(word)
    nouns = _lemmas(parse.kids(word)) | _lemmas(path[:2])
    for node in path[:2]:
        if node.upos != "VERB":
            nouns |= _lemmas(parse.kids(node))
    if _exposure(parse, word, path, verb):
        return "exposure"
    if nouns & {"release", "supervision"}:
        return "supervised_release"
    if "probation" in nouns:
        return "probation"
    if verb is not None and verb.lemma in _IMPOSED_VERB:
        return "imposed"
    if verb is not None and verb.lemma == "serve":
        above = parse.parent(verb)
        if above is not None and above.lemma in ("order", "sentence"):
            return "imposed"
    return None


def _money_role(parse: Parse, word: Word) -> str | None:
    path, verb = parse.governing_verb(word)
    near = _lemmas(parse.kids(word)) | _lemmas(path[:1])
    if path and path[0].upos != "VERB":
        near |= _lemmas(parse.kids(path[0]))
    far = _lemmas(path) | (_lemmas(parse.kids(verb)) if verb is not None else set())
    for pool in (near, far):
        for role, cues in _MONEY_NEAR:
            if pool & cues:
                if role == "fine" and _exposure(parse, word, path, verb):
                    return "exposure_fine"
                return role
    return None


def _date_role(parse: Parse, word: Word) -> str | None:
    path, verb = parse.governing_verb(word)
    marks = {k.lemma for k in parse.kids(word) if k.deprel in ("case", "mark")}
    for node in path[:1]:
        marks |= {k.lemma for k in parse.kids(node) if k.deprel in ("case", "mark")}
    if verb is None:
        return None
    if verb.lemma in ("begin", "continue") or marks & {"from", "between", "through", "until", "since"}:
        return "offense"
    role = _DATE_VERB.get(verb.lemma)
    if role in ("sentencing", "plea", "verdict") and _mood(parse, verb) == "scheduled":
        return "scheduled"
    if verb.lemma == "find" and "guilty" in _lemmas(parse.kids(verb)):
        return "verdict"
    return role


def _event_role(parse: Parse, doc: Doc, start: int, end: int, kind: str) -> tuple[str | None, Word | None]:
    inside = parse.inside(start, end)
    verb = next((w for w in inside if w.upos == "VERB"), None)
    if verb is None:
        return None, None
    if "☐" in doc.text[max(0, start - 30): start]:
        return "not_event", verb
    mood = _mood(parse, verb)
    if mood == "hypothetical":
        return "not_event", verb
    if mood == "scheduled":
        return "scheduled", verb
    kids = parse.kids(verb)
    around = _lemmas(kids)
    for kid in kids:
        around |= _lemmas(parse.kids(kid))
    if kind == "convict":
        if any(k.deprel == "advmod" and k.lemma in ("previously", "earlier") for k in kids):
            return "not_event", verb
        return ("verdict" if around & {"jury", "trial", "juror", "verdict"} else "conviction"), verb
    if kind == "indict":
        return "indictment", verb
    if kind == "charge":
        if not any(k.deprel in ("aux:pass", "nsubj:pass", "nsubj") for k in kids):
            return None, verb
        for label in ("complaint", "information", "indictment"):
            if label in around:
                return label, verb
        return "charge", verb
    return _EVENT_VERB.get(verb.lemma, _EVENT_VERB.get(kind)), verb


def _is_official(parse: Parse, words: list[Word]) -> bool:
    head = next((w for w in words if w.head not in {x.index for x in words}), None)
    if head is None:
        return False
    if head.deprel == "obl:agent":
        return True
    above = parse.parent(head)
    if above is not None and head.deprel in ("flat", "appos", "compound", "nmod", "nmod:desc") and above.lemma in _TITLES:
        return True
    return any(k.lemma in _TITLES and k.deprel in ("compound", "nmod:desc", "appos", "flat", "amod", "nmod") for w in words for k in parse.kids(w))


def _party_role(parse: Parse, start: int, end: int) -> str | None:
    words = parse.inside(start, end)
    head = parse.head_of(start, end)
    if head is None:
        return None
    if _is_official(parse, words):
        return "official"
    above = parse.parent(head)
    if above is None:
        return None
    if above.lemma == "victim":
        return "victim"
    if head.deprel == "nsubj:pass" and above.lemma in _JUDICIAL:
        return "defendant"
    if head.deprel == "nsubj" and above.lemma in _ADMITS:
        return "defendant"
    if head.deprel in ("obj", "iobj") and above.lemma in _JUDICIAL:
        return "defendant"
    if head.deprel == "appos" and above.lemma in ("defendant", "co-defendant", "codefendant"):
        return "defendant"
    return None


def _who(parse: Parse, verb: Word, mention_at: dict[int, tuple[int, int]], depth: int = 0) -> list[tuple[int, int]]:
    """Person spans the verb's action falls on: its object when a court acts
    on someone, its subject otherwise. A pronoun subject gives no answer."""
    kids = parse.kids(verb)

    def people(words: list[Word]) -> list[tuple[int, int]]:
        found = []
        for word in words:
            for node in (word, *(k for k in parse.kids(word) if k.deprel in ("conj", "flat", "appos"))):
                span = mention_at.get(node.index)
                if span and span not in found and not _is_official(parse, parse.inside(*span)):
                    found.append(span)
        return found

    subjects = [k for k in kids if k.deprel.startswith("nsubj")]
    if verb.lemma in _JUDICIAL and any(k.deprel == "nsubj" for k in subjects):
        acted_on = people([k for k in kids if k.deprel in ("obj", "iobj")])
        if acted_on:
            return acted_on
    named = people(subjects)
    if named:
        return named
    if any(k.upos == "PRON" for k in subjects) or depth >= 3:
        return []
    above = parse.parent(verb)
    if above is None or verb.deprel not in ("xcomp", "conj", "ccomp", "advcl", "acl", "acl:relcl"):
        return []
    if verb.deprel == "xcomp":
        controlled = people([k for k in parse.kids(above) if k.deprel in ("obj", "iobj")])
        if controlled:
            return controlled
    if verb.deprel == "acl:relcl":
        return people([above])
    return _who(parse, above, mention_at, depth + 1)


def read_dependency(doc: Doc) -> list[dict[str, Any]]:
    if not enabled():
        return []
    parse_ = parse(doc)
    if not parse_.words:
        return []
    text, method, out = doc.text, "dependency_parse", []
    mention_at: dict[int, tuple[int, int]] = {}
    for start, end, _ in names.iter_mentions(text):
        for word in parse_.inside(start, end):
            mention_at[word.index] = (start, end)

    def attribute(field_name: str, start: int, end: int, verb: Word | None) -> None:
        spans = _who(parse_, verb, mention_at) if verb is not None else []
        if spans:
            out.append(assertion("attribution", None, None, method, VERSION, 0.8, start, end,
                                 of=field_name, people=[list(span) for span in spans], rule="parse_subject"))

    for start, end, value, _ in fields.iter_duration(text):
        word = parse_.head_of(start, end)
        if word is None:
            continue
        role = _term_role(parse_, word)
        out.append(assertion("sentence", value, role, method, VERSION, 0.8 if role else 0.5, start, end))
        attribute("sentence", start, end, parse_.governing_verb(word)[1])
    for start, end, value, extras in fields.iter_money(text):
        word = parse_.head_of(start, end)
        if word is None:
            continue
        if sp.totals_row(text, start) and value != 0:
            continue  # a table cell has no grammar to read
        role = "not_case_amount" if extras.get("unit_price") or value == 0 else _money_role(parse_, word)
        out.append(assertion("money", value, role, method, VERSION, 0.8 if role else 0.5, start, end))
        attribute("money", start, end, parse_.governing_verb(word)[1])
    for start, end, value, _ in fields.iter_date(text):
        word = parse_.head_of(start, end)
        if word is None:
            continue
        role = _date_role(parse_, word)
        out.append(assertion("date", value, role, method, VERSION, 0.75 if role else 0.5, start, end))
    for start, end, kind, _ in fields.iter_event(text):
        if not parse_.inside(start, end):
            continue
        role, verb = _event_role(parse_, doc, start, end, kind)
        out.append(assertion("event", kind, role, method, VERSION, 0.8 if role else 0.5, start, end))
        attribute("event", start, end, verb)
    spans = {(start, end) for start, end, _ in names.iter_people(text)}
    spans |= {(start, end) for start, end, kind in parse_.entities if kind == "PERSON" and names.is_name(text[start:end])}
    for start, end in sorted(spans):
        if parse_.inside(start, end):
            role = _party_role(parse_, start, end)
            out.append(assertion("party", None, role, method, VERSION, 0.8 if role else 0.5, start, end))
    return out


def read_ner(doc: Doc) -> list[dict[str, Any]]:
    if not enabled():
        return []
    parse_ = parse(doc)
    text, method, out = doc.text, "ner_model", []
    for start, end, kind in parse_.entities:
        if kind == "PERSON" and names.is_name(text[start:end]):
            # A person is named here. Who they are in the case is not an entity type.
            out.append(assertion("party", None, None, method, VERSION, 0.5, start, end, entity="PERSON"))
    for start, end, hint in names.iter_people(text):
        if hint != "person":
            continue  # the phrasing itself says who this is; an entity type does not outweigh it
        over = [(min(end, e) - max(start, s), kind) for s, e, kind in parse_.entities if s < end and e > start]
        if not over or any(kind == "PERSON" for _, kind in over):
            continue
        covered, kind = max(over)
        # The model was trained on mixed-case text and types names in capitals poorly.
        if kind in ("ORG", "GPE", "LOC", "FAC", "NORP") and covered * 10 >= (end - start) * 6 and not text[start:end].isupper():
            out.append(assertion("party", None, "not_person", method, VERSION, 0.8, start, end, entity=kind))
    return out


register_reader("dependency", ("press", "court"), read_dependency, version=VERSION if enabled() else "off", order=35)
register_reader("ner", ("press", "court"), read_ner, version=VERSION if enabled() else "off", order=36)
