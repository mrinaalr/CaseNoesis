# Exploitation State Machine

| | |
|---|---|
| Input | Each record's acts in order, with dates and means ([`extraction/conduct.py`](../extraction/conduct.py)) |
| Command line | `python -m state_machines {machine, invariance, decide, laws, report, graphs}` |
| MCP | `esm_machine`, `esm_invariance`, `esm_decide`, `esm_laws` |
| Output | `data/extracted/esm/report.json`; graphs in `data/extracted/esm/` |
| Tests | [`test_state_machines.py`](test_state_machines.py): 20 tests on planted structure |

**Contents:** [Machine](#the-machine) · [States](#states) · [Transitions](#transitions) · [Invariance](#invariance) · [Decision model](#decision-model) · [Backbone and laws](#backbone-and-laws) · [Exploitation predicate](#exploitation-predicate) · [Ontology](#ontology) · [Capability](#capability) · [Results](#results) · [Limits](#limits) · [Code map](#code-map)

## The machine

$$
\mathcal{M} = (S,\ A,\ T,\ R_G,\ s_0,\ F)
$$

| Symbol | Here |
|---|---|
| $S$ | Preparation, InitialContact, Conditioning, Exploitation, Maintenance ([below](#states)) |
| $A$ | A kind of act (`transfer`), or an act with the technology its sentence names (`transfer[gift_card]`), plus `(stop)` |
| $T$ | $\hat{T}(s' \mid s, a)$, counted from trajectories |
| $R_G$ | Not estimated. A declared cost model ([below](#decision-model)) |
| $s_0$ | `start` |
| $F$ | Completed (Exploitation reached), Disrupted (detection narrated before it), Unresolved (the telling ends before it) |

## States

A state is a milestone the offense has reached, read from the acts before it. States and actions are separate: the same act can leave different states and lead to different ones.

| State | Reached when | CAC |
|---|---|---|
| Preparation | Means set up, no victim yet | |
| InitialContact | A victim, a person or a system, is reached | `cac-grooming:InitialContactPhase` |
| Conditioning | Leverage is held: deception, a demand, a threat, control | `cac-grooming:ConditioningPhase` |
| Exploitation | Value or a person is taken, or the offense's harm delivered | `cac-grooming:ExploitationPhase` |
| Maintenance | Leverage is renewed after exploitation | `cac-grooming:MaintenancePhase` |

The four backbone states are aligned to CAC by `skos:closeMatch`, not `exactMatch`: CAC defines them for child exploitation, and here they apply to every domain.

Acts move states by their role:

| Role | Acts | Move |
|---|---|---|
| prepare | setup | `start` → Preparation |
| reach | contact, recruit, access | `start`, Preparation → InitialContact |
| leverage | deception, demand, threat, control, transport | → Conditioning before exploitation; → Maintenance after |
| extract | transfer, exploit | → Exploitation, including from Maintenance (a renewed extraction) |
| deliver | supply | → Exploitation |
| after | movement, concealment | no change |

Exploitation ⇄ Maintenance is a loop: extortion that demands again, trafficking that keeps control.

## Transitions

$$
\hat{T}(s' \mid s, a) = \frac{n(s, a, s')}{n(s, a, \cdot)}
$$

reported with $n(s, a, \cdot)$. Detection narrated right after an act is that act's outcome: Completed if exploitation had been reached by then, Disrupted if not.

**Action space.** $A(s)$: acts taken at $s$ at least 5 times and in at least 1% of departures, plus `(stop)`. The cutoff changes no result: see [Results](#results).

## Invariance

The claim: domains share states, and technology enters through the actions. If so, domains should look alike in how they move between states, and differ in which acts, and which technologies, they use to do it. [`invariance.py`](invariance.py).

| Level | Distribution per domain |
|---|---|
| states | Transitions between states, $s \to s'$ with $s' \ne s$ |
| acts | The act taken at each state, $(s, a)$ |
| means | The act and its technology at each state, $(s, a[\text{means}])$ |

For each level, the mean Jensen-Shannon divergence between domains (bits) is set beside the divergence with domain labels shuffled. Domains are subsampled to equal size, 50 times, so a large domain does not look distinct only by being large. The claim predicts little excess at the state level and clear excess at the other two.

## Decision model

[`mdp.py`](mdp.py). The state carries whether the goal, Exploitation, has been reached, so it pays once.

$$
R\big((s, r), a, s'\big) = -c_\kappa(a) \;+\; v\,[s' = \text{Exploitation} \wedge r = 0] \;-\; d\,[s' = \text{Disrupted}]
$$

| Cost model | $c(a)$ | Encodes |
|---|---|---|
| `uniform` | 1 per act, 0 for `(stop)` | "Offenders are direct" |
| `declared` | 1 plus the mean of four friction levels in `config/esm_costs.json` (template: [`esm_costs.example.json`](esm_costs.example.json)) | "Offenders take the easiest path", with ease set by the researcher |

Value iteration ($\gamma = 0.95$) gives $Q^*$, the optimal policy, and $L^*$. Tests:

- **Rationality.** $P(a \mid x) \propto \exp(\beta\, Q^*(x, a))$, $\beta$ fitted to every observed choice among two or more options, compared with $\beta = 0$ and with 200 random cost models.
- **Agreement.** Share of choices that are the optimal action, beside always taking each state's most common action.
- **Sensitivity.** All results under nine feasibility cutoffs.

## Backbone and laws

[`coverage.py`](coverage.py). Each law is measured on trajectories that reach Exploitation.

| Measure | Definition |
|---|---|
| Backbone at $\theta$ | States occupied by at least $\theta$ of trajectories in every domain |
| Contact primacy | InitialContact before Exploitation |
| Full backbone | InitialContact and Conditioning both before Exploitation |
| Maintenance | Maintenance after Exploitation |
| Loop | Exploitation re-entered after Maintenance |
| $\kappa_d(b)$ | Share of completed trajectories that avoid state $b$. 0: every completed path went through $b$ |

## Exploitation predicate

A trajectory is exploitative when the victim is the source of what the offender takes: it reaches Exploitation by `extract` (transfer, exploit). `passes`, `fails` (reached only by `deliver`: contraband supplied, no victim as source), or `not_reached`.

## Ontology

[`ontology.py`](ontology.py) writes in the SDK's `trajectories` (0.3.1) and `means` (0.1.0) extensions. Every graph passes the SDK gate.

| Object | Class |
|---|---|
| State | `traj:State`, with `skos:closeMatch` to CAC |
| Act | `traj:PhaseAssertion`: the state it moved the offense to, its place, its interval, its confidence, its record |
| Last act | `isTerminal`, `terminalPolarity` "completed" or "disrupted"; none when unresolved |
| Telling | `traj:Trajectory` |
| Step | `traj:Transition`, enacting a `uco-action:Action` with the technology as `uco-action:instrument` |
| Goal | `means:Goal`: reach Exploitation |
| Act by a technology | `means:Option`, one per technology |
| Ability to use it | `means:OffenderCapability`, evidenced by use |
| Fitted machine | `traj:StateMachineModel` with one `traj:TransitionEstimate` per $(s, a, s')$ |

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

**Machine.** 20,813 trajectories, 85,166 steps. Ends: 10,676 Completed, 917 Disrupted, 9,220 Unresolved.

**Invariance.** Excess divergence over shuffled labels, bits:

| | States | Acts | Means |
|---|---:|---:|---:|
| Five domains, 97 trajectories each | 0.074 | 0.303 | 0.107 |
| Fraud and trafficking, 1,500 each | 0.061 | 0.417 | 0.518 |
| Court filings, three domains, 72 each | 0.024 | 0.165 | 0.125 |

Every level differs from shuffled in every subsample, except states in court filings (78% of subsamples). Domains differ least in how they move between states, and most in which acts and technologies they use. At 97 trajectories the means distribution is too sparse to separate domains from shuffled well (shuffled 0.84 bits); at 1,500 it is the largest difference.

**Decision model**, uniform costs:

| | All records | Court filings |
|---|---:|---:|
| $L^*$ | `transfer` → Exploitation | `exploit` → Exploitation |
| Observed median length | 3 acts | 4 acts |
| $\beta$ | 0.000 | 0.000 |
| Random cost models fitting at least as well | 83% | 71% |
| Optimal action taken | 19% | 10% |

Under all nine cutoffs (`min_count` 1, 5, 20 × `min_share` 0, 1%, 5%), $L^*$ is the same and $\beta = 0$.

**Laws**, court filings, trajectories reaching Exploitation:

| | Fraud (172) | Trafficking (51) | Cyber (53) |
|---|---:|---:|---:|
| Contact primacy | 33% | 24% | 49% |
| Full backbone | 17% | 18% | 19% |
| Maintenance | 53% | 63% | 62% |
| Loop | 41% | 27% | 43% |

No state is occupied by half of trajectories in every domain.

**Exploitation predicate.** Share of trajectories reaching Exploitation only by supply: drugs 32%, firearms 12%, every other domain 0 to 2%.

**Graphs.** Per-record trajectories and per-domain fitted machines for court filings pass the SDK gate.

**Gold statements** (held-out half): state paths exact for 19 of 22 plain tellings and 1 of 18 paraphrased; predicate correct for 25 of 40.

## Limits

These are measurements over what records narrate.

- **Reward.** Only `uniform` has been tested; "easiest path" needs a researcher's cost table.
- **Telling.** A record often begins at the payment, so missing early states (low contact primacy) can be states the telling skipped. Court filings tell more and are reported separately.
- **Acts.** Read by a list of verbs; about three in ten are missed, and paraphrased tellings are rarely read whole.
- **Order.** The order of telling.
- **Unit.** One record's telling, not a case's or one defendant's.
- **Domain.** The collector's search term, not the charge.
- **Levels.** Divergences at different levels have different numbers of categories; compare each with its own shuffled baseline, not with each other directly.
- **Release.** $L^*$ and $Q^*$ are published only at the level of states and kinds of act, from closed public cases.
- **Dissections.** None yet.

## Code map

| File | What it does |
|---|---|
| [`states.py`](states.py) | States, roles, steps, paths, the exploitation predicate, CAC alignment |
| [`machine.py`](machine.py) | The fitted machine: counts, $\hat{T}$, action space, observed policy |
| [`invariance.py`](invariance.py) | Domains compared at the state, act and means levels against shuffled labels |
| [`mdp.py`](mdp.py) | Cost models, value iteration, $L^*$, rationality, agreement, cutoff sensitivity |
| [`coverage.py`](coverage.py) | Backbone, laws, intervention, predicate by domain |
| [`ontology.py`](ontology.py) | Trajectory and model graphs; the gate |
| [`analysis.py`](analysis.py) | Each analysis as one call, for the command line and the MCP server |
| [`capability/`](capability/) | The capability sketch |
| `bellman.py`, `compute_lstar.py`, `iris.py`, `lifecycle_api.py`, `sparql_queries.py`, `trajectory.py`, `graphs/`, `data/` | Earlier lifecycle model, read only by the researcher site in `run/`. To be removed |
