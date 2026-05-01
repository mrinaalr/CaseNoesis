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
