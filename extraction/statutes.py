"""Statute table: U.S. Code section -> offense label, the words a record uses
for it, and the first-offense statutory maximum in months.

Two readers use it. The lookup reader turns a citation into an offense label.
The pattern reader turns the offense's name into the same label. When both
fire, two families agree on the offense.

`max_months` is the base statutory maximum for one count. `None` means the
maximum depends on the subsection or the facts, and the lookup reader then
makes no claim about exposure. `min_months` is a mandatory minimum where the
base offense carries one. These are reading aids for telling "faces 20 years"
from "sentenced to 20 years". They are not legal advice.
"""

from __future__ import annotations

import re
from typing import NamedTuple

TABLE_VERSION = "usc_offenses_2026_11"


class Statute(NamedTuple):
    label: str
    words: str  # regex for the offense named in words; "" when no stable name
    max_months: int | None = None
    min_months: int | None = None
    life: bool = False


LIFE = dict(max_months=None, life=True)

STATUTES: dict[tuple[str, str], Statute] = {
    # Fraud
    ("18", "1343"): Statute("wire_fraud", r"wire\s+fraud", 240),
    ("18", "1341"): Statute("mail_fraud", r"mail\s+fraud", 240),
    ("18", "1344"): Statute("bank_fraud", r"bank\s+fraud", 360),
    ("18", "1349"): Statute("fraud_conspiracy", r"conspir\w+\s+to\s+commit\s+(?:wire|mail|bank|health\s+care|securities)\s+fraud"),
    ("18", "1347"): Statute("health_care_fraud", r"health\s*care\s+fraud", 120),
    ("18", "1348"): Statute("securities_fraud", r"securities\s+fraud", 300),
    ("15", "78J"): Statute("securities_fraud", r"securities\s+fraud", 240),
    ("18", "1028A"): Statute("aggravated_identity_theft", r"aggravated\s+identity\s+theft", 24, 24),
    ("18", "1028"): Statute("identity_fraud", r"identity\s+(?:theft|fraud)"),
    ("18", "1029"): Statute("access_device_fraud", r"access\s+device\s+fraud"),
    ("18", "1030"): Statute("computer_fraud", r"computer\s+(?:fraud|intrusion|hacking)|unauthorized\s+access\s+to\s+a\s+(?:protected\s+)?computer"),
    ("18", "1956"): Statute("money_laundering", r"money\s+laundering|launder(?:ing|ed)\s+(?:the\s+)?(?:money|proceeds|funds)", 240),
    ("18", "1957"): Statute("money_laundering", r"money\s+laundering", 120),
    ("18", "1960"): Statute("unlicensed_money_transmitting", r"unlicensed\s+money\s+transmitting", 60),
    ("18", "371"): Statute("conspiracy", r"conspiracy\s+to\s+defraud\s+the\s+United\s+States", 60),
    ("18", "287"): Statute("false_claims", r"false(?:,\s+fictitious)?\s+(?:or\s+fraudulent\s+)?claims", 60),
    ("18", "641"): Statute("theft_of_government_property", r"theft\s+of\s+(?:government|public)\s+(?:property|money|funds)", 120),
    ("18", "1001"): Statute("false_statements", r"(?:making\s+)?false\s+statements?", 60),
    ("18", "1014"): Statute("false_loan_statement", r"false\s+statements?\s+(?:on|to|in)\s+(?:a\s+)?(?:loan|bank|financial)", 360),
    ("18", "1040"): Statute("disaster_fraud", r"disaster(?:\s+relief)?\s+fraud", 360),
    ("18", "1035"): Statute("health_care_false_statements", "", 60),
    ("18", "2314"): Statute("interstate_transport_stolen_property", r"interstate\s+transportation\s+of\s+stolen", 120),
    ("26", "7201"): Statute("tax_evasion", r"tax\s+evasion", 60),
    ("26", "7206"): Statute("false_tax_return", r"false\s+tax\s+returns?", 36),
    ("31", "5324"): Statute("structuring", r"structuring", 60),
    ("42", "1320A-7B"): Statute("anti_kickback", r"kickbacks?", 120),
    # Trafficking and forced labor
    ("18", "1591"): Statute("sex_trafficking", r"sex\s+trafficking", min_months=120, **LIFE),
    ("18", "1589"): Statute("forced_labor", r"forced\s+labor", 240),
    ("18", "1590"): Statute("labor_trafficking", r"(?:labor\s+trafficking|trafficking\s+(?:with\s+respect\s+to|for)\s+(?:peonage|forced\s+labor))", 240),
    ("18", "1592"): Statute("document_servitude", r"document\s+servitude", 60),
    ("18", "1594"): Statute("trafficking_conspiracy", r"conspir\w+\s+to\s+commit\s+(?:sex|labor)\s+trafficking"),
    ("18", "1581"): Statute("peonage", r"peonage", 240),
    ("18", "1584"): Statute("involuntary_servitude", r"involuntary\s+servitude", 240),
    ("18", "2421"): Statute("interstate_transport_for_prostitution", r"Mann\s+Act|transport\w*\s+(?:\w+\s+){0,4}for\s+(?:purposes\s+of\s+)?prostitution", 120),
    ("18", "1952"): Statute("travel_act", r"Travel\s+Act", 60),
    ("8", "1324"): Statute("alien_harboring", r"harboring\s+(?:illegal\s+|undocumented\s+)?(?:aliens|noncitizens)"),
    ("18", "1546"): Statute("visa_fraud", r"visa\s+fraud", 120),
    # Child exploitation (bounds carried over from CaseLinker's lookup)
    ("18", "2251"): Statute("csam_production", r"production\s+of\s+child\s+(?:pornography|sexual\s+abuse\s+material)", 360, 180),
    ("18", "2252"): Statute("csam_receipt_distribution", r"(?:receipt|distribution)\s+of\s+child\s+(?:pornography|sexual\s+abuse\s+material)", 240, 60),
    ("18", "2252A"): Statute("csam_receipt_distribution", r"(?:receipt|distribution)\s+of\s+child\s+(?:pornography|sexual\s+abuse\s+material)", 240, 60),
    ("18", "2422"): Statute("coercion_and_enticement", r"(?:coercion\s+and\s+)?enticement\s+of\s+a\s+minor", min_months=120, **LIFE),
    ("18", "2423"): Statute("transportation_of_minor", r"transportation\s+of\s+(?:a\s+)?minors?", min_months=120, **LIFE),
    # Cyber, extortion, racketeering
    ("18", "875"): Statute("interstate_threats_extortion", r"(?:cyber\s*)?extortion|interstate\s+(?:threats|communications)"),
    ("18", "1951"): Statute("hobbs_act", r"Hobbs\s+Act", 240),
    ("18", "1962"): Statute("racketeering", r"racketeering|RICO", 240),
    ("18", "2261A"): Statute("cyberstalking", r"cyber\s*stalking|stalking", 60),
    ("18", "2511"): Statute("wiretapping", r"(?:illegal\s+)?wiretapping|intercept\w+\s+(?:of\s+)?communications", 60),
    ("18", "1512"): Statute("obstruction", r"witness\s+tampering|obstruction\s+of\s+justice"),
}

OFFENSE_LABELS: tuple[str, ...] = tuple(sorted({item.label for item in STATUTES.values()}))

OFFENSE_WORDS: dict[str, re.Pattern[str]] = {}
for _item in STATUTES.values():
    if _item.words and _item.label not in OFFENSE_WORDS:
        OFFENSE_WORDS[_item.label] = re.compile(rf"\b(?:{_item.words})\b", re.IGNORECASE)


def lookup(title: str, section: str) -> Statute | None:
    return STATUTES.get((str(int(title)), section.upper()))
