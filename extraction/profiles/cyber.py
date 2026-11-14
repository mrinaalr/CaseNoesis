"""Computer intrusion and cyber-enabled offenses: scheme types."""

from extraction.profiles import Profile

PROFILE = Profile(
    name="cyber",
    domains=("cyber",),
    scheme={
        "ransomware": r"ransomware|ransom\s+(?:payments?|demands?|notes?)",
        "intrusion": r"(?:computer|network)\s+intrusions?|hack(?:ed|ing|ers?)|unauthorized\s+access|breach(?:ed|es)?",
        "ddos": r"DDoS|denial[-\s]of[-\s]service|booter|stresser",
        "malware_distribution": r"malware|botnets?|trojans?|infostealers?|remote\s+access\s+trojans?",
        "phishing": r"phishing|spear[-\s]?phishing|credential\s+(?:theft|harvest\w+)|stolen\s+credentials",
        "sim_swapping": r"SIM[-\s]swap\w*",
        "darknet_market": r"dark\s?(?:web|net)\s+market(?:place)?s?|online\s+criminal\s+marketplace",
        "crypto_theft": r"(?:stole|theft\s+of|stolen)\s+(?:\w+\s+){0,3}(?:cryptocurrency|bitcoin|crypto)|drain(?:ed|ing)\s+(?:\w+\s+){0,3}wallets?",
        "money_laundering": r"launder\w+|mixers?|tumblers?|cryptocurrency\s+mixing",
        "business_email_compromise": r"business\s+e-?mail\s+compromise|BEC\s+(?:scheme|scam|fraud)",
        "data_theft": r"(?:stole|theft\s+of|stolen|exfiltrat\w+)\s+(?:\w+\s+){0,3}(?:data|records|trade\s+secrets|source\s+code|personal\s+information)",
        "cyberstalking": r"cyber\s*stalk\w+|online\s+harassment|doxx?\w+|swatting",
        "sextortion": r"sextortion|sexually\s+explicit\s+(?:images|photos|videos)\s+(?:unless|if)",
        "insider": r"insider\s+threat|former\s+employee|disgruntled\s+employee",
    },
)
