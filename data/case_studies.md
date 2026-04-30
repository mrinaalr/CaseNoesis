# CaseLinker — draft pool for four new case studies (R1 / handoff)

**Purpose:** Triage four corpus IDs (`azicac_2011_009`, `ohio_ag_2017_002`, `nj_ag_2022_016`, `idaho_icac_2024_028`) against the **six case studies already authored** in `data/case_studies.json`, using the same **five analytical dimensions** the reading room uses.

---

## Site framing (from `visualization/case-studies.html` gate)

**What this is:** Structured studies from **public ICAC records** (press releases, task-force reports, closed adjudicated material). **Not** a crime database; **not** true crime. Historical and analytical—how the offense class and enforcement response changed across eras.

**Obligation to readers:** No graphic detail beyond analytical need; no unnecessary exposure. Offenders are **not** framed as monsters; the **landscape** is the unit of analysis.

**Sources & ethics:** Public, already-redacted records. HRPO #7668 (no private identifiable information under federal regs). **Convicted-offender names omitted** in published case studies. Vicarious-trauma-aware presentation.

**Feedback:** Public notes + private Google Form per study.

**Five dimensions** (canonical order, from `case_studies.json` notes):

1. **Platform context**
2. **Perpetrator methodology**
3. **Investigative approach**
4. **Prosecutorial outcome**
5. **Relationship to the broader technological era**

Each candidate below ends with a **5-dim skim** you can line up against a finished study before you author JSON.

---

## Six published studies (baseline portfolio)

| ID | Era | One-line thread |
|----|-----|-----------------|
| `azicac_2011_006` | I | P2P monitoring disclosed in-home production + redistribution; state DCAC sentencing. |
| `lapd_2017_001` | II | YouTube → Wizard 101 → upload service; NCMEC/upload-first; directed self-production. |
| `gbi_2020_002` | III | County-scale cybertip operation: warrants as child-protection, possession → hands-on surfacing. |
| `vt_ag_2020_011` | III | Kik undercover + federal possession; NCMEC/CPS GPS in video → state hands-on charge. |
| `doj_ceos_2025_025` | IV | Army soldier: AI on images of **known** children + in-home filming; hybrid federal stack. |
| `doj_ceos_2025_004` | IV | Greggy’s Cult: Discord + gaming contact surfaces; network charged as **enterprise**. |

**Portfolio gaps the four candidates might fill:**  
Era I beyond P2P (`009`); Era II that is **not** a “named app” story (`ohio_2017_002`); Era III **trafficking + classifieds/social web** (`nj`); Era IV **state** synthetic/AI-statute **first-prosecution** narrative (`idaho_2024_028`, distinct from federal DOJ framing).

---

## `azicac_2011_009` (corpus: AZICAC, 2011) — AIM / AOL CyberTip → search warrant, infant, neglect/CPS

**Era (facet year):** I (2010–2014).  
**DB:** `case_topics` `["family", "hands_on"]`; `platforms_used` `["AOL Instant Messenger"]`.

### 1) Case narrative as presented (corpus `case_text`)

```
In November 2011, AZICAC investigators from the
Phoenix Police Department and an F.B.I. Special
Agent executed a search warrant at a Phoenix
area residence as the result of a cybertip that
Phoenix Police had received from the National
Center for Missing and Exploited Children. AOL
had discovered an e-mail sent by an AIM user on
August 2, 2011 with an attached image of a
young female being sexually assaulted by an adult
male. The lead Phoenix Police investigator
conducted a court order process and identified
the AIM user who had sent to e-mail to himself
via his phone. Upon entry, investigators
discovered the residence to be a mess and
deplorable conditions for the 15 month old infant
living in the house. The suspect was a resident and
a 26 year old unemployed drug addict which
described others living in and out of the house.
The suspect admitted to sending the image via
his phone but investigators were unable to find it
during initial preview. He did not know the
identity of the victim. The baby was extremely
malnourished, there was no food in the house,
nothing had been cleaned, trashed was piled, etc.
Because of this, a child neglect investigation was
initiated and C.P.S. contacted to take custody of
the child, monitor the child for a month and if
need be, charge the mother with child neglect.
```

### 2) Summary of what happened (assistant)

AOL reported to NCMEC; Phoenix PD (AZICAC + FBI) used court process to tie an **AIM-sent email-to-self** (phone) to a residence, executed a warrant, and found not only a CSAM trail but a **15-month-old in severe neglect**. The file foregrounds **provider-visible email attachment** and **on-scene child-welfare crossover** (CPS, possible mother neglect charges)—not a P2P trade story like `azicac_2011_006`.

### 3) Five-dimension skim (draft)

1. **Platform context** — Mid–late Era I consumer stack: **AOL email / AIM** as the channel the provider could see; attachment-based reporting line to NCMEC, distinct from P2P crawling.
2. **Perpetrator methodology** — 26-year-old resident; self-send of abusive image; alleged **not** knowing victim identity; household instability described; hands-on/neglect layer at scene.
3. **Investigative approach** — CyberTip → lead investigator → **court-ordered ID** of AIM user → **simultaneous** criminal search and **immediate** child-safety/neglect response.
4. **Prosecutorial / agency outcome** — Text stops at **investigative/child-welfare** actions; **no** plea/sentence in excerpt—**gap** for a “published” study unless you add disposition from another record.
5. **Broader era** — Shows Era I **ESP reporting** as the disclosure path for abuse that is otherwise **in-home**; pairs analytically with `006` (same state task force, different **internet layer**).

**Pursuit note:** **Strong** thematic complement to `006` (Arizona, Era I) without repeating P2P. **Risk:** narrative includes **distressing infant condition**; needs strict CaseLinker **non-salacious** bar; **outcome** may need a second source.

---

## `ohio_ag_2017_002` (corpus: Ohio AG, May 2017) — Gallia County, Matthew Case, in-home unlicensed daycare, seven young victims

**Era (facet year):** II (2015–2018).  
**DB:** `case_topics` `['hands_on']`; `platforms_used` `[]`.  
**Corpus caveat:** body **duplicates**; trim for publication.

### 1) Case narrative as presented (corpus `case_text`)

```
May 01, 2017
Source: Ohio)— Ohio Attorney General Mike DeWine and Gallia County Prosecuting Attorney Jason
D. Holdren announced today that a Gallia County man has pleaded guilty to charges that he sexually assaulted
seven children at an in-home daycare operated by his wife. Matthew Case, 43, of 45 North Atwood Street in Rio
Grande, pleaded guilty this afternoon to a bill of information charging him with 10 counts of rape and six counts
of gross sexual imposition. Authorities with the Attorney General's Bureau of Criminal Investigation Crimes
Against Children Unit, Gallia County Sheriff's Office, and FBI Columbus Child Exploitation Task Force
arrested Case in April after two victims confided in an adult about the abuse. As a result of the investigation,
five additional victims were identified. All of the victims are females between the ages of three and seven. The
assaults occurred at Case's home between May 1, 2016, and April 12, 2017, while the children were at the
residence attending daycare. Because the in-home daycare reportedly cared for fewer than six children at a
time, it was not required to be licensed by the state of Ohio. At the time of his arrest, Case was a volunteer
firefighter. "My agents spoke with many parents who felt reassured by that fact that a firefighter lived at the
in-home daycare, but this defendant was truly a predator in disguise," said Attorney General DeWine. "Our big
concern right now is that he may have victimized even more children over the years, and we encourage anyone
with additional information on potential victims to contact law enforcement." "Due to the heinous nature of
these crimes and the age of the victims involved, my office wanted to bring justice to this situation as swiftly as
possible," said Gallia County Prosecuting Attorney Jason D. Holdren. "These victims are young children, some
of whom still do not have the ability to truly voice what they have experienced. Our goal is to bring an end to
this sexual violence and assist in helping these victims and their families begin the long process of healing. If
you have been, or suspect your child has been, victimized by Matthew Case, you may contact my office for
support services and counseling referrals." "This investigation is a result of our officers responding rapidly to
protect the victims and prevent any future crimes of abuse from occurring," added Gallia County Sheriff Matt
Champlin. "Taking advantage of the vulnerability of children is an unthinkable act and we will continue in our
efforts to identify victims who may have been abused." The investigation is ongoing, and anyone who believes
their child may have had inappropriate contact with Matthew Case is urged to call the Gallia County
Prosecutor’s Office at 740-446-0018; the Ohio Bureau of Criminal Investigation at 855-BCI-OHIO (224-6446);
or the Gallia County Sheriff's Office at 740-446-1221. Case will be sentenced before Gallia County Common
Pleas Judge Margaret Evans on May 25, 2017. Each count of rape carries a penalty of 15 years to life in prison.
Each count of gross sexual imposition carries a penalty of up to five years in prison. [duplicate paragraphs omitted in working copy]
```

### 2) Summary of what happened (assistant)

**Matthew Case** pleaded guilty to **10 rape** and **6 GSI** counts; **seven** girl victims (ages 3–7) in wife’s **in-home daycare**; **BCI Crimes Against Children + sheriff + FBI Columbus ICAC**. Disclosures started with **two** children telling an adult; investigation found **five** more. Policy hook: daycare **below Ohio licensing threshold**; **volunteer firefighter** as misplaced trust symbol. **Sentencing** was scheduled; confirm outcome if you publish (text is pre-sentence as of press date).

### 3) Five-dimension skim (draft)

1. **Platform context** — **No** named platform; “internet” in portfolio terms is **peripheral**—ICAC is in the **agency** line, not the locus of offense. Argue **Era II = mobile + ESP era** but this case’s lesson is **institutional** (daycare, licensing) + **disclosure**, not app mechanics.
2. **Perpetrator methodology** — Sustained hands-on in trusted childcare setting; multi-year window; public worry about **additional** unknown victims.
3. **Investigative approach** — Child disclosure → multi-victim **identification**; state BCI + local + **federal task force** partnership branding.
4. **Prosecutorial outcome** — **Guilty** plea (bill of information); statutory ranges stated; **sentence** not in excerpt—**follow-up** needed for a complete “outcome” dimension.
5. **Broader era** — Differentiates the Era II set from `lapd_2017_001`: proves you can place an **Era II** label on **offline institutional** vulnerability + law-enforcement **task force** visibility without a three-app pipeline.

**Pursuit note:** **High** differentiation from existing Era II study. **Risk:** readers may ask “where is the internet?”—the study must **front-foot** the thesis (ICAC as **network**, licensing as **gap**, disclosure as **signal**).

---

## `nj_ag_2022_016` (corpus: NJ AG / DCJ) — Ventnor male-prostitution ring, trafficking, Craigslist / social, aggravated assault on minor

**Era (facet in DB):** `date_start` **2022-01-01** (treat as metadata; **narrative** is 2011–2014 **conduct** and indictment-era press, not “2022” crime tech).  
**DB:** `case_topics` `["hands_on", "multi_state", "possession"]`; `platforms_used` `["Craigslist", "Facebook", "Twitter / X", "social media"]`.

### 1) Case narrative as presented (corpus `case_text`)

```
Unit & FBI Task Force
Source: – Acting Attorney General John J. Hoffman announced that a New Jersey man was indicted today
on first-degree charges of human trafficking and aggravated sexual assault for allegedly operating a male
prostitution ring from his apartment in Ventnor, in which he allegedly gave narcotics to young men, including at
least one minor, and prostituted them to male clients. The indictment also charges a client who allegedly
sexually assaulted a minor and a third man who allegedly tried to conceal evidence.
Marc A. Branch, 40, of Ventnor, was indicted today by a state grand jury on charges of human trafficking (1st
degree), aggravated sexual assault (1st degree), conspiracy (2nd and 3rd degree), promoting organized street
crime (2nd degree), engaging in prostitution with a person under 18 (2nd degree), promoting prostitution (3rd
degree), endangering the welfare of a child (3rd degree), and maintaining a nuisance (4th degree). The
indictment is the result of an investigation by the Division of Criminal Justice Human Trafficking Unit and the
FBI Human Trafficking Task Force in Atlantic City.
Branch allegedly lured vulnerable young males, ranging in age from their teens to their early 20s, to his
apartment on North Newport Avenue by offering them money, drugs, friendship and, in some cases, shelter. He
allegedly gave them cocaine, heroin and alcohol so that he could control them and prostitute them to male
clients, who paid up to $200 per sex act. Branch allegedly solicited clients for the prostitution ring by
advertising on Craigslist with naked photos of the young males. He also allegedly used Twitter, Facebook and
other websites.
Francis H. Forvour, 47, of Maple Shade, an alleged client, was charged with Branch in the count of first-degree
aggravated sexual assault. In 2011 or early 2012, Forvour allegedly performed oral sex on a male, under 16,
who was unconscious. Branch allegedly offered the boy marijuana to smoke that was laced with another drug,
which caused him to pass out. Forvour allegedly paid Branch for that sex act. Forvour also is charged with
sexual assault on a minor (2nd degree) and endangering the welfare of a child (3rd degree) in relation to that
incident. In addition, Forvour is charged with Branch with second-degree conspiracy and engaging in
prostitution with a person under 18, and he is charged with third-degree aggravated criminal sexual contact for
allegedly fondling another young man who was asleep.
“We charge that Branch plied troubled young men with drugs in order to ensnare them in a life of prostitution,”
said Acting Attorney General Hoffman. “The level of his depravity is illustrated by the incident charged in the
indictment in which he allegedly rendered an underage boy unconscious using narcotics so Forvour could
sexually assault him, all to turn a quick profit. This type of callous sexual exploitation of the very vulnerable
fits a classic pattern of human trafficking.”
“Through new directives, training and alliances, we are focusing law enforcement throughout New Jersey on
uncovering and prosecuting these heinous crimes,” said Director Elie Honig of the Division of Criminal
Justice. “Working with partners like the FBI, our new Human Trafficking Unit will continue to coordinate
operations involving all levels of law enforcement to rescue victims and bring human traffickers to justice. We
are maintaining a high level of vigilance in the run-up to the Super Bowl, because we know that this blockbuster
event has the potential to attract these criminal elements.”
The third defendant, Shaun P. Hussey, 29, of Margate, is charged with third-degree conspiracy, along with
Branch and Forvour, for allegedly conspiring with them to try to tamper with witnesses and conceal evidence
after Branch was arrested and jailed in October 2012. The indictment alleges that Forvour attempted to phone
the minor he allegedly assaulted in an effort to convince him to give a statement exonerating Branch. It is
further alleged that Forvour called a relative of the other young man he fondled in an attempt to contact that
victim. Hussey allegedly logged onto Branch’s social media sites and deleted photos and information he
believed might incriminate Branch. Hussey also is charged with hindering the apprehension or prosecution of
another person, a third-degree offense.
Branch was arrested in this case on Oct. 19, 2012 and was initially jailed with bail set at $250,000. He currently
is serving a state prison sentence for possession of drugs. Forvour was arrested on Dec. 21, 2012. He is being
held in the Burlington County Jail with bail set at $100,000.
The first-degree charge of human trafficking carries a sentence of 20 years to life in state prison and a criminal
fine of up to $200,000. The first-degree charge of aggravated sexual assault carries a sentence of 10 to 20 years
in state prison, with a period of parole ineligibility equal to 85 percent of the sentence imposed. Second-degree
crimes carry a sentence of five to 10 years in prison and a fine of up to $150,000, while third-degree crimes
carry a sentence of three to five years in prison and a fine of up to $15,000. Fourth-degree crimes carry a
sentence of up to 18 months in prison and a fine of up to $10,000.
The indictment was handed up to Superior Court Judge Pedro J. Jimenez Jr. in Mercer County, who assigned
the case to Atlantic County, where the defendants will be ordered to appear in court for arraignment at a later
date. The indictment is merely an accusation and the defendants are presumed innocent until proven guilty.
Deputy Attorney General Russell J. Curley presented the indictment to the state grand jury for the Division of
Criminal Justice Human Trafficking Unit, within the Gangs & Organized Crime Bureau. The investigation was
conducted for the Division of Criminal Justice by Detective Naike Kudlik, Sgt. Keith Stopko, Detective Eric
Barnes, Detective Brian Christensen and Detective Terry Shaw of the Human Trafficking Unit, under the
supervision of Deputy Chief of Detectives Alex M. Adkins. Detective Scott Caponi and Lt. Ritchie King of the
Division of Criminal Justice also assisted.
Special Agent Dan Garrabrant, head of the FBI Human Trafficking Task Force in Atlantic City, led the
investigation for the FBI. The Atlantic County Sheriff’s Office and New Jersey Human Services Police assisted
as members of the Task Force. The Ventnor Police Department and Atlantic County Prosecutor’s Office also
assisted with the investigation. Acting Attorney General Hoffman thanked the National Center for Missing and
Exploited Children, the Medford Police Department and the Burlington County Prosecutor’s Office for their
valuable assistance.
The Division of Criminal Justice maintains a 24-hour NJ Human Trafficking Hotline: 1-855-END-NJ-HT
(1-855-363-6548). In addition, the Internet Crimes Against Children Task Force in New Jersey works closely
with the National Center for Missing and Exploited Children in Washington, D.C., which maintains a national,
toll-free tipline for the public to report crimes against children: 1-800-THE-LOST , or 1-800-843-5678 . That
tip line brings leads to the New Jersey ICAC on sexual crimes against children.
```

### 2) Summary of what happened (assistant)

**State grand jury** indictment: **trafficking-run prostitution** from a Ventnor apartment, **drug coercion**, **Craigslist + social** for client acquisition; a charged episode of **unconscious minor** + paying client; third defendant charged with **social-media** evidence destruction and **witness** pressure. **ICAC** appears in closing boilerplate (national tip line → NJ ICAC), but the **spine** is **human-trafficking + commercial sex on the open web**—**not** the same as gaming/Discord in `doj_2025_004` or Kik in `vt_2020_011`.

### 3) Five-dimension skim (draft)

1. **Platform context** — **Craigslist + mainstream social** as **advertising and evidence** surfaces; “platform proliferation” in Era III includes **adult** commercial infrastructure co-opted for exploitation—not only child-oriented apps.
2. **Perpetrator methodology** — Drug leverage; **commercial** prostitution; **trafficking** frame; **minor** victim; separate **obstruction** via social logins.
3. **Investigative approach** — **NJ DCJ Human Trafficking Unit + FBI** Atlantic City task force; multi-defendant, **financial** and **victim** complexity; **NCMEC** name-checked at margin.
4. **Prosecutorial outcome** — **Indictment-stage** text (accusation); not a “closed plea” document like Ohio—**narrative risk** if you need **adjudication** for your standards.
5. **Broader era** — Fills a **trafficking + CSEC-adjacent** slot for Era III, overlapping topically with `gbi_2020_002` / `vt_2020_011` on **vulnerability** and **task force** work but **not** on cybertip-queue or Kik.

**Pursuit note:** **Thematically rich**; **legally and ethically heavy**. **Caveat:** long timeline (2012 arrests, etc.) vs `2022` id—**normalize dates** in prose; may need to **tighten** to ICAC-relevant through-line or accept **borderline** “ICAC case study” (ICAC in footer, not lead agency).

---

## `idaho_icac_2024_028` (corpus: Idaho AG, July 2024) — Philip Jack Lo, new visual-representation / AI-oriented statute, “first prosecution”

**Era (facet year):** IV (2023–2026).  
**DB:** `case_topics` `["possession"]`; `platforms_used` `[]` (tags **understate** AI/synthetic law content).

### 1) Case narrative as presented (corpus `case_text`)

```
CATEGORY: ICAC, Press Releases
July 12, 2024
FOR IMMEDIATE RELEASE
Media Contact: Damon Sidur
damon.sidur@ag.idaho.gov
208-334-2400
Photo courtesy of Idaho Tourism
Newsroom Kootenai County Man Arrested for Sexual Exploitation of a Child
[BOISE] – Attorney General Raúl Labrador has announced investigators with his Idaho Internet Crimes Against Children
(ICAC) Task Force arrested thirty-three-year-old Philip Jack Lo of Coeur d' Alene on Wednesday, July 10th, 2024. Lo was
charged with 7 counts of sexual exploitation of a child by possession of sexually exploitative material and 3 counts of
possessing visual representations of the sexual abuse of children under a new law that took effect on July 1, 2024.
“I’m very proud of the hard work being done by our ICAC investigators and those agencies and ICAC partners that are
committed to protecting kids in our community,” said Attorney General Labrador. “This will be the first case prosecuted
under Idaho’s new law that targets AI-generated, animated and other obscene images of child sexual abuse. The people
who create and share these images, AI or otherwise, represent a profound threat to the safety and well-being of children
across our state.”
Agencies that assisted the ICAC Task Force were the U.S. Department of Homeland Security, Kootenai County Sheriff’s
Office, Kootenai County Prosecutor’s Office, and the Coeur d’ Alene Police Department. The Lead Investigator on the case
is Jim Bohr, a member of the Meridian Police Department assigned full-time to the Idaho ICAC Task Force who serves in
the Attorney General’s ICAC Unit.
Anyone with information regarding the exploitation of children is encouraged to contact local police, the Attorney General’s
ICAC Unit at 208-947-8700, or the National Center for Missing and Exploited Children at 1-800-843-5678.
The Attorney General’s ICAC Unit works with the Idaho ICAC Task Force, a coalition of federal, state, and local law
enforcement agencies, to investigate and prosecute individuals who use the internet to criminally exploit children.
Parents, educators, and law enforcement officials can find more information and helpful resources at the ICAC website,
ICACIdaho.org.
```

### 2) Summary of what happened (assistant)

**Post-statute** (effective **2024-07-01**) **arrest** (~July 10): **7** conventional **possession** counts + **3** under Idaho’s new **“visual representation”** provision explicitly tied in the release to **AI, animated, and other** CSAM. AG frames it as the **first** prosecution under that law. **Charging** stage; **no** sentence in this text—**presumption of innocence**.

### 3) Five-dimension skim (draft)

1. **Platform context** — **Deliberately abstract** in the release: law targets **AI-generated, animated, other** representations; **not** a single consumer app case—analogue to “**statute and file type**” as the platform story.
2. **Perpetrator methodology** — Charged as **possession-heavy** with add-on **synthetic/animated** visual-representation counts (as alleged).
3. **Investigative approach** — **Idaho ICAC** + locals + **DHS**; named lead investigator—**standard** interagency list; no CyberTip detail in excerpt.
4. **Prosecutorial outcome** — **Charging** only; **“first prosecution”** is **AG** framing—verify if you cite as fact; **disposition TBD** for a full outcome dimension.
5. **Broader era** — Pairs with **`doj_ceos_2025_025`**: **federal** “AI + known child” vs **state** “first-mover **statute** on synthetic/visual representations + possession stack.”

**Pursuit note:** **Flagship** for “**Era IV = law + enforcement catching up to synthetic**” in **state** voice. **Risks:** (1) **pre-conviction** copy; (2) **redundancy** with federal AI case if takeaway isn’t **clearly** statutory/state; (3) **`platforms_used` empty** in DB—**override in prose** from the release.

---

## Quick comparison: worth pursuing on top of the six?

| ID | Additive vs six? | Friction |
|----|------------------|----------|
| `azicac_2011_009` | **Yes** — NCMEC/AIM path; infant/CPS **crossover**; not P2P (`006`). | Outcome thin in text. |
| `ohio_ag_2017_002` | **Yes** — only **non-app** Era II institutional story in this batch. | “Where’s the internet?” must be **argued**; **sentence** follow-up. |
| `nj_ag_2022_016` | **Maybe** — **trafficking + Craigslist** broadens Era III. | **ICAC** is peripheral; **indictment** stage; id/date **messy** vs 2022. |
| `idaho_icac_2024_028` | **Yes** for **state AI statute** “first” story; complements **federal** AI study. | **Pre-disposition**; “first” claim = **sourced to AG** only. |

**Suggested handoff string for your Claude pass:** *“Given the six published CaseLinker studies (see table above) and the five-dimension frame, which of the four candidate IDs are worth full JSON authoring, and for each what is the one-sentence **takeaway** and the biggest **factual or dignity** risk?”*
