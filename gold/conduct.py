"""Gold statements of offense: invented filings whose acts are known.

The 200-record corpus measures what the engine reads about a prosecution.
This one measures what it reads about the offense. Each record is a statement
of offense written from a script: an ordered list of acts, each with its kind,
its date where the text gives one, and the technology its sentence names.

A script is told two ways. One telling uses the verbs a reader would expect.
The other paraphrases, sometimes with words the engine's lexicon does not
hold, so that a reader which only knows its own words is seen to miss.

The documents also carry what must not be read as conduct: the section that
recites the elements of the offense in the statute's own verbs, and the
penalties section. Everything is invented; see `gold/README.md`.
"""

from __future__ import annotations

import hashlib
import json
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from gold.render import NOTICE
from gold.world import DISTRICTS, GIVEN, MIDDLE, SURNAMES

SEED = 20261115
RECORDS = 80
CORPUS = Path(__file__).resolve().parent / "corpus"
_MONTH = "January February March April May June July August September October November December".split()

# (kind, means, plain telling, paraphrase). {D} the defendant, {V} the person harmed, {A} an amount.
Step = tuple[str, dict[str, list[str]], str, str]
SCRIPTS: dict[str, dict[str, Any]] = {
    "romance": {"domain": "fraud", "offense": ("wire fraud", "18 U.S.C. § 1343"), "steps": [
        ("setup", {"channel": ["dating_site", "website"]}, "{D} created a profile on a dating website using a name and photographs that were not {D}'s own", "{D} put up a profile on a dating website under an invented name"),
        ("contact", {"channel": ["dating_site", "website"]}, "{D} contacted {V} through the dating website", "{D} struck up a conversation with {V} through the dating website"),
        ("deception", {}, "{D} posed as an engineer working on an offshore oil platform", "{D} told {V} a story about working as an engineer on an offshore oil platform, none of which was true"),
        ("demand", {"channel": ["wire_transfer"]}, "{D} asked {V} to send money by wire transfer to pay customs fees", "{D} said that customs fees had to be paid and that {V} should cover them by wire transfer"),
        ("transfer", {"channel": ["bank_account"]}, "{V} wired {A} to a bank account that {D} controlled", "{V} parted with {A}, which went to a bank account that {D} controlled"),
        ("movement", {}, "{D} withdrew the funds in cash within days", "{D} took the funds out in cash within days"),
    ]},
    "bec": {"domain": "fraud", "offense": ("wire fraud", "18 U.S.C. § 1343"), "steps": [
        ("setup", {}, "{D} registered an internet domain that differed by one letter from the domain of a real supplier", "{D} bought an internet domain one letter away from that of a real supplier"),
        ("access", {"channel": ["email"]}, "{D} gained unauthorized access to the e-mail account of an employee of {V}", "{D} got into the e-mail account of an employee of {V} without permission"),
        ("deception", {"channel": ["email"]}, "{D} impersonated the supplier in e-mails to the accounting department of {V}", "{D} wrote to the accounting department of {V} by e-mail as if {D} were the supplier"),
        ("demand", {}, "{D} instructed {V} to send future payments to a new account", "{D} gave {V} new payment instructions"),
        ("transfer", {}, "{V} wired {A} to the account named in the instructions", "{A} left the accounts of {V} for the account named in the instructions"),
        ("movement", {"channel": ["cryptocurrency"]}, "{D} converted the funds into cryptocurrency", "{D} turned the funds into cryptocurrency"),
    ]},
    "relief": {"domain": "fraud", "offense": ("bank fraud", "18 U.S.C. § 1344"), "steps": [
        ("setup", {}, "{D} incorporated a company that had no employees and no business", "{D} formed a company that had no employees and no business"),
        ("deception", {}, "{D} submitted a false application for a pandemic relief loan in the company's name", "{D} applied for a pandemic relief loan in the company's name, stating a payroll that did not exist"),
        ("deception", {}, "{D} fabricated payroll records to support the application", "{D} made up payroll records to support the application"),
        ("transfer", {}, "The lender deposited {A} into the company's account", "The lender funded the loan, and {A} reached the company's account"),
        ("movement", {}, "{D} withdrew the funds and spent them on personal purchases", "{D} drew the funds down and spent them on personal purchases"),
    ]},
    "ransomware": {"domain": "cyber", "offense": ("computer fraud", "18 U.S.C. § 1030"), "steps": [
        ("setup", {"channel": ["darkweb"]}, "{D} purchased stolen login credentials on a dark web marketplace", "{D} bought stolen login credentials on a dark web marketplace"),
        ("access", {}, "{D} accessed the computer network of {V} without authorization", "{D} entered the computer network of {V} without authorization"),
        ("access", {"channel": ["malware"]}, "{D} deployed ransomware on the servers of {V}", "{D} ran ransomware on the servers of {V}"),
        ("demand", {"channel": ["cryptocurrency"]}, "{D} demanded a ransom payment in Bitcoin", "{D} left a note stating the price, in Bitcoin, of restoring the files"),
        ("threat", {}, "{D} threatened to publish the stolen files if {V} did not pay", "{D} warned that the stolen files would be made public if {V} did not pay"),
        ("transfer", {"channel": ["cryptocurrency"]}, "{V} paid {A} in Bitcoin", "{V} sent Bitcoin worth {A}"),
    ]},
    "sextortion": {"domain": "extortion", "offense": ("interstate threats", "18 U.S.C. § 875"), "steps": [
        ("setup", {"platform": ["instagram"]}, "{D} created an Instagram account under a false name", "{D} made an Instagram account under a false name"),
        ("contact", {"platform": ["instagram"]}, "{D} messaged {V} on Instagram", "{D} wrote to {V} on Instagram"),
        ("deception", {}, "{D} pretended to be a woman of about the same age as {V}", "{D} let {V} believe that {D} was a woman of about the same age"),
        ("threat", {}, "{D} threatened to send intimate images of {V} to {V}'s family", "{D} said that intimate images of {V} would go to {V}'s family"),
        ("demand", {"channel": ["gift_card"]}, "{D} demanded payment in gift cards", "{D} named a price, to be paid in gift cards"),
        ("transfer", {"channel": ["gift_card"]}, "{V} purchased gift cards worth {A} and sent the codes", "{V} bought gift cards worth {A} and gave up the codes"),
    ]},
    "sex_trafficking": {"domain": "trafficking", "offense": ("sex trafficking", "18 U.S.C. § 1591"), "steps": [
        ("recruit", {}, "{D} recruited {V} with a promise of a job in a restaurant", "{D} offered {V} a job in a restaurant that did not exist"),
        ("transport", {}, "{D} transported {V} across state lines to a motel", "{D} drove {V} across state lines to a motel"),
        ("control", {}, "{D} took {V}'s identification and phone", "{D} kept hold of {V}'s identification and phone"),
        ("threat", {}, "{D} threatened to harm {V} if {V} tried to leave", "{D} told {V} that leaving would end in violence"),
        ("exploit", {"channel": ["online_advertisement"]}, "{D} posted online advertisements offering {V} for commercial sex", "{D} put online advertisements up offering {V} for commercial sex"),
        ("exploit", {}, "{D} kept the money that {V} was paid", "{D} took everything that {V} was paid"),
    ]},
    "forced_labor": {"domain": "forced_labor", "offense": ("forced labor", "18 U.S.C. § 1589"), "steps": [
        ("recruit", {}, "{D} recruited {V} abroad with a promise of lawful work and good wages", "{D} found {V} abroad and promised lawful work and good wages"),
        ("transport", {}, "{D} brought {V} to the United States on a temporary work visa", "{D} arranged a temporary work visa and {V}'s travel to the United States"),
        ("control", {}, "{D} confiscated {V}'s passport on arrival", "{D} held on to {V}'s passport from the day of arrival"),
        ("exploit", {}, "{D} required {V} to work sixteen hours a day for little pay", "{V} worked sixteen hours a day for {D} for little pay"),
        ("threat", {}, "{D} threatened to report {V} to immigration authorities", "{D} said that immigration authorities would be told about {V}"),
    ]},
    "enticement": {"domain": "csea", "offense": ("enticement of a minor", "18 U.S.C. § 2422"), "steps": [
        ("contact", {"platform": ["snapchat"]}, "{D} messaged a person {D} believed to be a child on Snapchat", "{D} began writing on Snapchat to a person {D} believed to be a child"),
        ("recruit", {"channel": ["in_person"]}, "{D} enticed that person to meet in person", "{D} pressed that person to meet in person"),
        ("transport", {}, "{D} traveled to the meeting place", "{D} went to the meeting place"),
    ]},
    "drug_sale": {"domain": "drugs", "offense": ("distribution of a controlled substance", "21 U.S.C. § 841"), "steps": [
        ("setup", {"channel": ["darkweb"]}, "{D} opened a vendor account on a dark web marketplace", "{D} set up as a vendor on a dark web marketplace"),
        ("supply", {"channel": ["mail"]}, "{D} shipped pills containing fentanyl to buyers through the U.S. mail", "{D} sent pills containing fentanyl to buyers through the U.S. mail"),
        # A buyer's payment for contraband is part of the sale, not value taken from a person harmed.
        ("supply", {"channel": ["cryptocurrency"]}, "Buyers paid {D} in cryptocurrency", "{D} took payment from buyers in cryptocurrency"),
        ("movement", {}, "{D} laundered the proceeds through accounts held in other names", "{D} ran the proceeds through accounts held in other names"),
    ]},
}
ELEMENTS = (
    "II. ELEMENTS OF THE OFFENSE\n"
    "To prove the offense charged, the government must prove beyond a reasonable doubt that the defendant knowingly devised a scheme, "
    "that the defendant recruited, enticed, transported or obtained a person or a thing of value, that the defendant threatened or deceived "
    "another to do so, and that the defendant sent or caused to be sent a communication in interstate commerce."
)
PENALTIES = (
    "III. PENALTIES\n"
    "The defendant understands that the offense is punishable by a term of imprisonment, a fine, and a term of supervised release, and that the "
    "Court may order restitution to any person who paid or transferred money as a result of the offense."
)


def _stamp(when: date, form: str) -> tuple[str, str | None]:
    if form == "day":
        return f"On or about {_MONTH[when.month - 1]} {when.day}, {when.year}, ", when.isoformat()
    if form == "month":
        return f"In or about {_MONTH[when.month - 1]} {when.year}, ", f"{when.year:04d}-{when.month:02d}"
    return "", None


def _record(number: int) -> tuple[dict[str, Any], dict[str, Any]]:
    rng = random.Random(SEED * 31 + number)
    key = list(SCRIPTS)[number % len(SCRIPTS)]
    script = SCRIPTS[key]
    district = rng.choice(DISTRICTS)
    surname = rng.choice(SURNAMES)
    full = f"{rng.choice(GIVEN)} {rng.choice(MIDDLE)}. {surname}"
    victim = rng.choice(("Victim-1", "the victim", "Company A")) if key not in ("enticement", "drug_sale") else "the victim"
    if key in ("bec", "ransomware"):
        victim = rng.choice(("Company A", "Victim Company 1"))
    amount = f"${rng.choice((18_500, 42_000, 96_300, 240_000, 1_150_000)):,}"
    paraphrase = rng.random() < 0.45
    when = date(rng.randint(2019, 2024), rng.randint(1, 12), rng.randint(1, 27))
    docket = f"{rng.randint(1, 5)}:{(when.year + 1) % 100:02d}-cr-{rng.randint(11, 989):05d}"
    acts: list[dict[str, Any]] = []
    lines: list[str] = []
    for index, (kind, means, plain, other) in enumerate(script["steps"]):
        when += timedelta(days=rng.randint(2, 45))
        prefix, stamp = _stamp(when, rng.choices(("day", "month", "none"), weights=(45, 15, 40))[0])
        sentence = (other if paraphrase and rng.random() < 0.7 else plain).replace("{D}", surname).replace("{V}", victim).replace("{A}", amount)
        if prefix:
            sentence = prefix + sentence if sentence.startswith(surname) or sentence[0].isupper() and sentence.split()[0] in (surname, "Victim-1", "Company", "Buyers") else prefix + sentence[0].lower() + sentence[1:]
        lines.append(f"{index + 4}. {sentence}.")
        acts.append({"kind": kind, "date": stamp, "means": {k: sorted(v) for k, v in means.items()}})
    when += timedelta(days=rng.randint(20, 200))
    prefix, stamp = _stamp(when, "day")
    lines.append(f"{len(lines) + 4}. {prefix}agents executed a search warrant at the residence of {surname}.")
    acts.append({"kind": "detection", "date": stamp, "means": {}})

    name, cite = script["offense"]
    filed = when + timedelta(days=rng.randint(60, 300))
    text = "\n".join([
        f"Case {docket} Document {rng.randint(9, 60)} Filed {filed.month:02d}/{filed.day:02d}/{filed.year % 100:02d} Page 1 of 6",
        "UNITED STATES DISTRICT COURT", f"FOR THE {district[1].upper()}", "UNITED STATES OF AMERICA", "v.",
        f"{full.upper().replace('.', '')},", "Defendant.", f"Criminal No. {docket}", "STATEMENT OF OFFENSE",
        f"Pursuant to Federal Rule of Criminal Procedure 11, the United States and the defendant, {full}, stipulate and agree that the following "
        "facts are true and accurate. These facts do not constitute all of the facts known to the parties concerning the charged offense.",
        "I. SUMMARY OF THE PLEA AGREEMENT",
        f"1. The defendant agrees to plead guilty to Count One of the Information, which charges {name} in violation of {cite}.",
        ELEMENTS, PENALTIES, "IV. FACTUAL BASIS",
        f"2. At all times relevant to this Statement of Offense, {surname} resided in {district[4][0]}, {district[3]}.",
        f"3. {victim[0].upper()}{victim[1:]} is known to the parties and is not named here.",
        *lines,
        f"{len(lines) + 5}. This Statement of Offense is a summary and does not include every fact known to the defendant or to the government.",
        f"/s/ {full}", "Defendant",
    ])
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    record_id = "ct-" + digest[:16]
    entry = {
        "record_id": record_id, "kind": "court", "domain": script["domain"], "domains": [script["domain"]],
        "source_url": f"https://gold.example/conduct/{number:03d}/", "agency": f"District Court, {district[1]}",
        "docket_number": docket, "collected_as": "statement_of_offense", "sha256": digest, "notice": NOTICE,
    }
    split = "dev" if number % 2 == 0 else "test"
    return ({"record_id": record_id, "split": split, "script": key, "paraphrased": paraphrase, "entry": entry, "text": text},
            {"record_id": record_id, "split": split, "script": key, "paraphrased": paraphrase, "acts": acts, "defendant": full})


def generate() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pairs = [_record(number) for number in range(1, RECORDS + 1)]
    return [record for record, _ in pairs], [truth for _, truth in pairs]


def write() -> dict[str, Any]:
    records, truth = generate()
    CORPUS.mkdir(parents=True, exist_ok=True)
    for name, rows in (("conduct_records", records), ("conduct_truth", truth)):
        with (CORPUS / f"{name}.jsonl").open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return {"records": len(records), "acts": sum(len(t["acts"]) for t in truth), "paraphrased": sum(1 for r in records if r["paraphrased"]),
            "split": {key: sum(1 for r in records if r["split"] == key) for key in ("dev", "test")}}


def load(split: str | None = None) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    def rows(name: str) -> list[dict[str, Any]]:
        with (CORPUS / f"{name}.jsonl").open(encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    return ([r for r in rows("conduct_records") if split in (None, r["split"])],
            {t["record_id"]: t for t in rows("conduct_truth") if split in (None, t["split"])})


def _lcs(left: list[Any], right: list[Any]) -> int:
    table = [[0] * (len(right) + 1) for _ in range(len(left) + 1)]
    for i in range(len(left) - 1, -1, -1):
        for j in range(len(right) - 1, -1, -1):
            table[i][j] = table[i + 1][j + 1] + 1 if left[i] == right[j] else max(table[i + 1][j], table[i][j + 1])
    return table[0][0]


def score(split: str | None, name: str) -> dict[str, Any]:
    """Run the engine on the gold statements and compare the acts it stores with the acts they state.

    `acts` scores each act's kind, in order (an act counts when it is in the
    longest sequence the two lists share). `dated_acts` asks for the date too,
    `acts_with_means` for the technology. `paths` compares the whole sequence
    with a run of one kind counted once."""
    from collections import Counter, defaultdict

    from extraction import acts as act_rules, conduct as conduct_layer
    from gold import score as scoring

    records, truth = load(split)
    db = scoring.run(records, name)
    conduct_layer.build(db, scoring.source_for(records))
    tallies: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    by_kind: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    exact = {"all": [0, 0], "plain": [0, 0], "paraphrased": [0, 0]}
    phase_exact = [0, 0]
    similarity = []
    from state_machines import states as st

    state_exact = {"all": [0, 0], "plain": [0, 0], "paraphrased": [0, 0]}
    terminal_exact, predicate_exact = [0, 0], [0, 0]
    for record in records:
        want = truth[record["record_id"]]["acts"]
        have = conduct_layer.sequence(db, record["record_id"])
        for label, key in (
            ("acts", lambda a: a["kind"]),
            ("dated_acts", lambda a: (a["kind"], a["date"])),
            ("acts_with_means", lambda a: (a["kind"], json.dumps(a.get("means") or {}, sort_keys=True))),
        ):
            left, right = [key(a) for a in want], [key(a) for a in have]
            shared = _lcs(left, right)
            tallies[label][0] += shared
            tallies[label][1] += len(right) - shared
            tallies[label][2] += len(left) - shared
        wanted, found = Counter(a["kind"] for a in want), Counter(a["kind"] for a in have)
        for kind in set(wanted) | set(found):
            hit = min(wanted[kind], found[kind])
            by_kind[kind][0] += hit
            by_kind[kind][1] += found[kind] - hit
            by_kind[kind][2] += wanted[kind] - hit
        want_path, have_path = conduct_layer.path(want), conduct_layer.path(have)
        similarity.append(2 * _lcs(list(want_path), list(have_path)) / (len(want_path) + len(have_path)) if want_path or have_path else 1.0)
        for bucket in ("all", "paraphrased" if record["paraphrased"] else "plain"):
            exact[bucket][0] += int(want_path == have_path)
            exact[bucket][1] += 1
        phases = lambda path: conduct_layer.path([{"kind": act_rules.PHASE[k]} for k in path])  # noqa: E731
        phase_exact[0] += int(phases(want_path) == phases(have_path))
        phase_exact[1] += 1
        truth_states, read_states = st.path({"acts": want}), st.path({"acts": have})
        for bucket in ("all", "paraphrased" if record["paraphrased"] else "plain"):
            state_exact[bucket][0] += int(truth_states == read_states)
            state_exact[bucket][1] += 1
        terminal_exact[0] += int(truth_states[-1:] == read_states[-1:])
        terminal_exact[1] += 1
        predicate_exact[0] += int(st.predicate({"acts": want}) == st.predicate({"acts": have}))
        predicate_exact[1] += 1

    def report(tp: int, fp: int, fn: int) -> dict[str, Any]:
        p, r = (tp / (tp + fp) if tp + fp else None), (tp / (tp + fn) if tp + fn else None)
        return {"tp": tp, "fp": fp, "fn": fn, "precision": p and round(p, 3), "recall": r and round(r, 3),
                "f1": round(2 * p * r / (p + r), 3) if p and r else None}

    return {
        "split": split or "all", "records": len(records),
        **{label: report(*counts) for label, counts in tallies.items()},
        "by_kind": {kind: report(*counts) for kind, counts in sorted(by_kind.items())},
        "paths_exact": {bucket: f"{hit} of {total}" for bucket, (hit, total) in exact.items()},
        "phase_paths_exact": f"{phase_exact[0]} of {phase_exact[1]}",
        "state_paths_exact": {bucket: f"{hit} of {total}" for bucket, (hit, total) in state_exact.items()},
        "terminal_state_exact": f"{terminal_exact[0]} of {terminal_exact[1]}",
        "exploitation_predicate_exact": f"{predicate_exact[0]} of {predicate_exact[1]}",
        "path_similarity": round(sum(similarity) / len(similarity), 3) if similarity else None,
    }
