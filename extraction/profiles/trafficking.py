"""Sex trafficking: scheme types."""

from extraction.profiles import Profile

PROFILE = Profile(
    name="trafficking",
    domains=("trafficking",),
    scheme={
        "sex_trafficking": r"sex\s+trafficking|commercial\s+sex(?:\s+acts?)?|trafficked\s+(?:the\s+|a\s+|\w+\s+)?(?:victims?|women|girls?|minors?)",
        "minor_sex_trafficking": r"sex\s+trafficking\s+of\s+(?:a\s+)?(?:minors?|child(?:ren)?)|child\s+sex\s+trafficking|(?:minor|juvenile|underage)\s+victims?",
        "force_fraud_coercion": r"force,?\s+fraud,?\s+(?:and|or)\s+coercion|by\s+force|coerc\w+|threat(?:s|ened)\s+(?:of|to)\s+(?:violence|harm|kill)|beat(?:ing)?\s+(?:her|him|them|the\s+victims?)",
        "debt_bondage": r"debt\s+bondage|smuggling\s+debts?|owed\s+(?:a\s+|the\s+)?debts?|pay\s+off\s+(?:a\s+|the\s+|their\s+)?debts?",
        "online_advertising": r"(?:online|internet)\s+(?:advertisements?|ads)\s+(?:for|offering)|advertis\w+\s+(?:the\s+|her\s+|them\s+)?(?:victims?|for\s+(?:commercial\s+)?sex)|escort\s+(?:ads?|websites?|services?)",
        "interstate_transport": r"transport\w+\s+(?:\w+\s+){0,4}across\s+state\s+lines|interstate\s+(?:transportation|travel)|Mann\s+Act",
        "illicit_massage_business": r"(?:illicit\s+)?massage\s+(?:parlors?|business\w*|spas?)",
        "drug_dependency": r"(?:supplied|provid\w+|plied)\s+(?:\w+\s+){0,3}(?:with\s+)?(?:drugs|heroin|fentanyl|methamphetamine|narcotics)|drug\s+(?:addiction|dependen\w+)",
        "recruitment_deception": r"false\s+promises?|promis\w+\s+(?:of\s+)?(?:a\s+)?(?:jobs?|work|employment|modeling|better\s+life)|lured|recruit(?:ed|ing|ment)",
        "international": r"smuggl\w+|brought\s+(?:\w+\s+){0,3}(?:to|into)\s+the\s+United\s+States|transnational|from\s+(?:Mexico|China|Thailand|Honduras|Guatemala|the\s+Philippines)",
    },
)
