# Exploitation State Machine

| | |
|---|---|
| States | [`schemes/esm.json`](schemes/esm.json), in two layers; [`schemes/crosswalk.json`](schemes/crosswalk.json) places other alphabets under them; [`schemes/esm.ttl`](schemes/esm.ttl) is both as SKOS, gated |
| Input | Walks from any source: acts read from records, a `traj` graph in any alphabet, or JSON |
| Command line | `python -m state_machines {scheme, machine, invariance, decide, laws, read, report, graphs}` |
| MCP | `esm_scheme`, `esm_machine`, `esm_invariance`, `esm_decide`, `esm_laws`, `esm_read` |
| Output | `data/extracted/esm/report.json`; graphs in `data/extracted/esm/` |
| Tests | [`test_state_machines.py`](test_state_machines.py): 29 tests on planted structure |

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

2026-11-14, collected corpus, rules only, offense domains. Full figures in `report.json`.

**Machine.** 20,813 walks, 87,156 steps at the milestone layer. Ends: 10,676 Completed, 917 Disrupted, 9,220 Unresolved.

**Invariance.** Excess divergence over shuffled labels, bits:

| | Layer | States | Acts | Means |
|---|---|---:|---:|---:|
| Five domains, 97 walks each | milestone | 0.089 | 0.301 | 0.106 |
| | track | 0.323 | 0.340 | 0.100 |
| Fraud and trafficking, 1,500 each | milestone | 0.071 | 0.417 | 0.515 |
| | track | 0.491 | 0.535 | 0.497 |
| Court filings, three domains, 72 each | milestone | 0.039 | 0.167 | 0.123 |
| | track | 0.164 | 0.207 | 0.135 |

Every cell differs from shuffled in every subsample, except milestones in court filings (94% of subsamples). At the milestone layer, domains differ least in how they move between states and most in which acts and technologies they use. At the track layer they differ as much in states as in acts: they reach the same milestones by different routes. At 97 walks the means distribution is too sparse to separate domains from shuffled well (shuffled 0.84 bits).

**How milestones are reached.** Of the walks reaching each milestone, the share reaching it by each track, all records:

| | Fraud | Trafficking | CSEA | Cyber |
|---|---:|---:|---:|---:|
| Conditioning by deception | 79% | 3% | 8% | 23% |
| Conditioning by coercion | 6% | 51% | 38% | 18% |
| Exploitation by value taken | 94% | 27% | 4% | 83% |
| Exploitation of a person | 8% | 77% | 94% | 21% |
| Contact by intrusion | 15% | 1% | 11% | 54% |

A walk can reach a milestone more than once, by different tracks; shares need not sum to 100%. Conditioning reached by a demand alone, with no deception or coercion read, is not counted in either row.

**Decision model**, uniform costs:

| | All records | Court filings |
|---|---:|---:|
| $L^*$ | `transfer` → Exploitation | `transfer` → Exploitation |
| Observed median length | 3 acts | 4 acts |
| $\beta$, milestone and track layers | 0.000 | 0.000, 0.008 |
| Random cost models fitting at least as well | 66% | 69% |
| Optimal action taken | 22% | 12% |

Under all nine cutoffs (`min_count` 1, 5, 20 × `min_share` 0, 1%, 5%), $L^*$ is the same and $\beta = 0$.

**Laws**, court filings, walks reaching Exploitation:

| | Fraud (172) | Trafficking (51) | Cyber (53) |
|---|---:|---:|---:|
| Contact primacy | 33% | 24% | 49% |
| Full backbone | 17% | 18% | 19% |
| Maintenance | 53% | 63% | 62% |
| Re-entry | 45% | 27% | 53% |
| Exit | 28% | 14% | 38% |

No milestone is occupied by half of walks in every domain.

**Exploitation predicate.** Share of walks reaching Exploitation only by supply: drugs 32%, firearms 15%, every other domain 0 to 2%.

**Other alphabets.** The SDK's layered exemplar (four layers in four alphabets) reads with every state placed. Three of its layers reach exploitation and are marked `disrupted`, for the arrest that ended them; here they end Completed, and the reader reports each disagreement.

{{GRAPHS}}

**Gold statements** (held-out half): state paths exact for 19 of 22 plain tellings and 1 of 18 paraphrased; predicate correct for 25 of 40.

## Limits

These are measurements over what records narrate.

- **Reward.** Only `uniform` has been tested; "easiest path" needs a researcher's cost table.
- **Telling.** A record often begins at the payment, so missing early states (low contact primacy) can be states the telling skipped. Court filings tell more and are reported separately.
- **Acts.** Read by a list of verbs; about three in ten are missed, and paraphrased tellings are rarely read whole. Tracks inherit this. `recruit` also reads the enlisting of accomplices, so Recruitment is overcounted where offenders recruit each other, as in fraud.
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
