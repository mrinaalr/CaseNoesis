# Exploitation State Machine

| | |
|---|---|
| States | [`schemes/esm.json`](schemes/esm.json), in two layers; [`schemes/crosswalk.json`](schemes/crosswalk.json) places other alphabets under them; [`schemes/esm.ttl`](schemes/esm.ttl) is both as SKOS, gated |
| Input | Walks from any source: acts read from records, a `traj` graph in any alphabet, or JSON |
| Command line | `python -m state_machines {scheme, machine, invariance, decide, laws, read, report, graphs}` |
| MCP | `esm_scheme`, `esm_machine`, `esm_invariance`, `esm_decide`, `esm_laws`, `esm_read` |
| Output | `data/extracted/esm/report.json`; graphs in `data/extracted/esm/` |
| Tests | [`test_state_machines.py`](test_state_machines.py): 37 tests on planted structure, including the calibration of the nulls |

**Contents:** [Machine](#the-machine) · [States](#states) · [Other alphabets](#other-alphabets) · [Readers](#readers) · [Transitions](#transitions) · [Invariance](#invariance) · [Decision model](#decision-model) · [Backbone and laws](#backbone-and-laws) · [Exploitation predicate](#exploitation-predicate) · [Ontology](#ontology) · [Capability](#capability) · [Results](#results) · [Limits](#limits) · [Code map](#code-map)

## The machine

$$
\mathcal{M} = (S,\ A,\ T,\ R_G,\ s_0,\ F)
$$

| Symbol | Here |
|---|---|
| $S$ | The states of one layer of the scheme ([below](#states)) |
| $A$ | A kind of act (`transfer`), or an act with the technology its sentence names (`transfer[gift_card]`), plus `(stop)` |
| $T$ | $\hat{T}(s' \mid s, a)$, counted from walks |
| $R_G$ | Not estimated. A declared cost model ([below](#decision-model)) |
| $s_0$ | `start` |
| $F$ | Completed (the goal reached), Disrupted (detection narrated before it), Unresolved (the telling ends before it) |

The machine, the decision model and every test take walks and a layer. They do not depend on how the states were defined or read.

## States

A state is the condition an offense is in: what it has reached, and the leverage it holds. It is read from evidence, never from the offense's domain. States are data in [`schemes/esm.json`](schemes/esm.json): each has a layer, a definition, at most one broader state, and its links to other vocabularies.

**Milestones**, the states of the machine:

| State | Reached when | Crime script stage | CAC |
|---|---|---|---|
| Preparation | Means are set up; no victim reached | preparation | |
| InitialContact | A victim, a person or a system, is reached | entry | `grooming:InitialContactPhase` |
| Conditioning | Leverage is held before anything is taken | instrumental pre-condition | `grooming:ConditioningPhase` |
| Exploitation | Value or a person is taken, or the harm delivered | doing | `grooming:ExploitationPhase` |
| Maintenance | Leverage is held again after exploitation | doing, repeated | `grooming:MaintenancePhase` |
| Exit | Proceeds moved or traces concealed after exploitation | post-condition, exit | |

The backbone $B$ is InitialContact, Conditioning, Exploitation, Maintenance. Its states are aligned to CAC by `skos:closeMatch`: CAC defines them for child exploitation, and here they apply to every domain. Exit is Cornish's post-condition and exit; it is not in $B$.

**Tracks**, how a milestone was reached:

| Milestone | Tracks |
|---|---|
| InitialContact | Solicitation (a person approached), Recruitment (a person enlisted with an offer), Intrusion (a system entered) |
| Conditioning | Deception (cooperation under a false belief), Coercion (compliance under threat or control) |
| Exploitation | ValueTaken, PersonExploited, ContrabandSupplied |
| Maintenance | RenewedDeception, RenewedCoercion |
| Exit | Laundering, Concealment |

Coercion, once held, is not undone by a later deception. A walk whose evidence does not say how a milestone was reached stays at the milestone: a demand alone leaves it at Conditioning.

**After the goal.** Leverage held after exploitation is Maintenance; the same leverage before it is Conditioning. The scheme says this once (`after_goal`), and projection applies it from the walk's history. A source state placed under Coercion therefore becomes RenewedCoercion after exploitation, without its alphabet knowing about the goal.

## Other alphabets

The SDK's domain extensions define their own states as flat SKOS schemes, by design ("does not flatten multiple domain alphabets into one mega-S"). [`schemes/crosswalk.json`](schemes/crosswalk.json) places each under an ESM state, without changing it:

| Alphabet | Placed |
|---|---|
| SDK trafficking | Recruitment → Recruitment; Control → Coercion; Exploitation → PersonExploited; EarningsCollection → ValueTaken |
| SDK forced labor | Recruitment → Recruitment; Control → Coercion; ForcedLabor → PersonExploited |
| SDK elder fraud | InitialContact → Solicitation; Conditioning, ExtractionInstruction → Deception; ProceedsCollection → ValueTaken; Laundering → Laundering; Completed → the terminal Completed |
| SDK extortion | InitialAccess → Intrusion; Exfiltration, Demand, LeakThreat → Coercion |
| SDK layered (CSEA, transit, child sex trafficking) | Targeting → Preparation; MaterialDependency, Sexualization, CrossBorderTransit → Conditioning; CSAMLeverage, ForcedSexualExploitation → PersonExploited; PlacementControl, Harboring → Coercion |
| CAC grooming, sextortion | The five phases → their milestones; Isolation, Sexualization, TrustBuilding → Conditioning |

`closeMatch` maps a state onto the ESM state; `broadMatch` places it beneath. Each placement is a modeling claim with its reason where it is contestable: extortion's Exfiltration is placed as leverage, because in an extortion script the stolen copy is held and the ransom is what is taken.

## Readers

[`readers.py`](readers.py) turns a source into walks, the one form every analysis reads ([`walks.py`](walks.py)): events, each an action and the finest state it left the offense in, and whether the telling ended or detection was narrated.

| Reader | Reads | States |
|---|---|---|
| `from_conduct` | Acts read from a record | Track states, by the act's role (below) |
| `from_graph` | Every `traj:Trajectory` in a graph | The graph's own; placed by the crosswalk or by the graph's own `skos:broadMatch`, `closeMatch` or `broader`; otherwise kept and reported as unplaced |
| `from_json` | Walks from any other extractor | Any, with extra states declared beside them |

Acts reach states by role:

| Role | Acts | Reaches |
|---|---|---|
| prepare | setup | Preparation, from `start` |
| reach | contact, recruit, access | Solicitation, Recruitment, Intrusion, from `start` or Preparation |
| deceive | deception | Deception, unless coercion is held |
| coerce | threat, control | Coercion |
| press | demand, transport | The leverage already held; Conditioning if none |
| extract | transfer, exploit | ValueTaken, PersonExploited |
| deliver | supply | ContrabandSupplied |
| after | movement, concealment | Laundering, Concealment, after the goal; no change before |

A graph's own terminal polarity is kept beside the walk. Where it says "completed" for a chain that never reaches the goal, the reader reports the disagreement instead of taking either side.

## Transitions

$$
\hat{T}(s' \mid s, a) = \frac{n(s, a, s')}{n(s, a, \cdot)}
$$

reported with $n(s, a, \cdot)$. Detection narrated right after an act is that act's outcome. It ends in Completed if the goal had been reached, Disrupted if not.

**Action space.** $A(s)$: acts taken at $s$ at least 5 times and in at least 1% of departures, plus `(stop)`. The cutoff changes no result: see [Results](#results).

## Invariance

The claim: domains share states, and technology enters through the actions. If so, domains should look alike in how they move between milestones, and differ in which acts, and which technologies, they use to do it. [`invariance.py`](invariance.py).

| Level | Distribution per domain |
|---|---|
| states | Transitions between states, $s \to s'$ with $s' \ne s$ |
| acts | The act taken at each state, $(s, a)$ |
| means | The act and its technology at each state, $(s, a[\text{means}])$ |

For each level, the mean Jensen-Shannon divergence between domains (bits) is set beside the divergence with domain labels shuffled, on equal-size subsamples, so a large domain does not look distinct only by being large.

Setting the levels beside one another does not test the claim. States are computed by grouping acts, and a coarser grouping of any data diverges less than a finer one: random act sequences, with no order and no backbone, give the same ordering of levels. Tracks are a finer grouping than milestones and diverge more for the same reason. Two nulls test it, each scored on the same equal-size subsample as the observed value, 200 times:

| Null | What changes | The claim predicts |
|---|---|---|
| Grouping | Act kinds reassigned to roles at random, keeping how many kinds each role has | The scheme's grouping leaves less state-level divergence between domains than a random grouping |
| Order | Each record's acts shuffled | Observed state-level divergence below that with order shuffled, if it comes from how domains move through states and not only from which acts they use |

## Decision model

[`mdp.py`](mdp.py). The decision state carries whether the goal, Exploitation or any state beneath it, has been reached, so the goal pays once.

$$
R\big((s, r), a, s'\big) = -c_\kappa(a) \;+\; v\,[s' \in G \wedge r = 0] \;-\; d\,[s' = \text{Disrupted}]
$$

| Cost model | $c(a)$ | Encodes |
|---|---|---|
| `uniform` | 1 per act, 0 for `(stop)` | "Offenders are direct" |
| `declared` | 1 plus the mean of four friction levels in `config/esm_costs.json` (template: [`esm_costs.example.json`](esm_costs.example.json)) | "Offenders take the easiest path", with ease set by the researcher |

Value iteration ($\gamma = 0.95$) gives $Q^*$, the optimal policy, and $L^*$, at either layer. The model is fitted to walks told from preparation or contact. A telling that begins at the payment, as many releases do, would put a taking act among the first moves and make a one-act path to the goal feasible by construction; those walks are reported beside, not tested. Tests:

- **Rationality.** $P(a \mid x) \propto \exp(\beta\, Q^*(x, a))$, $\beta$ fitted over $[-20, 20]$ to every observed choice among two or more options, compared with $\beta = 0$ and with 200 random cost models. A negative $\beta$ means choices lean away from the optimum. A random model counts as fitting better only when strictly better; ties, which every pair of models at $\beta = 0$ produces, are reported apart.
- **Agreement.** Share of choices that are the optimal action, beside always taking each state's most common action.
- **Sensitivity.** All results under nine feasibility cutoffs.

## Backbone and laws

[`coverage.py`](coverage.py). Laws are measured at the milestone layer, on walks that reach the goal. Each names its states by the scheme's roles, so a scheme without a role skips that law.

| Measure | Definition |
|---|---|
| Backbone at $\theta$ | States occupied by at least $\theta$ of walks in every domain |
| Contact primacy | InitialContact before Exploitation |
| Full backbone | InitialContact and Conditioning both before Exploitation |
| Maintenance | Maintenance after Exploitation |
| Re-entry | Exploitation entered more than once |
| Exit | Exit after Exploitation |
| $\kappa_d(b)$ | Share of completed walks that avoid state $b$. 0: every completed path went through $b$ |
| Tracks | For each milestone a domain reached, the share of its walks at each track beneath it |

## Exploitation predicate

A walk is exploitative when the victim is the source of what the offender takes. Each goal state says whether it is (`victim_is_source`): ValueTaken and PersonExploited do, ContrabandSupplied does not. `passes`, `fails` (only states where the victim is not the source), `unspecified` (a goal state that does not say), or `not_reached`.

## Ontology

[`ontology.py`](ontology.py) writes in the SDK's `trajectories` (0.3.1) and `means` (0.1.0) extensions. Every graph passes the SDK gate.

| Object | Class |
|---|---|
| Scheme | `skos:ConceptScheme`; [`schemes/esm.ttl`](schemes/esm.ttl), publishable |
| State | `traj:State` and `skos:Concept`, with `skos:broader`, `skos:definition`, and its CAC and other links |
| Another alphabet's state | Its own IRI, with `skos:broadMatch` or `skos:closeMatch` to the ESM state |
| Act | `traj:PhaseAssertion`: the finest state it reached, its place, its interval, its confidence, its record |
| Last act | `isTerminal`, `terminalPolarity` "completed" or "disrupted"; none when unresolved |
| Telling | `traj:Trajectory` |
| Step | `traj:Transition`, enacting a `uco-action:Action` with the technology as `uco-action:instrument` |
| Goal | `means:Goal`: reach Exploitation |
| Act by a technology | `means:Option`, one per technology |
| Ability to use it | `means:OffenderCapability`, evidenced by use |
| Fitted machine | `traj:StateMachineModel` at one layer, with one `traj:TransitionEstimate` per $(s, a, s')$ |

Not written: reward, value, policy (`means` records none by design); `means:Selection` (a record shows the option taken, not the menu); `means:OptionAssessment` (frictions are not in a record).

## Capability

[`capability/`](capability/): a sketch of the Capability class proposed in [UCO issue 682](https://github.com/ucoProject/UCO/issues/682), to offer upstream.

| File | Holds |
|---|---|
| `capability.ttl` | `cap:Capability`, `cap:structuredCharacterization` to a `uco-action:ActionPattern`, `cap:capabilityScope`; re-parents `means:OffenderCapability` onto it |
| `capability-shapes.ttl` | At most one characterization, and it is an action pattern |
| `capability-exemplar.ttl` | One capability from a gold statement of offense, as the stand-in and as the proposal's form |
| `capability-invalid-exemplar.ttl` | Must fail its shapes |

## Results

2026-11-14, collected corpus (45,877 records), rules only, offense domains. Full figures in `report.json`.

**What the claims come to.** No claim is supported yet. Each is set against a null that could fail it:

| Claim | Test | Result |
|---|---|---|
| States hold while actions vary | State-level divergence between domains against random groupings of acts into roles, on 200 paired subsamples | Not separable from a random grouping. The scheme's grouping leaves less divergence than a random one in 0.88 of draws for five domains, 0.68 for fraud and trafficking, 0.50 for court filings. On random data with no structure this share ranges up to 0.85 (mean 0.50); a share near 0.95 would count |
| | The same against shuffled act order | Domains differ in how they move between states more than their act mix explains: fraud and trafficking are above shuffled order in every draw. This is evidence against states being shared |
| Offenders are direct | $\beta$ under uniform costs on walks told from the start, against 200 random cost models | Not supported. $\beta = -0.10$: choices lean slightly away from the shortest path; 27% of random cost models fit better. Under the strictest cutoff (5% of departures) the action space shrinks, $L^*$ is to stop, and $\beta = +0.45$ |
| A backbone recurs | Coverage of each milestone in every domain | No milestone is in half of walks in every domain. In court filings, only Conditioning is |
| The exploitation predicate separates exploitation from other harm | Of walks reaching exploitation, the share that fail (reached only by supply) | Drugs 58%, firearms 83%; fraud 4%, trafficking 6%, CSEA, cyber and forced labor 2 to 5%. Drug and firearm figures rest on 24 and 26 walks |

**Machine.** 20,570 walks, 83,901 steps at the milestone layer. Ends: 4,958 Completed, 1,278 Disrupted, 14,334 Unresolved. Most walks never reach exploitation: since a transfer requires the person harmed as payer ([`acts.py`](../extraction/acts.py)), a release that reports only how the offender moved money has no exploitation step.

**Invariance**, excess divergence over shuffled domain labels, bits. Each cell is read against its own baseline, not against the other cells:

| | Layer | States | Acts | Means |
|---|---|---:|---:|---:|
| Five domains, 97 walks each | milestone | 0.106 | 0.305 | 0.109 |
| | track | 0.312 | 0.327 | 0.098 |
| Fraud and trafficking, 1,500 each | milestone | 0.117 | 0.429 | 0.526 |
| | track | 0.488 | 0.541 | 0.501 |
| Court filings, three domains, 73 each | milestone | 0.063 | 0.170 | 0.126 |
| | track | 0.208 | 0.224 | 0.129 |

**The nulls**, state-level excess, mean over 200 paired draws (40 for fraud and trafficking):

| | Layer | Observed | Random grouping (5th to 95th percentile) | Shuffled order | Draws observed below random grouping | below shuffled order |
|---|---|---:|---:|---:|---:|---:|
| Five domains | milestone | 0.106 | 0.154 (0.091 to 0.227) | 0.102 | 0.88 | 0.36 |
| | track | 0.310 | 0.285 (0.222 to 0.338) | 0.298 | 0.26 | 0.18 |
| Fraud and trafficking | milestone | 0.116 | 0.159 (0.026 to 0.265) | 0.098 | 0.68 | 0.00 |
| | track | 0.485 | 0.415 (0.287 to 0.520) | 0.492 | 0.20 | 0.88 |
| Court filings | milestone | 0.059 | 0.061 (0.019 to 0.112) | 0.035 | 0.50 | 0.06 |
| | track | 0.205 | 0.168 (0.119 to 0.228) | 0.183 | 0.14 | 0.18 |

**How milestones are reached.** Of the walks reaching each milestone, the share reaching it by each track, all records. This describes the data; it does not test the claim, since tracks are a finer grouping:

| | Fraud | Trafficking | CSEA | Cyber |
|---|---:|---:|---:|---:|
| Conditioning by deception | 79% | 3% | 8% | 20% |
| Conditioning by coercion | 6% | 52% | 36% | 27% |
| Exploitation by value taken | 80% | 9% | 2% | 68% |
| Exploitation of a person | 20% | 87% | 96% | 30% |
| Contact by intrusion | 15% | 1% | 11% | 56% |

**Decision model**, uniform costs:

| | Told from the start | All walks | Court filings, from the start |
|---|---:|---:|---:|
| Walks | 6,824 | 20,570 | 234 |
| $L^*$ | `recruit` → `transfer` | `transfer` | `recruit` → `transfer` |
| Observed median length | 3 acts | 3 acts | 4 acts |
| $\beta$ | −0.096 | −0.158 | −0.032 |
| Random cost models fitting better | 27% | 26% | 62% |
| Optimal action taken | 18% | 9% | 8% |

**Laws**, court filings, walks reaching Exploitation:

| | Fraud (94) | Trafficking (32) | Cyber (37) |
|---|---:|---:|---:|
| Contact primacy | 35% | 22% | 62% |
| Full backbone | 20% | 13% | 32% |
| Maintenance | 52% | 81% | 62% |
| Re-entry | 31% | 28% | 41% |
| Exit | 70% | 34% | 76% |

**Other alphabets.** The SDK's layered exemplar (four layers in four alphabets) reads with every state placed. Three of its layers reach exploitation and are marked `disrupted`, for the arrest that ended them; here they end Completed, and the reader reports each disagreement.

**Graphs.** The scheme graph passes the SDK gate as publishable. Trajectory and model graphs for court filings are being validated again after a fix to walks whose first act reaches nothing; this line gives the count when that run ends.

**Gold statements** (held-out half): state paths exact for 19 of 22 plain tellings and 1 of 18 paraphrased; predicate correct for 27 of 40.

## Limits

These are measurements over what records narrate.

- **Reward.** Only `uniform` has been tested; "easiest path" needs a researcher's cost table.
- **Telling.** A record often begins at the payment, so missing early states (low contact primacy) can be states the telling skipped. Court filings tell more and are reported separately.
- **Acts.** Read by a list of verbs; about three in ten are missed, and paraphrased tellings are rarely read whole. Tracks inherit this. `recruit` also reads the enlisting of accomplices, so Recruitment is overcounted where offenders recruit each other, as in fraud. A payment's direction is read from the words before its verb: right for 43 of 48 payments in a developer's audit of 60, and 7 of the 60 were not payments.
- **Nulls.** A single comparison against random groupings can land anywhere between 0 and 0.85 on data with no structure; only a share near 0.95 counts as evidence for a grouping.
- **Placements.** The act roles and the crosswalk are modeling choices, stated in one file each, and every result depends on them.
- **Order.** The order of telling.
- **Unit.** One record's telling, not a case's or one defendant's.
- **Domain.** The collector's search term, not the charge.
- **Levels.** Divergences at different levels and layers have different numbers of categories; compare each with its own shuffled baseline, not with each other directly.
- **Release.** $L^*$ and $Q^*$ are published only at the level of states and kinds of act, from closed public cases.
- **Dissections.** None yet.

## Code map

| File | What it does |
|---|---|
| [`scheme.py`](scheme.py) | Schemes: states, layers, hierarchy, projection, the goal, the crosswalk |
| [`walks.py`](walks.py) | Walks: steps and paths at a layer, the exploitation predicate |
| [`readers.py`](readers.py) | Acts, graphs and JSON into walks |
| [`machine.py`](machine.py) | The fitted machine: counts, $\hat{T}$, action space, observed policy |
| [`invariance.py`](invariance.py) | Domains compared at the state, act and means levels against shuffled labels |
| [`mdp.py`](mdp.py) | Cost models, value iteration, $L^*$, rationality, agreement, cutoff sensitivity |
| [`coverage.py`](coverage.py) | Backbone, laws, intervention, tracks, predicate by domain |
| [`ontology.py`](ontology.py) | Scheme, trajectory and model graphs; the gate |
| [`analysis.py`](analysis.py) | Each analysis as one call, for the command line and the MCP server |
| [`schemes/`](schemes/) | The ESM scheme, the crosswalk, and the scheme as SKOS |
| [`capability/`](capability/) | The capability sketch |
| `bellman.py`, `compute_lstar.py`, `iris.py`, `lifecycle_api.py`, `sparql_queries.py`, `trajectory.py`, `graphs/`, `data/` | Earlier lifecycle model, read only by the researcher site in `run/`. To be removed |
