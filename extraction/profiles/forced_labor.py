"""Forced labor and labor trafficking: scheme types."""

from extraction.profiles import Profile

PROFILE = Profile(
    name="forced_labor",
    domains=("forced_labor",),
    scheme={
        "forced_labor": r"forced\s+labor|labor\s+trafficking|compelled\s+(?:\w+\s+){0,3}(?:to\s+work|labor)|involuntary\s+servitude|peonage",
        "domestic_servitude": r"domestic\s+(?:servitude|servant|worker)s?|nann(?:y|ies)|housekeepers?|live[-\s]in\s+(?:maid|servant)",
        "debt_bondage": r"debt\s+bondage|smuggling\s+debts?|recruitment\s+(?:fees?|debts?)|pay\s+off\s+(?:a\s+|the\s+|their\s+)?debts?",
        "document_confiscation": r"confiscat\w+\s+(?:\w+\s+){0,3}(?:passports?|documents?|visas?)|(?:took|held|kept|withheld|seized)\s+(?:\w+\s+){0,3}(?:passports?|identification|immigration\s+documents?)|document\s+servitude",
        "visa_fraud": r"visa\s+fraud|H-2[AB]|fraudulent\s+visas?|B-1\s+visa|J-1\s+visa",
        "wage_theft": r"(?:little|no)\s+(?:or\s+no\s+)?pay|unpaid\s+(?:wages|labor)|without\s+pay|withheld\s+(?:\w+\s+){0,2}(?:wages|pay)",
        "threat_of_deportation": r"threat\w*\s+(?:of|to)\s+(?:deport\w+|report\w*\s+(?:\w+\s+){0,3}to\s+immigration)|immigration\s+status",
        "physical_restraint": r"lock(?:ed|ing)\s+(?:\w+\s+){0,3}(?:in|inside)|not\s+allowed\s+to\s+leave|physical(?:ly)?\s+(?:abus\w+|restrain\w+)|isolat\w+",
        "labor_recruitment_fraud": r"false\s+promises?|promis\w+\s+(?:of\s+)?(?:\w+\s+){0,3}(?:jobs?|wages|education|schooling|better\s+life)|recruit(?:ed|ing|ment)",
        "agriculture": r"farm\s?workers?|agricultur\w+|harvest\w*|fields",
        "restaurant_hospitality": r"restaurants?|hotels?|motels?|buffets?",
    },
)
