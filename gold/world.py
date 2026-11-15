"""The invented world the gold records are written from.

Every case here is made up: the people, the dockets, the amounts, the dates.
Districts, agencies and statutes are real, because a record that named a
fictional court would not have the shape of a real one. Nothing is taken from
a collected record.

`sample_case` draws one case from a seeded generator. The case is the ground
truth: who the defendants are, what each was charged with, what happened to
each and when, and what each was ordered to serve and pay. `gold.render`
writes documents from it and notes which of these facts each document states.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

GIVEN = (
    "Aldric Benno Calla Darien Elska Fenwick Greta Halden Imre Jorah Kessa Lorcan Marek Nadia Osric Petra Quillon Rhea "
    "Soren Talia Ulric Vesna Wendell Xenia Yorick Zelda Anton Brisa Caspian Delphine Emeric Farah Gideon Hesper Ivo Junia "
    "Kellan Livia Matthias Noor Orrin Pilar Rafferty Sabine Tobias Una Viktor Willa"
).split()
# Coined surnames: made up for this corpus so that no record names a real family.
# A match with a real person would be a coincidence.
SURNAMES = (
    "Vantrell Oskarby Quillfeather Brannoch Delvemarr-Oske Estravane Fallowmere Garrowick Hallovoss-Brin Ivernesse Jaskolt "
    "Kellenbrook Lumarre Marrowick Nettlestone Orlowe Pemberwick Quenbry Rookhaven Sallowfield Thornquill Underhaye "
    "Varnholt Wexcombe Yarrowgate Zellinor Ashgrovin Brackenmoor Corwynne Dunmarrow Eldermoss Farthingwell Greywether "
    "Hollowmere Inglesmoor Jessamoor Kirkbrae Larkspurr Mossgiel Northmere Oakenshaw Penhallick Quarrington Ravenscarr "
    "Silvermoss Tamsworth Umberfield Vexley Wintermoor Yewdale"
).split()
MIDDLE = "A B C D E F G H J K L M N P R S T W".split()

# (collector agency string, court name, dateline, state for "of City, State")
DISTRICTS = (
    ("USAO - Massachusetts", "District of Massachusetts", "BOSTON", "Massachusetts", ("Worcester", "Lowell", "Quincy", "Brockton")),
    ("USAO - New Jersey", "District of New Jersey", "NEWARK, N.J.", "New Jersey", ("Paterson", "Edison", "Camden", "Trenton")),
    ("USAO - Florida, Middle", "Middle District of Florida", "Tampa, Florida", "Florida", ("Lakeland", "Ocala", "Sarasota", "Clearwater")),
    ("USAO - Texas, Southern", "Southern District of Texas", "HOUSTON", "Texas", ("Pasadena", "Sugar Land", "Katy", "Galveston")),
    ("USAO - California, Central", "Central District of California", "LOS ANGELES", "California", ("Glendale", "Pomona", "Torrance", "Anaheim")),
    ("USAO - Illinois, Northern", "Northern District of Illinois", "CHICAGO", "Illinois", ("Aurora", "Joliet", "Naperville", "Evanston")),
    ("USAO - Georgia, Northern", "Northern District of Georgia", "ATLANTA", "Georgia", ("Marietta", "Decatur", "Roswell", "Smyrna")),
    ("USAO - Ohio, Southern", "Southern District of Ohio", "COLUMBUS, Ohio", "Ohio", ("Dayton", "Hilliard", "Dublin", "Lancaster")),
    ("USAO - Washington, Western", "Western District of Washington", "Seattle", "Washington", ("Tacoma", "Everett", "Kent", "Renton")),
    ("USAO - Pennsylvania, Eastern", "Eastern District of Pennsylvania", "PHILADELPHIA", "Pennsylvania", ("Chester", "Norristown", "Reading", "Bensalem")),
    ("USAO - Arizona", "District of Arizona", "PHOENIX", "Arizona", ("Mesa", "Tempe", "Glendale", "Chandler")),
    ("USAO - Missouri, Eastern", "Eastern District of Missouri", "ST. LOUIS", "Missouri", ("Florissant", "Chesterfield", "Ballwin", "Kirkwood")),
)

AGENCIES = {
    "fraud": ("the FBI", "the U.S. Postal Inspection Service", "IRS Criminal Investigation", "the U.S. Secret Service",
              "the Department of Health and Human Services Office of Inspector General", "Homeland Security Investigations"),
    "trafficking": ("Homeland Security Investigations", "the FBI"),
    "forced_labor": ("Homeland Security Investigations", "the Department of Labor Office of Inspector General", "the FBI"),
    "cyber": ("the FBI", "the U.S. Secret Service"),
    "csea": ("Homeland Security Investigations", "the FBI"),
}

# (title, section, name in words, offense label in the engine's statute table)
OFFENSES = {
    "wire_fraud": ("18", "1343", "wire fraud", "wire_fraud"),
    "mail_fraud": ("18", "1341", "mail fraud", "mail_fraud"),
    "bank_fraud": ("18", "1344", "bank fraud", "bank_fraud"),
    "wire_conspiracy": ("18", "1349", "conspiracy to commit wire fraud", "fraud_conspiracy"),
    "health_care_fraud": ("18", "1347", "health care fraud", "health_care_fraud"),
    "agg_id_theft": ("18", "1028A", "aggravated identity theft", "aggravated_identity_theft"),
    "money_laundering": ("18", "1956", "money laundering", "money_laundering"),
    "tax_evasion": ("26", "7201", "tax evasion", "tax_evasion"),
    "false_return": ("26", "7206", "filing a false tax return", "false_tax_return"),
    "computer_fraud": ("18", "1030", "computer fraud", "computer_fraud"),
    "sex_trafficking": ("18", "1591", "sex trafficking", "sex_trafficking"),
    "forced_labor": ("18", "1589", "forced labor", "forced_labor"),
    "csam_distribution": ("18", "2252A", "distribution of child pornography", "csam_receipt_distribution"),
    "enticement": ("18", "2422", "enticement of a minor", "coercion_and_enticement"),
    "securities_fraud": ("18", "1348", "securities fraud", "securities_fraud"),
}
MAXIMUM_YEARS = {
    "wire_fraud": 20, "mail_fraud": 20, "bank_fraud": 30, "wire_conspiracy": 20, "health_care_fraud": 10,
    "money_laundering": 20, "tax_evasion": 5, "false_return": 3, "computer_fraud": 10, "forced_labor": 20,
    "csam_distribution": 20, "securities_fraud": 25,
}


@dataclass(frozen=True)
class Narrative:
    """One way of telling how an offense was carried out, with the labels a
    careful reader would give it. `{D}` is the defendant or defendants,
    `{loss}` a dollar amount, `{victims}` a count, `{period}` when it happened."""

    key: str
    domain: str
    offenses: tuple[str, ...]
    text: str
    scheme: tuple[str, ...]
    channel: tuple[str, ...] = ()
    platform: tuple[str, ...] = ()
    # What the counted people are called in the text, and whether they are victims.
    counted: str = "victims"
    financial: bool = True
    # Labels the text supports without stating: neither required nor counted against a reader.
    arguable: tuple[str, ...] = ()
    # The story says the defendant was arrested.
    arrested: bool = False


NARRATIVES = (
    Narrative(
        "romance_a", "fraud", ("wire_fraud", "money_laundering"),
        "{period}, {D} took part in a romance scam aimed at people who were looking for companionship online. {D} created "
        "fake profiles on dating websites and social media and built relationships with the people who answered. Once "
        "trust was established, the victims were told that money was needed for a medical emergency or to release an "
        "inheritance held overseas. The victims sent the money by wire transfer and by buying gift cards. In all, "
        "{victims} victims lost {loss}.",
        scheme=("romance",), channel=("dating_site", "social_media", "wire_transfer", "gift_card"),
        arguable=("channel:website",),
    ),
    Narrative(
        "romance_b", "fraud", ("wire_fraud",),
        "According to court documents, {period} {D} posed online as an engineer working on an offshore oil platform. "
        "Using invented names and stolen photographs, {D} met widowed and divorced people through dating apps, exchanged "
        "affectionate notes with them for months, and then asked for help paying customs charges on equipment. The "
        "people who believed the story sent their savings through Western Union and MoneyGram. {victims} victims in "
        "several states lost {loss}.",
        scheme=("romance",), channel=("dating_site",), platform=("western_union", "moneygram"),
    ),
    Narrative(
        "bec_a", "fraud", ("wire_fraud", "money_laundering"),
        "{period}, {D} carried out a business email compromise scheme. {D} gained access to the e-mail accounts of "
        "company employees who handled payments, watched for pending invoices, and then sent e-mails that appeared to "
        "come from known vendors with new payment instructions. The companies wired the money to bank accounts that "
        "{D} controlled. {victims} companies lost {loss}.",
        scheme=("business_email_compromise",), channel=("email", "bank_account", "wire_transfer"), counted="companies",
    ),
    Narrative(
        "bec_b", "fraud", ("wire_conspiracy",),
        "Court records show that {period} {D} tricked the finance staff of a regional hospital system and a title "
        "company into redirecting vendor payments. {D} registered internet domains that differed by one letter from "
        "those of real suppliers and used them to send payment-change requests. The money, {loss} in all, went by wire "
        "transfer to accounts opened in the names of shell companies.",
        scheme=("business_email_compromise",), channel=("wire_transfer", "bank_account"),
    ),
    Narrative(
        "ponzi_a", "fraud", ("wire_fraud", "securities_fraud"),
        "{period}, {D} ran a Ponzi scheme. {D} told investors that their money would be used to buy and resell medical "
        "supplies and promised returns of 20 percent a year. There was no such business. {D} used money from new "
        "investors to make payments to earlier ones and spent the rest on personal expenses. {victims} investors lost "
        "{loss}.",
        scheme=("ponzi",), counted="investors",
    ),
    Narrative(
        "ponzi_b", "fraud", ("wire_fraud", "mail_fraud"),
        "According to the evidence, {period} {D} solicited money for a real estate fund that {D} said would buy and "
        "renovate apartment buildings. {D} defrauded investors by sending them account statements showing gains that "
        "did not exist. Withdrawals were paid with deposits from people who joined later. When the fund collapsed, "
        "{victims} investors had lost {loss}.",
        scheme=("investment", "ponzi"), counted="investors",
    ),
    Narrative(
        "ppp_a", "fraud", ("wire_fraud", "bank_fraud"),
        "{period}, {D} submitted false applications for Paycheck Protection Program loans on behalf of companies that "
        "had no employees and no payroll. The applications included fabricated payroll records. Lenders approved the "
        "applications and paid out {loss}, which {D} spent on vehicles, jewelry and travel.",
        scheme=("pandemic_relief",),
    ),
    Narrative(
        "ppp_b", "fraud", ("wire_fraud",),
        "According to court documents, {period} {D} applied for COVID-19 relief money meant for small businesses hurt "
        "by the pandemic. {D} claimed to run a landscaping company with dozens of workers. The company did not exist. "
        "{D} received {loss} and moved it through several bank accounts within days.",
        scheme=("pandemic_relief",), channel=("bank_account",),
    ),
    Narrative(
        "health_a", "fraud", ("health_care_fraud",),
        "{period}, {D} operated a medical equipment company and billed Medicare for braces and wheelchairs that "
        "patients did not need and in many cases never received. {D} paid kickbacks to marketers who supplied "
        "patient information. Medicare paid {loss} on the false claims.",
        scheme=("health_care_fraud",), arguable=("offense:anti_kickback", "offense:false_claims"),
    ),
    Narrative(
        "health_b", "fraud", ("health_care_fraud", "wire_conspiracy"),
        "The evidence showed that {period} {D} owned a home health agency that submitted claims for nursing visits "
        "that were never made. Staff were told to copy visit notes from one patient file to another. The government "
        "health insurance program for the elderly and disabled paid the agency {loss}.",
        scheme=("health_care_fraud",),
    ),
    Narrative(
        "tech_a", "fraud", ("wire_fraud", "wire_conspiracy"),
        "{period}, {D} worked with a call center that ran a tech support scam. Pop-up warnings told computer users, "
        "many of them elderly victims, that their machines were infected and gave a phone number to call. Callers were "
        "persuaded to install remote access software, including AnyDesk, and to pay for repairs that were never "
        "needed. Payment was taken in gift cards. More than {victims} victims lost {loss}.",
        scheme=("tech_support", "elder_fraud"), channel=("phone_call", "remote_access", "gift_card"), platform=("anydesk",),
    ),
    Narrative(
        "grandparent_a", "fraud", ("wire_conspiracy", "mail_fraud"),
        "According to court documents, {period} {D} belonged to a group that telephoned older adults and pretended to "
        "be a grandson who had been arrested after a car accident. A second caller, pretending to be a lawyer, said "
        "that bail had to be paid in cash that day. {D} then sent couriers to collect the money in person. {victims} "
        "victims lost {loss}.",
        scheme=("grandparent", "elder_fraud"), channel=("phone_call", "in_person"),
    ),
    Narrative(
        "embezzle_a", "fraud", ("wire_fraud", "bank_fraud"),
        "{period}, {D} worked as the bookkeeper of a family-owned construction supplier. {D} wrote company checks to "
        "pay personal credit card bills and recorded them in the ledger as payments to vendors. {D} embezzled {loss} "
        "before an outside accountant found the entries.",
        scheme=("embezzlement",),
    ),
    Narrative(
        "embezzle_b", "fraud", ("wire_fraud",),
        "The plea documents state that {period} {D}, the office manager of a dental practice, changed the payroll "
        "records to pay additional salary into a personal account and used the practice's credit line for personal "
        "purchases. The practice lost {loss}.",
        scheme=("embezzlement",),
    ),
    Narrative(
        "crypto_a", "fraud", ("wire_conspiracy", "money_laundering"),
        "{period}, {D} helped run a cryptocurrency investment scam of the kind known as pig butchering. Victims were "
        "contacted on WhatsApp and Telegram by people who pretended to have dialed a wrong number and then turned the "
        "conversation to investing. They were directed to a fake trading platform that showed large gains. When the "
        "victims tried to withdraw, they were told to pay taxes first. {victims} victims lost {loss}, which was "
        "converted to Tether and moved overseas.",
        scheme=("crypto_investment",), channel=("cryptocurrency", "website"), platform=("whatsapp", "telegram"),
    ),
    Narrative(
        "idtheft_a", "fraud", ("bank_fraud", "agg_id_theft"),
        "{period}, {D} bought stolen identities and used them to open bank accounts and apply for credit. {D} "
        "deposited counterfeit checks into the accounts and withdrew the money before the banks discovered that the "
        "checks were worthless. The banks lost {loss}. The identities of {victims} people were used.",
        scheme=("identity_theft", "bank_fraud"), channel=("bank_account",), counted="people",
    ),
    Narrative(
        "tax_a", "fraud", ("false_return", "tax_evasion"),
        "{period}, {D} ran a tax preparation business and prepared false tax returns for clients, claiming business "
        "losses and education credits that the clients had not earned. {D} took a share of each inflated refund. The "
        "returns caused a tax loss of {loss}.",
        scheme=("tax",),
    ),
    Narrative(
        "sextraf_a", "trafficking", ("sex_trafficking",),
        "{period}, {D} recruited women with false promises of restaurant jobs and then compelled them to engage in "
        "commercial sex. {D} posted online advertisements offering the women, kept the money they were paid, and used "
        "threats of violence against those who tried to leave. {D} transported the women across state lines between "
        "motels. Investigators identified {victims} victims.",
        scheme=("sex_trafficking", "recruitment_deception", "online_advertising", "force_fraud_coercion", "interstate_transport"),
        channel=("online_advertisement",), financial=False,
    ),
    Narrative(
        "sextraf_b", "trafficking", ("sex_trafficking",),
        "According to the evidence at trial, {period} {D} controlled several adults through a combination of debt and "
        "fear. {D} told them that they owed a debt for housing and transportation and that it could be paid only by "
        "performing commercial sex acts arranged through escort websites. {D} supplied them with heroin to keep them "
        "dependent. {victims} victims testified.",
        scheme=("sex_trafficking", "debt_bondage", "online_advertising", "drug_dependency"), channel=("website",), financial=False,
    ),
    Narrative(
        "labor_a", "forced_labor", ("forced_labor",),
        "{period}, {D} recruited workers from the Philippines with promises of good wages and lawful jobs on H-2B "
        "visas. When the workers arrived, {D} confiscated their passports, housed them in a crowded basement, and "
        "made them work up to 16 hours a day in two restaurants for little pay. {D} told them that they would be "
        "reported to immigration authorities if they complained. The forced labor continued until one worker "
        "contacted a neighbor. {victims} workers were identified.",
        scheme=("forced_labor", "labor_recruitment_fraud", "visa_fraud", "document_confiscation", "wage_theft",
                "threat_of_deportation", "restaurant_hospitality"),
        counted="workers", financial=False,
    ),
    Narrative(
        "ransom_a", "cyber", ("computer_fraud", "wire_conspiracy"),
        "{period}, {D} deployed ransomware on the computer networks of school districts, a county government and "
        "several hospitals. {D} obtained access with stolen credentials bought on a darknet market, encrypted the "
        "victims' files, and demanded ransom payments in Bitcoin. {victims} victims paid a total of {loss}.",
        scheme=("ransomware", "phishing", "darknet_market"), channel=("malware", "cryptocurrency", "darkweb"),
    ),
    Narrative(
        "simswap_a", "cyber", ("computer_fraud", "agg_id_theft"),
        "According to court documents, {period} {D} carried out SIM swapping attacks. {D} persuaded mobile carrier "
        "employees to move victims' phone numbers to devices that {D} controlled, used the numbers to reset account "
        "passwords, and then stole cryptocurrency from the victims' wallets. {victims} victims lost {loss}.",
        scheme=("sim_swapping", "crypto_theft"), channel=("cryptocurrency",),
    ),
    Narrative(
        "csam_a", "csea", ("csam_distribution",),
        "{period}, {D} used a peer-to-peer file-sharing network to distribute child sexual abuse material. An "
        "undercover agent downloaded files from a computer at the residence of {D}. A search of the devices found "
        "there confirmed the distribution of child sexual abuse material.",
        scheme=("distribution", "undercover_operation"), channel=("cloud_storage",), financial=False, counted="",
    ),
    Narrative(
        "entice_a", "csea", ("enticement",),
        "According to court documents, {period} {D} used Snapchat to send sexual messages to a person {D} believed to "
        "be a child. The person was an undercover officer. {D} arranged a meeting and was arrested on arrival. The "
        "charge is coercion and enticement of a minor.",
        scheme=("enticement", "undercover_operation"), platform=("snapchat",), financial=False, counted="", arrested=True,
    ),
)


@dataclass
class Person:
    key: str
    given: str
    middle: str
    surname: str
    age: int
    city: str
    state: str

    @property
    def full(self) -> str:
        return f"{self.given} {self.middle}. {self.surname}" if self.middle else f"{self.given} {self.surname}"

    @property
    def caps(self) -> str:
        return self.full.upper().replace(".", "")

    @property
    def plain(self) -> str:
        return f"{self.given} {self.surname}"


@dataclass
class Outcome:
    """What happened to one defendant. A date is None when it has not happened."""

    offenses: tuple[str, ...]
    arrest: date | None = None
    charge_kind: str = "indictment"  # complaint | indictment | information
    complaint: date | None = None
    charge: date | None = None  # the indictment or information
    superseding: date | None = None
    disposition: str | None = None  # plea | verdict
    disposition_date: date | None = None
    withdrawn_plea: date | None = None
    sentencing: date | None = None
    resentencing: date | None = None
    scheduled_sentencing: date | None = None
    months: int | None = None  # imprisonment; None with probation
    life: bool = False
    resentenced_months: int | None = None
    supervised_years: int | None = None
    probation_years: int | None = None
    restitution: float | None = None
    forfeiture: float | None = None
    fine: float | None = None


@dataclass
class Case:
    case_id: str
    split: str
    domain: str
    district: tuple[Any, ...]
    docket: str
    judge: Person
    prosecutor: Person
    agent: Person
    agencies: tuple[str, ...]
    narrative: Narrative
    defendants: list[Person]
    outcomes: dict[str, Outcome]
    offense_start: date
    offense_end: date
    loss: float | None
    victims: int | None
    stage: str  # charged | disposed | sentenced
    # A planted departure from the usual path, or a planted inconsistency in what the documents say.
    planted: str | None = None
    notes: dict[str, Any] = field(default_factory=dict)


def _round_money(rng: random.Random, low: float, high: float) -> float:
    value = rng.uniform(low, high)
    style = rng.random()
    if style < 0.45:  # a figure a release would round: "$1.9 million", "$640,000"
        if value >= 1_000_000:
            return round(value / 100_000) * 100_000.0
        return round(value / 10_000) * 10_000.0
    if style < 0.8:
        return float(round(value))
    return round(value, 2)


def _business_day(rng: random.Random, start: date, low: int, high: int) -> date:
    day = start + timedelta(days=rng.randint(low, high))
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def _person(rng: random.Random, key: str, used: set[str], district: tuple[Any, ...], *, official: bool = False) -> Person:
    while True:
        surname = rng.choice(SURNAMES)
        if surname not in used:
            used.add(surname)
            break
    return Person(
        key, rng.choice(GIVEN), rng.choice(MIDDLE) if rng.random() < (0.9 if official else 0.35) else "", surname,
        rng.randint(24, 71), rng.choice(district[4]), district[3],
    )


def sample_case(seed: int, number: int) -> Case:
    rng = random.Random(seed * 100_003 + number)
    narrative = rng.choice(NARRATIVES)
    district = rng.choice(DISTRICTS)
    used: set[str] = set()
    count = rng.choices((1, 2, 3), weights=(62, 28, 10))[0]
    if narrative.key in ("csam_a", "entice_a", "embezzle_a", "embezzle_b", "tax_a"):
        count = 1
    defendants = [_person(rng, f"d{index + 1}", used, district) for index in range(count)]
    judge, prosecutor, agent = (_person(rng, key, used, district, official=True) for key in ("judge", "ausa", "agent"))

    offense_start = date(rng.randint(2017, 2022), rng.randint(1, 12), 1)
    offense_end = _business_day(rng, offense_start, 240, 1100)
    stage = rng.choices(("charged", "disposed", "sentenced"), weights=(24, 22, 54))[0]
    planted = None
    if stage == "sentenced" and rng.random() < 0.16:
        planted = rng.choice(("resentencing", "plea_withdrawn", "date_inconsistency"))

    loss = _round_money(rng, 90_000, 9_500_000) if narrative.financial else None
    victims = rng.choice((3, 4, 6, 9, 12, 14, 17, 23, 31, 46, 58, 120)) if narrative.counted else None

    year = offense_end.year + (1 if offense_end.month > 8 else 0)
    docket = f"{rng.randint(1, 5)}:{year % 100:02d}-cr-{rng.randint(11, 989):05d}"
    arrest_all = _business_day(rng, offense_end, 20, 200) if rng.random() < 0.4 else None
    charge_kind = rng.choices(("indictment", "complaint", "information"), weights=(58, 24, 18))[0]
    outcomes: dict[str, Outcome] = {}
    for position, person in enumerate(defendants):
        offenses = narrative.offenses if position == 0 or rng.random() < 0.6 else narrative.offenses[:1]
        out = Outcome(offenses=tuple(offenses), charge_kind=charge_kind, arrest=arrest_all)
        base = arrest_all or _business_day(rng, offense_end, 30, 260)
        if charge_kind == "complaint":
            out.complaint = base if arrest_all is None else _business_day(rng, base, -3, 0)
            out.arrest = out.arrest or _business_day(rng, out.complaint, 0, 6)
            out.charge = _business_day(rng, out.complaint, 14, 40)
        else:
            out.charge = _business_day(rng, base, 1, 45)
        if charge_kind == "indictment" and rng.random() < 0.07:
            out.superseding = _business_day(rng, out.charge, 60, 200)
        if stage in ("disposed", "sentenced"):
            out.disposition = "plea" if charge_kind == "information" or rng.random() < 0.8 else "verdict"
            out.disposition_date = _business_day(rng, out.superseding or out.charge, 90, 420)
            if planted == "plea_withdrawn" and position == 0:
                out.withdrawn_plea = out.disposition_date
                out.disposition = "verdict"
                out.disposition_date = _business_day(rng, out.withdrawn_plea, 120, 260)
            if stage == "disposed":
                out.scheduled_sentencing = _business_day(rng, out.disposition_date, 80, 140)
        if stage == "sentenced":
            out.sentencing = _business_day(rng, out.disposition_date, 85, 230)
            cap = min(MAXIMUM_YEARS.get(o, 20) for o in out.offenses) * 12
            if narrative.domain in ("trafficking", "forced_labor", "csea"):
                out.months = rng.choice((60, 87, 96, 120, 135, 151, 180, 210, 240))
            elif rng.random() < 0.12 and (loss or 0) < 600_000:
                out.months, out.probation_years = None, rng.choice((2, 3, 5))
            else:
                out.months = min(cap, rng.choice((6, 12, 18, 21, 24, 27, 30, 33, 37, 41, 46, 51, 57, 63, 70, 78, 87, 97, 108, 121)))
            if out.months is not None:
                out.supervised_years = 5 if narrative.domain in ("trafficking", "csea") else rng.choice((1, 2, 3, 3, 3, 5))
            if narrative.financial:
                share = loss if position == 0 else _round_money(rng, loss * 0.2, loss * 0.9)
                out.restitution = share if rng.random() < 0.85 else None
                out.forfeiture = _round_money(rng, loss * 0.1, loss * 0.8) if rng.random() < 0.4 else None
                out.fine = rng.choice((5_000.0, 10_000.0, 25_000.0, 50_000.0)) if rng.random() < 0.14 else None
            if planted == "resentencing" and position == 0 and out.months:
                out.resentencing = _business_day(rng, out.sentencing, 300, 560)
                out.resentenced_months = max(6, out.months - rng.choice((6, 12, 15, 24)))
        outcomes[person.key] = out

    if count > 1 and planted is None and rng.random() < 0.5:
        # Co-defendants who went through the case together: same dates.
        first = outcomes[defendants[0].key]
        for person in defendants[1:]:
            other = outcomes[person.key]
            other.charge, other.complaint, other.arrest = first.charge, first.complaint, first.arrest
            if first.disposition == other.disposition:
                other.disposition_date, other.scheduled_sentencing = first.disposition_date, first.scheduled_sentencing
                other.sentencing = first.sentencing

    return Case(
        case_id=f"gold-case-{number:03d}", split="dev" if number % 2 == 0 else "test", domain=narrative.domain,
        district=district, docket=docket, judge=judge, prosecutor=prosecutor, agent=agent,
        agencies=tuple(rng.sample(AGENCIES[narrative.domain], k=min(2, len(AGENCIES[narrative.domain])))),
        narrative=narrative, defendants=defendants, outcomes=outcomes, offense_start=offense_start,
        offense_end=offense_end, loss=loss, victims=victims, stage=stage, planted=planted,
    )
