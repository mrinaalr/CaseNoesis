# CaseLinker — draft pool for additional case studies (R1 / handoff)

**Purpose:** Triage corpus IDs against the **case studies already authored** in `data/case_studies.json`, using the same **five analytical dimensions** the reading room uses. **Earlier batch:** `azicac_2011_009`, `ohio_ag_2017_002`, `nj_ag_2022_016`, `idaho_icac_2024_028`. **Added here:** `illinois_ag_2016_001` (Era II), `ut_ag_2022_010` (Era III).

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

## `illinois_ag_2016_001` (corpus: Illinois AG, April 2016) — Operation Glass House, dissemination + possession stack, infant-focused initiative frame

**Era (facet year):** II (2015–2018).  
**DB:** `case_topics` `["possession", "csam"]`; `severity_indicators` `["sexual_abuse", "infant"]`; `platforms_used` `["online"]` (generic—release emphasizes **download/trade online**, not a named consumer app).

### 1) Case narrative as presented (corpus `case_text`)

```
April 15, 2016
MADIGAN: KANE COUNTY MAN CHARGED WITH CHILD PORNOGRAPHY POSSESSION

Chicago — Attorney General Lisa Madigan today announced that a Kane County man was charged with disseminating child
pornography as part of “Operation Glass House,” a statewide initiative to apprehend the most active offenders
who download and trade child pornography online. Omar Rojas-Martinez, 27, of Aurora, was charged in Kane County Circuit Court with three
counts of dissemination of child pornography, Class X felonies punishable by 6 to 30 years in the Illinois
Department of Corrections (IDOC), and 10 counts of possession of child pornography, Class 2 felonies
punishable by three to seven years in prison. Rojas-Martinez is being held in Kane County Jail pending a bond
hearing.

“When an offender downloads or trades these horrific images, it perpetuates the sexual assault of
children and causes further devastation to victims,” Madigan said. “We will continue to apprehend these
offenders.”

Madigan’s investigators, with the assistance of the U.S. Department of Homeland Security-Homeland Security Investigations,
the Aurora Police Department and the Kane County State’s Attorney’s Office, conducted a search of a residence in the
300 block of Broadway Avenue in Aurora Friday and arrested Rojas-Martinez after evidence of alleged child pornography
was discovered. Kane County State’s Attorney Joseph McMahon’s office will prosecute the case.

The public is reminded that the defendant is presumed innocent until proven guilty in a court of law.

This is the 79th arrest since Madigan launched “Operation Glass House” in August 2010 to investigate the most active
child pornography traders in Illinois. In 2010, the first year of the initiative, Madigan’s investigations revealed a
disturbing trend of offenders trading extremely violent videos of young children being raped. As a result,
Madigan’s office has focused on apprehending offenders who are seen trading and watching extremely violent videos
involving children, including infants and toddlers.

Madigan’s office, with a grant from the U.S. Department of Justice, runs the Illinois Internet Crimes Against Children
(ICAC) Task Force, which investigates child exploitation crimes and trains law enforcement agencies.
```

### 2) Summary of what happened (assistant)

**Statewide initiative arrest:** Illinois AG frames charges under **Operation Glass House** (since **2010**, **79th** arrest in corpus text)—**3 × dissemination** (Class **X**) + **10 × possession** (Class **2**) against a **27-year-old** Aurora defendant; **Friday** search of a **Broadway Ave** residence with **HSI**, **Aurora PD**, **Kane County SA**; **jail / bond hearing** stage only. Release explicitly ties initiative priorities to **violent** material involving **very young children, including infants and toddlers**—explains **`infant` / `sexual_abuse`** severity tags without hands-on allegations in excerpt.

### 3) Five-dimension skim (draft)

1. **Platform context** — **Trade/download online** as the operational story; **`online`** tag only—no named forum, messenger, or P2P brand in excerpt (contrast **`lapd_2017_001`**).
2. **Perpetrator methodology** — **Possession + dissemination** charging stack; AG rhetoric links trading to **continued harm** to victims; **no** victim-contact narrative in excerpt.
3. **Investigative approach** — **Illinois ICAC** (DOJ grant) + **HSI** + local PD + county prosecutor—standard **federal–state–local** bundle with **residential search**.
4. **Prosecutorial outcome** — **Charging + custody** only; statutory ranges quoted; **presumption of innocence** boilerplate—disposition **off-corpus** for a finished study.
5. **Broader era** — **Era II institutional** mirror: named **multi-year state operation** with **explicit infant/toddler** prioritization language—substantively thicker than a one-paragraph warrant blotter; pairs with **`ohio_ag_2017_002`** (non-app Era II) as **AG-led initiative + charge geometry** teaching material.

**Pursuit note:** Solid **Era II institutional** depth—**named operation**, **charge mix**, **infant/toddler prioritization** rhetoric; still **thin on technical stack** and **final outcome**. **Dignity:** excerpt names defendant—omit or neutralize in any **published** reading-room JSON per site gate.

---

## `ut_ag_2022_010` (corpus: Utah AG / Roosevelt PD composite, March 2022) — Oculus contact surface, interstate recovery, VR parenting advisory

**Era (facet year):** III (2019–2022).  
**DB:** `case_topics` `["online_only", "multi_state"]`; `platforms_used` `["Kik", "Snapchat", "TikTok", "WhatsApp", "chat", "online", "social media"]` (**many entries come from the embedded “popular apps” appendix**, not only the core offense narrative—treat DB tags as **noisy** for this row).

### 1) Case narrative as presented (corpus `case_text`)

```
Roosevelt 13 Year Old Returned Home After ICAC Investigation

Source: — The Roosevelt Police Department led an investigation assisted by the Utah Attorney General’s Office,
Uintah County Sheriff’s Office, the FBI, and other law enforcement and in conjunction with tech company Meta,
in arresting 25-year-old Chris Evans, a Florida trucker who had kidnapped 13-year-old Rylie Secrest after meeting her online.

MISSING CHILD HAS BEEN LOCATED RYLIE SECREST was located at 3:39 p.m. on March 10, 2022, in Cheyenne,
Wyoming. Rylie was found by the Cheyenne City Police Department in the back of a white bobtail semi-truck being
driven by Chris Evans, 25 of Florida. Roosevelt City Police Officers, in cooperation with the Utah Internet Crimes
Against Children Task Force (ICAC), the Federal Bureau of Investigations (FBI), Utah State Bureau of Investigations,
National Center for Missing and Exploited Children, and the Uintah County Sheriff’s Department obtained suspect
information and also determined an approximate location of Evans using data from cell phones and communication apps.
Investigators have determined Rylie communicated with Evans using Oculus, a Meta program, for approximately one month.
This is one of the first instances of a case involving Oculus in the nation. Rylie was located by Cheyanne police within
one hour of identifying Evans as a suspect. Rylie appears to be in good health. An investigation regarding kidnapping
and harboring runaway charges against Evans is underway.

Precautions for Parents and Teens [lengthy public-education appendix on gaming, VR chat rooms, and a catalog of
consumer apps — MeetMe, WhatsApp, TikTok, Snapchat, Kik, etc. — continues in full corpus text]
```

### 2) Summary of what happened (assistant)

**Interstate missing-child resolution:** Utah/Roosevelt-led stack (+ ICAC, FBI, NCMEC, Uintah SO, **Meta**) identifies a **Florida** suspect; **cell/app data** narrows location; **Wyoming** police recover the **13-year-old** from a **semi-truck** within **~1 hour** of suspect ID. Release highlights **~1 month** of contact via **Oculus (Meta)** and claims **early national visibility** for **VR** in this enforcement genre. **Charges described as under investigation** in excerpt—**not** a closed adjudication snapshot.

### 3) Five-dimension skim (draft)

1. **Platform context** — **VR / Oculus** as alleged **contact and grooming surface**—distinct from flat mobile messaging cases; DB **`platforms_used`** is **polluted** by appended **parent-warning app list** → author should **anchor** on Oculus + LE narrative, not every extracted token.
2. **Perpetrator methodology** — **Cross-country trucker** + **online-first** meeting → **physical removal** / transport idiom; press emphasizes **speed** of geo-acuity once suspect locked.
3. **Investigative approach** — **Multi-agency + vendor (Meta)** cooperation; **phone/app telemetry** and **ICAC** coordination across **UT → WY** (and FL resident suspect)—textbook **Era III proliferation** story (many actors, many tools).
4. **Prosecutorial outcome** — **Open investigation** language for **kidnapping / harboring runaway**; **no** sentence—good **recovery** outcome for victim **health**, **legal outcome TBD** for study completeness.
5. **Broader era** — Positions **gaming / VR social** as an emerging **ICAC-visible** layer in **2022**—bridges **Era III platform sprawl** toward **metaverse-adjacent** risk discourse without jumping to **Era IV synthetic CSAM** framing.

**Pursuit note:** **High distinctiveness** on **Oculus** thread; **watch** **dignity** (minor named in release—CaseLinker published studies omit offender names; align minor naming with your ethics gate); **truncate** or **footnote** the **generic app glossary** when authoring JSON.

---

## Quick comparison: worth pursuing on top of the six?

| ID | Additive vs six? | Friction |
|----|------------------|----------|
| `azicac_2011_009` | **Yes** — NCMEC/AIM path; infant/CPS **crossover**; not P2P (`006`). | Outcome thin in text. |
| `ohio_ag_2017_002` | **Yes** — only **non-app** Era II institutional story in this batch. | “Where’s the internet?” must be **argued**; **sentence** follow-up. |
| `nj_ag_2022_016` | **Maybe** — **trafficking + Craigslist** broadens Era III. | **ICAC** is peripheral; **indictment** stage; id/date **messy** vs 2022. |
| `idaho_icac_2024_028` | **Yes** for **state AI statute** “first” story; complements **federal** AI study. | **Pre-disposition**; “first” claim = **sourced to AG** only. |
| `illinois_ag_2016_001` | **Yes** — **Operation Glass House** + **ICAC/HSI** stack; **dissemination vs possession** charge mix; infant-priority **policy** frame. | **Generic** `online`; defendant **named** in source; **pre-disposition** only. |
| `ut_ag_2022_010` | **Maybe → Yes** if **Oculus / VR** angle is the spine—**rare** in corpus. | **Noisy** DB platforms from **appendix**; minor **named** in source; **open** investigation language. |

**Suggested handoff string for your Claude pass:** *“Given the six published CaseLinker studies (see table above) and the five-dimension frame, which of the six candidate IDs are worth full JSON authoring, and for each what is the one-sentence **takeaway** and the biggest **factual or dignity** risk?”*
