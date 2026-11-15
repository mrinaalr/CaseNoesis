"""Conduct: the kinds of act an offense is made of, and the words that report them.

A statement of offense, a factual basis, or an agent's affidavit tells what
was done as a series of acts: an account was opened, a victim was contacted,
money was demanded, sent, and moved. The kinds here are deliberately few and
are not tied to one offense. A romance scam, a ransomware attack and a
trafficking case each use a different subset, and that difference is what a
comparison across offense types needs.

    setup        prepared the means: opened an account, registered a domain or a company
    contact      reached a person: messaged, called, approached, met
    deception    said or submitted something false: posed as, misrepresented, forged
    demand       asked for or required something of value
    threat       threatened harm, exposure, arrest or deportation
    transfer     value passed from the person harmed: wired, paid, sent, deposited. The payer must
                 be the person harmed; see `settle`
    movement     the offender moved or changed the value: laundered, withdrew, converted, or wired
                 or deposited it themselves
    access       got into a computer or an account without authority; deployed or ran code on it
    recruit      drew a person in: recruited, enticed, lured, groomed
    transport    moved a person or travelled to one
    control      held a person: took documents, confined, assaulted, coerced
    exploit      used the person: commercial sex, compelled labor, produced or traded abuse material
    supply       sold, shipped or delivered contraband or a weapon, and the buyer's payment for it
    concealment  hid the act afterwards: deleted, destroyed, lied to investigators
    detection    what investigators did: an undercover contact, a search, a seizure

Two readers classify each trigger and vote. The pattern reader goes by the
verb. The clause reader goes by what the verb acts on. "Sent" is a contact
when a message follows and a transfer when an amount does; the two readers
agree only where the verb and its object point the same way. Where the verb
alone says what was done ("threatened", "laundered"), the clause reader
abstains. `not_conduct`
is for a trigger inside a recital of what a statute requires or allows,
which uses the same verbs and reports no act.
"""

from __future__ import annotations

import re

KINDS = ("setup", "contact", "deception", "demand", "threat", "transfer", "movement", "access", "recruit",
         "transport", "control", "exploit", "supply", "concealment", "detection")

# The same acts one level up: where each falls in the course of an offense. This is the
# stage structure of a crime script (Cornish, 1994), kept to five stages so that offenses
# of different kinds can be laid side by side. It agrees with the roles the state machine
# gives each act: entering a system is an approach, as contacting a person is; moving a
# person is leverage over them.
PHASE = {
    "setup": "preparation",
    "contact": "approach", "recruit": "approach",
    "deception": "leverage", "demand": "leverage", "threat": "leverage", "control": "leverage",
    "access": "approach",
    "transport": "leverage",
    "transfer": "harm", "exploit": "harm", "supply": "harm",
    "movement": "exit", "concealment": "exit",
    "detection": "detection",
}
PHASES = ("preparation", "approach", "leverage", "harm", "exit", "detection")

# Who a demand or an instruction is addressed to: a pronoun, "the victim", or a short label
# such as "Victim-1" or "Company A". Never more than three words, so a name cannot hide a clause.
_WHOM = r"(?:[\w'’.-]+\s+){1,3}?"

# Verb phrases, by kind. Order matters where one phrase contains another: the first kind listed wins.
_VERBS: tuple[tuple[str, str], ...] = (
    ("detection", r"executed\s+a\s+(?:federal\s+)?search\s+warrant|seized|intercepted|conducted\s+(?:a\s+)?(?:controlled|undercover)|"
                  r"acting\s+in\s+an\s+undercover\s+capacity|posing\s+as\s+a\s+(?:minor|child|\d{1,2}[-\s]year[-\s]old)|reported\s+(?:the\s+\w+\s+)?to\s+(?:the\s+)?(?:FBI|police|law\s+enforcement|bank)"),
    ("concealment", r"deleted|destroyed|wiped|concealed|disguised|lied\s+to|falsely\s+told\s+(?:agents|investigators|law\s+enforcement)"),
    ("deception", r"posed\s+as|pretended\s+to\s+be|claimed\s+to\s+be|impersonated|falsely\s+(?:stated|represented|claimed|told|promised|certified)|"
                  r"misrepresented|fabricated|forged|falsified|submitted\s+(?:a\s+|an\s+|\w+\s+)?(?:false|fraudulent|fictitious)|created\s+(?:a\s+)?(?:fake|false|fraudulent)"),
    ("threat", r"threatened|warned\s+(?:her|him|them|the\s+victims?)\s+that"),
    ("demand", r"demanded|requested\s+(?:that|payment|money)|asked\s+" + _WHOM + r"to\s+(?:send|pay|wire|transfer|buy|purchase)|"
               r"instructed\s+" + _WHOM + r"to|directed\s+" + _WHOM + r"to"),
    ("movement", r"laundered|withdrew|converted|cashed\s+out|structured|moved\s+the\s+(?:funds|money|proceeds)|transferred\s+the\s+(?:funds|money|proceeds)|"
                 r"wired\s+the\s+(?:funds|money|proceeds)|dissipated|spent\s+the\s+(?:funds|money|proceeds)"),
    ("transfer", r"wired|(?<!was\s)(?<!were\s)(?<!been\s)(?<!be\s)(?<!being\s)(?<!not\s)(?<!never\s)(?<![-\w])paid(?=\s+[\w$])(?!\s+(?:sick|family|leave|time|vacation|holiday|out\b))|sent\s+(?:approximately\s+|about\s+|more\s+than\s+|a\s+total\s+of\s+)?\$|transferred\s+(?:approximately\s+|about\s+)?\$|deposited|mailed\s+(?:cash|a\s+check|checks)|"
                 r"purchased\s+(?:\w+\s+)?gift\s+cards|lost\s+(?:approximately\s+|about\s+)?\$"),
    ("access", r"accessed|logged\s+in(?:to)?|hacked|breached|gained\s+(?:unauthorized\s+)?access|deployed|installed|encrypted|exfiltrated|compromised"),
    ("exploit", r"caused\s+" + _WHOM + r"to\s+engage|engaged\s+in\s+(?:a\s+)?commercial\s+sex|posted\s+(?:online\s+)?advertisements?|advertised|"
                r"produced|received\s+(?:and\s+possessed\s+)?(?:child|images|videos|files)|distributed\s+(?:child|images|videos|files)|required\s+" + _WHOM + r"to\s+work|"
                r"compelled|kept\s+the\s+(?:money|proceeds|earnings)"),
    ("control", r"confiscated|took\s+(?:her|his|their|the\s+\w+['’]s)\s+(?:passports?|phones?|identification|documents)|"
                r"withheld\s+(?:her|his|their|the\s+\w+['’]s)\s+(?:pay|wages|passports?|documents|identification)|locked\s+(?:her|him|them|the\s+\w+)\s+in|confined|"
                r"beat\s+(?:her|him|them|the\s+victims?)|assaulted|forced|coerced|isolated"),
    ("transport", r"transported|drove|travel(?:ed|led)|flew|brought\s+" + _WHOM + r"to|smuggled"),
    ("recruit", r"recruited|enticed|lured|persuaded|induced|groomed|solicited"),
    ("supply", r"sold|shipped|delivered|supplied|distributed|dispensed|exported|trafficked"),
    ("contact", r"contacted|messaged|e-?mailed|texted|called\s+(?:the\s+)?(?:victims?|her|him|them|individuals|people|customers|residents|seniors)|telephoned|approached|met\s+(?:with\s+)?(?:her|him|them|the\s+victims?|a\s+\w+)|began\s+communicating|"
                r"initiated\s+contact|sent\s+(?:a\s+|an\s+|several\s+|numerous\s+|\w+\s+)?(?:messages?|e-?mails?|texts?|letters?|friend\s+requests?)|communicated\s+with|responded\s+to"),
    ("setup", r"created|registered|opened|set\s+up|established|incorporated|rented|leased|obtained|acquired|purchased|recruited\s+money\s+mules"),
)
VERBS: tuple[tuple[str, re.Pattern[str]], ...] = tuple((kind, re.compile(rf"\b(?:{pattern})", re.IGNORECASE)) for kind, pattern in _VERBS)
TRIGGER = re.compile("|".join(f"(?:\\b(?:{pattern}))" for _, pattern in _VERBS), re.IGNORECASE)

# What the verb acts on, by kind. Read from the words after the trigger, inside its clause.
OBJECTS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (kind, re.compile(pattern, re.IGNORECASE))
    for kind, pattern in (
        ("detection", r"\bsearch\s+warrant\b|\bundercover\b|\bagents?\b|\bofficers?\b|\blaw\s+enforcement\b|\bseiz\w+\b"),
        ("concealment", r"\bevidence\b|\brecords\b|\bmessages\s+(?:from|on)\s+(?:his|her|their)\b|\binvestigators\b|\bto\s+avoid\s+detection\b"),
        ("movement", r"\bproceeds\b|\bthe\s+(?:funds|money)\b|\b(?:into|to)\s+(?:cryptocurrency|bitcoin|cash)\b|\bshell\s+compan\w+\b|\boverseas\s+accounts?\b|\bmule\b"),
        ("transfer", r"\$\s?\d|\bgift\s+cards?\b|\bsavings\b|\bpayments?\b|\bransom\b|\bwire\s+transfers?\b"),
        ("deception", r"\bfalse\w*\b|\bfraudulent\w*\b|\bfake\b|\bfictitious\b|\bposed\b|\bpretend\w*\b|\bimpersonat\w+\b|\bnonexistent\b|\bdid\s+not\s+exist\b"),
        ("threat", r"\bthreat\w*\b|\bharm\b|\bkill\b|\bexpose\b|\barrest(?:ed)?\s+unless\b|\bdeport\w*\b|\bpublish\b|\brelease\s+the\s+(?:images|photos|videos)\b"),
        ("exploit", r"\bcommercial\s+sex\b|\bsex\s+acts?\b|\badvertisements?\b|\bchild\s+(?:pornography|sexual\s+abuse\s+material)\b|\bsexually\s+explicit\b|\bto\s+work\b|\bwithout\s+pay\b|\bearnings\b"),
        ("control", r"\bpassports?\b|\bidentification\b|\bimmigration\s+documents?\b|\bnot\s+allowed\s+to\s+leave\b|\bdebts?\b|\bphysical\w*\b"),
        ("access", r"\bcomputers?\b|\bnetworks?\b|\bservers?\b|\bransomware\b|\bmalware\b|\be-?mail\s+accounts?\s+of\b|\bwithout\s+authorization\b|\bfiles\b"),
        ("supply", r"\bfentanyl\b|\bmethamphetamine\b|\bcocaine\b|\bheroin\b|\bpills\b|\bfirearms?\b|\bpistols?\b|\brifles?\b|\bmachineguns?\b|\bkilograms?\b|\bgrams\b|\bcontrolled\s+substances?\b"),
        ("transport", r"\bacross\s+state\s+lines\b|\bto\s+(?:a\s+)?(?:hotel|motel|residence|apartment)\b|\bfrom\s+\w+\s+to\s+\w+\b|\binto\s+the\s+United\s+States\b|\bairport\b"),
        ("recruit", r"\bpromis\w+\b|\bjobs?\b|\bemployment\b|\bmodeling\b|\ba\s+better\s+life\b|\bminor\b|\bto\s+meet\b"),
        ("demand", r"\bto\s+(?:send|pay|wire|transfer|buy|purchase)\b|\bfees?\b|\btaxes\b|\bcustoms\b|\bbail\b"),
        ("contact", r"\bmessages?\b|\be-?mails?\b|\bphone\b|\btelephone\b|\bsocial\s+media\b|\bdating\b|\bprofile\s+of\b|\bWhatsApp\b|\bTelegram\b|\bSnapchat\b|\bFacebook\b|\bInstagram\b"),
        ("setup", r"\baccounts?\b|\bprofiles?\b|\bdomains?\b|\bcompan(?:y|ies)\b|\bLLC\b|\bcorporations?\b|\bentit(?:y|ies)\b|\bwebsites?\b|\bSIM\b|\bphones?\b|"
              r"\bmailbox(?:es)?\b|\bP\.?O\.?\s+box(?:es)?\b|\bcredentials\b|\bidentities\b|\bskimm\w+\b|\bdevices?\b|\bsoftware\b|\bequipment\b"),
    )
)

# Verbs too general to name an act: "obtained a loan", "obtained a phone", "the agency created a
# list". Each counts only with an object that says what was done, read from the words after it.
GENERAL = re.compile(r"(?:obtained|acquired|purchased|created|established|opened|set\s+up|rented|leased|registered|incorporated)\b", re.IGNORECASE)
_TAKES_VALUE = re.compile(r"(?:obtained|acquired)\b", re.IGNORECASE)
SELLS = re.compile(r"(?:sold|shipped|delivered|supplied|distributed|dispensed|exported|trafficked)\b", re.IGNORECASE)
# "fraudulently obtained proceeds", "illegally-obtained checks": a description of a thing, not a report of an act.
_DESCRIBES = re.compile(r"^\s+(?!(?:a|an|the|his|her|their|its|more|over|approximately|about|at\s+least|nearly|\$|\d)\b)[a-z]+\b", re.IGNORECASE)
# The verbs of a statute in a row: "knowingly recruited, enticed, harbored, transported, or obtained".
VERB_LIST = re.compile(r"(?:\b\w+(?:ed|t),\s+){2,}(?:and\s+|or\s+)?\w+(?:ed|t)\b", re.IGNORECASE)
REACH = 90

# Verbs whose kind depends on what they act on. The clause reader votes on these and
# abstains on the rest, where the verb alone says what was done.
AMBIGUOUS = re.compile(
    r"(?:sent|transferred|received|paid|deposited|forced|produced|accessed|installed|converted)\b",
    re.IGNORECASE,
)

# A recital of what a statute requires or allows, or of what a party promises: the verbs of conduct, and no act.
RECITAL = re.compile(
    r"\belements?\s+of\s+the\s+offense\b|\bmust\s+prove\b|\bwould\s+have\s+to\s+prove\b|\bbeyond\s+a\s+reasonable\s+doubt\b|\bwhoever\b|"
    r"\bmaximum\s+(?:penalty|sentence|term)\b|\bpunishable\b|\bdefendant\s+(?:understands|agrees|acknowledges|waives)\b|\bshall\s+be\s+(?:fined|imprisoned)\b|"
    r"\bin\s+violation\s+of\s+Title\b|\bpresumed\s+innocent\b|\bif\s+convicted\b|\bthe\s+government\s+agrees\b|\bthe\s+United\s+States\s+agrees\b",
    re.IGNORECASE,
)


def by_verb(trigger: str, after: str, before: str = "") -> str | None:
    """The kind a trigger's own words name. `after` and `before` are the text around it.

    A general verb names an act only through its object: something set up
    (an account, a company), or value taken. A verb of selling names a supply
    only when what is sold is contraband or a weapon."""
    if GENERAL.match(trigger):
        if re.search(r"ly[-\s]$", before) and _DESCRIBES.match(after):
            return None
        found = by_object(after[:REACH])
        if found == "setup":
            return "setup"
        if found in ("transfer", "movement"):
            if _TAKES_VALUE.match(trigger):
                return "transfer"
            # "purchased gift cards worth $9,000": the purchase is how the value leaves the payer.
            return "transfer" if re.match(r"purchased\s+(?:\w+\s+)?gift\s+cards", trigger + after[:30], re.IGNORECASE) else None
        return None
    if SELLS.match(trigger) and not re.match(r"distributed\s+(?:child|images|videos|files)", trigger + after[:20], re.IGNORECASE):
        return "supply" if by_object(after[:REACH]) == "supply" else None
    probe = trigger + after[:40]
    for kind, pattern in VERBS:
        if pattern.match(probe):
            return kind
    return None


def in_verb_list(sentence: str, start: int, end: int) -> bool:
    """True when the trigger at `[start, end)` of `sentence` is one of a row of statutory verbs."""
    return any(match.start() <= start and end <= match.end() for match in VERB_LIST.finditer(sentence))


def by_object(after: str) -> str | None:
    """The kind the words after a trigger point to, nearest cue first."""
    best: tuple[int, str] | None = None
    for kind, pattern in OBJECTS:
        match = pattern.search(after)
        if match and (best is None or match.start() < best[0]):
            best = (match.start(), kind)
    return best[1] if best else None


# Who paid, read from the words before a transfer verb in its clause.
_VICTIM = re.compile(
    r"\bvictims?\b|\bV-?\d+\b|\bVictim[-\s]\w+|\bCompany\s+[A-Z0-9]\b|\binvestors?\b|\blenders?\b|\bthe\s+lender\b|\bclients?\b|"
    r"\bpatients?\b|\bthe\s+banks?\b|\binsurers?\b|\bthe\s+(?:company|business|employer|program|agency)\b|\bresidents?\b|"
    r"\bseniors?\b|\belderly\b|\bwidow\b|\bfamil(?:y|ies)\b|\bminors?\b|\bdonors?\b|\bhomeowners?\b|\bpolicyholders?\b|"
    # Institutions a fraud takes from: health programs, tax and loan agencies, banks, insurers, governments.
    r"\bMedicare\b|\bMedicaid\b|\bTRICARE\b|\bMedi-Cal\b|\bIRS\b|\bInternal\s+Revenue\s+Service\b|\bSBA\b|\bSmall\s+Business\s+Administration\b|"
    r"\bprograms?\b|\bplans?\b|\binsurance\s+compan(?:y|ies)\b|\binsurers?\b|\bcarriers?\b|\b[A-Z][\w&.]*\s+(?:Bank|Insurance|Mutual|Credit\s+Union)\b|"
    r"\bwomen\b|\bmen\b|\bpeople\b|\bparents\b|\bborrowers\b|\bpersons\b|\bindividuals\b|\bconsumers\b|\bstudents\b|\bemployees\b|\bmembers\b|\bstrangers\b|"
    r"\b(?:hospital|medical\s+center|school|university|charity|church|union)\b|"
    r"\bbanks?\b|\bthe\s+(?:government|United\s+States|state|county|city|Department|Treasury|VA)\b|\bstate\s+agenc(?:y|ies)\b|\bpayors?\b|\bpayers?\b",
    re.IGNORECASE)
_BUYER = re.compile(r"\bbuyers?\b|\bpurchasers?\b|\bthe\s+CS\b|\bCHS\b|\bthe\s+CI\b|\bconfidential\s+(?:source|informant)s?\b|\bundercover\b|\bthe\s+UC\b", re.IGNORECASE)
_OFFENDER = re.compile(r"\b(?:defendants?|co-?defendants?|co-?conspirators?|conspirators|marketers|recruiters|he|she|they|his\s+\w+|her\s+\w+)\s*$|\b[A-Z][A-Za-z'’-]+\s*$|\[name\]\s*$")
# Words between a subject and its verb: "Khan and the marketers in turn paid", "Brock also transferred".
_ADVERBS = re.compile(r"(?:\s+(?:also|then|in\s+turn|subsequently|allegedly|later|thereafter|knowingly|fraudulently|personally|directly|ultimately|again|each|wire|repeatedly|routinely|typically|often|would|had|have|has))+\s*$", re.IGNORECASE)
_CLAUSE_START = re.compile(r"(?:[.;:]|,\s+(?:and|then|after\s+which)\b|\band\s+then\b|\band\b|,)\s*")
_CAUSED = re.compile(r"\b(?:caused|induced|directed|instructed|told|persuaded|convinced|asked)\s+(?:\S+\s+){1,4}to\s*$", re.IGNORECASE)


def payer(before: str) -> str:
    """Who a transfer verb's subject is: `victim`, `buyer`, `offender` or `unknown`."""
    tail = _CLAUSE_START.split(before)[-1] if before else ""
    if _VICTIM.search(tail):  # "victim-buyers": the person harmed, whatever else they are called
        return "victim"
    if _BUYER.search(tail):
        return "buyer"
    if _CAUSED.search(before):
        return "victim"
    subject = _ADVERBS.sub("", " " + tail).strip()
    if subject and _OFFENDER.search(subject):
        return "offender"
    return "unknown"


def settle(kind: str | None, before: str, after: str) -> str | None:
    """A transfer, given who paid. Value passes from the person harmed only when they are the payer.

    A buyer's payment for contraband is part of the sale: `supply`. The offender wiring or depositing
    money is the offender moving it: `movement`. A transfer whose payer the clause does not name
    stays a transfer only when a person harmed is named before the verb."""
    if kind != "transfer":
        return kind
    who = payer(before)
    contraband = by_object(after[:REACH]) == "supply" or bool(re.search(r"\bfor\s+(?:the\s+|a\s+|an\s+)?(?:\w+\s+){0,3}(?:fentanyl|methamphetamine|cocaine|heroin|pills|firearms?|pistols?|rifles?|guns?|drugs)\b", after[:REACH], re.IGNORECASE))
    if who == "buyer" or (contraband and who != "victim"):
        return "supply"
    if who == "offender":
        return "movement"
    # The payer comes before the verb. A person harmed named only after it is who was paid: "paid the victims back".
    if who == "unknown" and not _VICTIM.search(before):
        return "movement"
    return "transfer"
