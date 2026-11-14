"""Child sexual exploitation and abuse: scheme types.

The field-level readers CaseLinker built for this domain (victim and offender
ages, with their own gate) are not ported. This profile carries the topic
labels only.
"""

from extraction.profiles import Profile

PROFILE = Profile(
    name="csea",
    domains=("csea",),
    scheme={
        "production": r"produc(?:ed|ing|tion)\s+(?:of\s+)?(?:child\s+pornography|child\s+sexual\s+abuse\s+material|CSAM|sexually\s+explicit\s+(?:images|videos|material))",
        "distribution": r"distribut(?:ed|ing|ion)\s+(?:of\s+)?(?:child\s+pornography|child\s+sexual\s+abuse\s+material|CSAM)",
        "possession": r"possess(?:ed|ing|ion)\s+(?:of\s+)?(?:child\s+pornography|child\s+sexual\s+abuse\s+material|CSAM)",
        "receipt": r"recei(?:ved|ving|pt)\s+(?:of\s+)?(?:child\s+pornography|child\s+sexual\s+abuse\s+material|CSAM)",
        "enticement": r"entic(?:ed|ing|ement)|coercion\s+and\s+enticement|groom(?:ed|ing)",
        "sextortion": r"sextortion|threatened\s+to\s+(?:share|post|send|release)\s+(?:\w+\s+){0,4}(?:images|photos|videos)",
        "travel": r"travel(?:ed|ing)?\s+(?:\w+\s+){0,6}to\s+engage\s+in\s+(?:illicit\s+)?sex\w*",
        "undercover_operation": r"undercover\s+(?:officer|agent|operation|investigator|detective)|posing\s+as\s+a\s+(?:minor|child|\d{1,2}[-\s]year[-\s]old)",
        "ai_generated": r"AI[-\s]generated|artificial\s+intelligence|deepfakes?|morphed\s+images",
        "hands_on": r"sexual(?:ly)?\s+(?:abus\w+|assault\w*)|molest\w+|hands[-\s]on",
    },
)
