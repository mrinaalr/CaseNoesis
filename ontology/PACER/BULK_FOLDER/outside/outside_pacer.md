# Outside ICAC PACER Selection — Case Type Shopping List for CASE/UCO SDK Modeling
**Prepared for:** Cory Hall, Project VIC International  
**Prepared by:** Mrinaal Ramachandran  
**Date:** June 24, 2026  
**Target:** ~9 terminated federal cases (2022–2024), rich factual records for CASE/UCO ontology modeling  
**Budget:** ~$45 of PACER budget (pull docket + indictment, plea agreement, sentencing memo per case)

---

## Pull Strategy

For each case:
1. Confirm via DOJ press release → get defendant name + district + case number
2. Go to **Court CM/ECF Lookup** → search district + defendant name → confirm docket
3. Pull in order: **(1) Indictment/Information → (2) Plea Agreement → (3) Sentencing Memo**

---

## Tier 1 — Pull First (Easiest Finds, Richest Records)

| # | Crime Type | Selected Case | Defendant | District | Case No. | Key Charge | DOJ Press Release | Why This Case |
|---|---|---|---|---|---|---|---|---|
| 1 | **Cryptocurrency** | *United States v. Lichtenstein* | Ilya Lichtenstein (+ Heather Morgan) | D.D.C. | 1:23-cr-00239 | 18 U.S.C. § 1956(h) — Money Laundering Conspiracy | [Sentencing (Nov 2024)](https://www.justice.gov/usao-dc/pr/bitfinex-hacker-sentenced-money-laundering-conspiracy-involving-billions-stolen) | Bitfinex hack, 119,754 BTC (~$3.6B). Chain hopping, mixers, darknet markets, fictitious identities, Bitcoin ATMs. Textbook digital artifact chain for CASE/UCO. Plea agreement has full statement of facts. |
| 2 | **Espionage / NDI** | *United States v. Teixeira* | Jack Douglas Teixeira | D. Mass. | 1:23-cr-10159 | 18 U.S.C. § 793(e) — Willful Retention & Transmission of NDI (6 counts) | [Sentencing (Nov 2024)](https://www.justice.gov/usao-ma/pr/former-air-national-guardsman-sentenced-15-years-prison-unlawfully-disclosing-classified) | Air National Guard Discord leaks. Classified workstation access, document photographing, SCI spillage. Clean closed docket, 15-year sentence. Best NDI/insider-access case in recent federal record. |
| 3 | **Racketeering (RICO / Cyber)** | *United States v. Lam et al.* | Malone Lam + 12+ co-defendants ("Social Engineering Enterprise") | D.D.C. | 1:24-cr-00417 | 18 U.S.C. § 1962(d) — RICO Conspiracy; 18 U.S.C. § 1956 — Money Laundering; 18 U.S.C. § 1343 — Wire Fraud | [Sentencing (Apr 2026)](https://www.justice.gov/usao-dc/pr/california-money-launderer-sentenced-dc-70-months-role-scheme-stole-263-million)  [Indictment Charges (Sept 2024)](https://www.justice.gov/usao-dc/pr/indictment-charges-two-230-million-cryptocurrency-scam) | Textbook cyber RICO. Enterprise formed from online gaming friendships, stole $263M+ in Bitcoin via social engineering. Formally charged as RICO with explicit role differentiation in indictment: database hackers, organizers, target identifiers, callers, money launderers, residential burglars (physical hardware wallet theft). Rich concepts for CASE/UCO modeling. |
| 4 | **Elder Fraud** | *United States v. Keel* | Christopher L. Keel | E.D. La. | 2:22-cr-00115 | 18 U.S.C. § 1349 — Conspiracy to Commit Wire Fraud; 18 U.S.C. § 912 — Impersonation of Federal Officer | [Sentencing (Oct 2023)](https://www.justice.gov/usao-edla/pr/florida-man-sentenced-10-years-prison-impersonating-federal-officers-nationwide-elder) | Nationwide scheme, impersonated Treasury agents, targeted 77-year-old victim, in-person cash pickup. Three documented victims ($60k Green Dot cards, $300k cash pickup, $36k withdrawal). Documented co-conspirator + travel trail (Seattle → New Orleans, plane tickets same credit card). Sting operation arrest on pickup attempt. Clean victim → phone call → impersonation → cash delivery → arrest chain. 125-month sentence. |

---

## Tier 2 — Pull Session 2 (Findable, Slightly More Specific Search)

| # | Crime Type | Selected Case | Defendant | District | Case No. | Key Charge | DOJ Press Release | Why This Case |
|---|---|---|---|---|---|---|---|---|
| 5 | **Insider Threat** | *United States v. Linwei Ding* | Linwei Ding ("Leon Ding") | N.D. Cal. | 3:24-cr-00141 | 18 U.S.C. § 1831 — Economic Espionage (7 counts); 18 U.S.C. § 1832 — Theft of Trade Secrets (7 counts) | [Conviction (Jan 2026)](https://www.justice.gov/opa/pr/former-google-engineer-found-guilty-economic-espionage-and-theft-confidential-ai-technology) | Google AI engineer, thousands of pages of AI trade secrets uploaded to personal cloud. Tensor Processing Unit designs, supercomputer architecture. Secretly affiliated with two PRC companies. First-ever conviction on AI-related economic espionage charges. |
| 6 | **Export Control** | *United States v. Chen* | Lin Chen | N.D. Cal. | — | 50 U.S.C. § 1705 (IEEPA) — Conspiracy to Illegally Export Semiconductor Manufacturing Machine | [Plea (Oct 2024)](https://www.justice.gov/usao-ndca/pr/chinese-national-pleads-guilty-illegally-exporting-semiconductor-manufacturing-machine) | Semiconductor wafer processing equipment exported to China. IEEPA violation, BIS Entity List. Technical artifact detail (equipment specs, shipping falsification) and rich for CASE/UCO export chain. |
| 7 | **Murder for hire** | *United States v. Grayson* | Ashley Grayson | W.D. Tenn. | 2:23-cr-20121 | 18 U.S.C. § 1958 — Use of Interstate Facility in Commission of Murder-for-Hire | [Sentencing (Nov 2024)](https://www.justice.gov/usao-wdtn/pr/texas-woman-sentenced-10-years-imprisonment-connection-murder-hire-plot) | Online business rivalry escalated to murder-for-hire. Grayson offered Memphis couple at least $20,000 each to kill three people: a Southaven, MS business competitor, her former boyfriend, and a Texas woman who posted negatively about her online. September 10, 2022 video-recorded call documents Grayson confirming intent and offering $5,000 bonus for killing within the week. Grayson paid $10,000 cash in Dallas for a staged "attempt." Week-long jury trial March 2024 — Joshua Grayson acquitted, Ashley convicted. Sentenced October 31, 2024 to 120 months (statutory maximum). Investigated by FBI and ATF. |

---

## Tier 3 — Pull Session 2 or 3 (Harder Finds, Specific Search Required)

| # | Crime Type | Selected Case | Defendant | District | Case No. | Key Charge | DOJ Press Release | Why This Case / Search Note |
|---|---|---|---|---|---|---|---|---|
| 8 | **Kidnapping** | *United States v. Maez-Schaack* | Kyle Kahalehili Maez-Schaack | D.N.D. | — | 18 U.S.C. § 1201 — Kidnapping; 21 U.S.C. § 846 — Drug Trafficking Conspiracy; 18 U.S.C. § 924(c) — Brandishing Firearm During Kidnapping | [Sentencing (June 2026)](https://www.justice.gov/opa/pr/man-sentenced-kidnapping-victim-gunpoint-and-seeking-ransom-drug-debt) | Textbook interstate kidnapping-for-ransom. Victim taken at gunpoint from Fargo, ND to Moorhead, MN to collect a $6,000 drug debt. Multiple co-conspirators with role differentiation (orchestrator, transport, confinement). Ransom calls to family documented. Victim escape. 30-year sentence. Guilty plea Feb 2026 — plea agreement has full offense conduct stipulation. Rich actor → location → communication → victim chain for CASE/UCO. |
| 9 | **Assault + Attempted Murder (Federal)** | *United States v. Perry & O'Dell* | Bryan C. Perry + Jonathan S. O'Dell | W.D. Mo. | — | 18 U.S.C. § 111(a)(b) — Assault on Federal Officers (×10 counts); 18 U.S.C. § 1117 — Conspiracy to Murder Federal Officers; 18 U.S.C. § 924(c) — Use of Firearm in Furtherance (×14 counts) | [Sentencing (Aug 2025)](https://www.justice.gov/usao-wdmo/pr/militia-members-sentenced-conspiracy-murder-border-patrol-officers-attempted-murder) | Co-founders of "2nd American Militia" conspired to murder Border Patrol agents at the southern border, then fired 11 shots at FBI agents executing a search warrant. TikTok recruitment videos, stolen firearms, body armor, gas masks — full digital + physical observable chain. Multi-actor role differentiation (Perry: triggerman/recruiter; O'Dell: local organizer). Conspiracy to "go to war with U.S. Border Patrol", attempted murder of federal agents, escaped from Phelps County Jail on Sept 29, 2023 and led a high-speed chase before recapture. 9-day jury trial = exceptionally detailed factual record in sentencing memos. Perry sentenced to 15 consecutive life terms; O'Dell to 165 years. Fully terminated, no pardon issues. |

---

## Notes on sampling

**Why these cases for CASE/UCO SDK:** Each was selected for artifact and actor richness, not just conviction type. For ontology modeling, the most useful documents are plea agreements with factual stipulations (signed admissions of conduct) and sentencing memos (narrative reconstructions). These give clean actor → action → evidence → victim chains that map directly to CASE/UCO object types.

**Espionage note:** Though charged under 18 U.S.C. § 793 (NDI), not classic espionage statutes (§ 794 — transmitting to foreign government), this is the strongest recent case for modeling classified information handling, access control bypass, online platform usage (Discord), and insider NDI flow. A § 794 EDVA case (foreign agent) can be added if needed.





```