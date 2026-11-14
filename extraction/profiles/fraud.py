"""Fraud: scheme types. Covers the classic, cyber, investment, elder, and
online collector buckets."""

from extraction.profiles import Profile

PROFILE = Profile(
    name="fraud",
    domains=("fraud",),
    scheme={
        "romance": r"romance\s+(?:scams?|fraud|schemes?)|online\s+romance|romantic\s+relationships?\s+with|sweetheart\s+scams?|catfish\w*",
        "investment": r"investment\s+(?:fraud|scams?|schemes?)|defraud\w*\s+investors|fraudulent\s+investments?|investor\s+fraud",
        "ponzi": r"Ponzi(?:[-\s]like)?(?:\s+scheme)?|pyramid\s+scheme",
        "crypto_investment": r"pig[-\s]butchering|crypto(?:currency)?\s+investment\s+(?:fraud|scams?|schemes?)|fake\s+(?:crypto(?:currency)?\s+)?(?:trading|investment)\s+platforms?",
        "business_email_compromise": r"business\s+e-?mail\s+compromise|BEC\s+(?:scheme|scam|fraud)|e-?mail\s+compromise",
        "tech_support": r"tech(?:nical)?[-\s]support\s+(?:scams?|fraud|schemes?)|fake\s+(?:virus|computer|security)\s+(?:alerts?|warnings?|pop[-\s]?ups?)",
        "government_imposter": r"(?:government|IRS|Social\s+Security|law\s+enforcement|federal\s+agent|FBI|police)\s+(?:imposter|impersonat\w+)|impersonat\w+\s+(?:an?\s+)?(?:government|federal|IRS|FBI|law\s+enforcement|police|Social\s+Security|bank)\s+(?:official|agent|officer|employee)s?|posing\s+as\s+(?:an?\s+)?(?:government|federal|IRS|FBI|law\s+enforcement|bank)\s+\w+",
        "grandparent": r"grandparent\s+(?:scams?|fraud|schemes?)|pos(?:ed|ing)\s+as\s+(?:a\s+|their\s+|the\s+victims?'?s?\s+)?grand(?:child|son|daughter)\w*",
        "lottery_sweepstakes": r"lottery\s+(?:scams?|fraud|schemes?)|sweepstakes|prize\s+(?:scams?|winnings)|won\s+a\s+(?:lottery|prize)",
        "elder_fraud": r"elder\s+(?:fraud|abuse|exploitation|financial)|elderly\s+victims?|older\s+(?:adults|Americans|victims)|senior\s+citizens?|seniors",
        "health_care_fraud": r"health\s*care\s+fraud|Medicare\s+fraud|Medicaid\s+fraud|billed\s+(?:Medicare|Medicaid)|false\s+claims\s+to\s+(?:Medicare|Medicaid)|kickbacks?",
        "pandemic_relief": r"Paycheck\s+Protection\s+Program|PPP\s+loans?|Economic\s+Injury\s+Disaster|EIDL|COVID(?:-19)?\s+relief|pandemic\s+(?:relief|unemployment)|CARES\s+Act",
        "unemployment_insurance": r"unemployment\s+(?:insurance|benefits?)\s+(?:fraud|claims?)",
        "identity_theft": r"identity\s+theft|stolen\s+identit(?:y|ies)|stole\s+the\s+identit(?:y|ies)|personal\s+identif\w+\s+information",
        "bank_fraud": r"bank\s+fraud|check\s+(?:kiting|fraud)|counterfeit\s+checks?|stolen\s+checks?|check[-\s]washing",
        "credit_card": r"credit\s+card\s+(?:fraud|scheme)|stolen\s+credit\s+cards?|card\s+skimm\w+|skimming\s+devices?|access\s+device\s+fraud",
        "mortgage": r"mortgage\s+fraud|loan\s+modification\s+(?:scam|fraud)|foreclosure\s+(?:rescue|scam)",
        "tax": r"tax\s+(?:fraud|evasion|refund\s+fraud)|false\s+tax\s+returns?",
        "telemarketing": r"telemarketing\s+(?:fraud|scheme|scam)|boiler\s+room",
        "embezzlement": r"embezzl\w+|misappropriat\w+\s+(?:funds|money|client)",
        "money_mule": r"money\s+mules?|mule\s+accounts?",
        "account_takeover": r"account\s+takeovers?|SIM[-\s]swap\w*|took\s+over\s+(?:the\s+)?(?:victims?'?s?\s+)?accounts?",
        "advance_fee": r"advance[-\s]fee|upfront\s+fees?|fees?\s+(?:in\s+advance|up\s?front)",
        "charity": r"charity\s+(?:fraud|scam)|fake\s+charit(?:y|ies)|sham\s+charit(?:y|ies)",
        "employment": r"(?:job|employment|work[-\s]from[-\s]home)\s+(?:scams?|fraud|offers?\s+scam)|fake\s+job",
        "insurance": r"insurance\s+fraud|staged\s+(?:accidents?|collisions?)",
        "securities": r"securities\s+fraud|insider\s+trading|pump[-\s]and[-\s]dump|market\s+manipulation",
        "procurement": r"procurement\s+fraud|bid[-\s]rigging|government\s+contracts?\s+fraud|defraud\w*\s+the\s+(?:Department|government|United\s+States)",
        "extortion": r"extort\w+|sextortion|blackmail\w*",
    },
    buckets={"elder": "elder_fraud", "investment": "investment"},
)
