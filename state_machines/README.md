# Exploitation State Machine

| | |
|---|---|
| Input | The `conduct` table: each record's acts in order, with dates and means ([`extraction/conduct.py`](../extraction/conduct.py)) |
| Command line | `python -m state_machines {machine, states, decide, coverage, report, graphs}` |
| MCP | `esm_machine`, `esm_states`, `esm_decide`, `esm_coverage` |
| Report | `data/extracted/esm/report.json` |
| Graphs | `data/extracted/esm/records/`, `data/extracted/esm/models/`, in the SDK's `trajectories` and `means` extensions |
| Tests | [`test_state_machines.py`](test_state_machines.py), 16 tests on synthetic trajectories with planted structure |

**Contents:** [Machine](#the-machine) · [Trajectories](#trajectories) · [Transition function](#transition-function) · [States](#states) · [Decision model](#decision-model) · [Backbone and intervention](#backbone-and-intervention) · [Ontology](#ontology) · [Capability](#capability) · [Results](#results) · [Limits](#limits) · [Code map](#code-map)

## The machine

$$
\mathcal{M} = (S,\ A,\ T,\ R_G,\ s_0,\ F)
$$

| Symbol | Definition | Here |
|---|---|---|
| $S$ | Finite set of states | A partition of the fifteen kinds of act. Default: five phases (`preparation`, `approach`, `leverage`, `harm`, `exit`). Learned alternatives from [`states.py`](states.py) |
| $A$ | Actions | A kind of act (`transfer`), or an act with the technology its sentence names (`transfer[gift_card]`), plus `(stop)` |
| $T$ | $T : S \times A \to \Delta(S)$ | Counted from trajectories ([below](#transition-function)) |
| $R_G$ | Goal-indexed rewards | **Not estimated.** A declared cost model ([below](#decision-model)) |
| $s_0$ | Initial state | `start` |
| $F$ | Terminal states | `completed` (the actor stops, or the telling ends) and `disrupted` (the record narrates detection next) |

## Trajectories

A record's acts, in the order it tells them, become steps:

$$
\sigma = \big((s_0, a_0, s_1),\ (s_1, a_1, s_2),\ \dots\big), \qquad s_{t+1} = \begin{cases} \text{disrupted} & \text{if detection is narrated right after } a_t \\ \phi(a_t) & \text{otherwise} \end{cases}
$$

where $\phi$ maps a kind of act to its state. A trajectory that does not end in detection ends with $(s_T, \texttt{(stop)}, \text{completed})$. A repeat of the same action into the same state is one step. Steps are counted over all trajectories:

$$
n(s, a, s') = \left|\lbrace (s, a, s') \text{ in } \sigma_c : c \in C \rbrace\right|
$$

## Transition function

$$
\hat{T}(s' \mid s, a) = \frac{n(s, a, s')}{n(s, a, \cdot)}
$$

defined for the pairs the corpus observes, and reported with $n(s, a, \cdot)$. Because $s' = \phi(a)$ except for detection, $\hat{T}$ is close to deterministic, and its information is in $P(\text{disrupted} \mid s, a)$: how often a record narrates detection right after an act.

**Action space.** $A(s)$ is the set of actions taken at $s$ at least 5 times and in at least 1% of departures from $s$, plus `(stop)`.

**Observed policy.** $\hat{\pi}(a \mid s) = n(s, a, \cdot) / n(s, \cdot, \cdot)$.

## States

**Learning states.** A state alphabet is a partition of the kinds of act. For a partition $\phi$, the class model is

$$
P(x_{t+1} \mid x_t) = P\big(\phi(x_{t+1}) \mid \phi(x_t)\big)\ P\big(x_{t+1} \mid \phi(x_{t+1})\big)
$$

and the partition is found by agglomeration: start with every act in its own class and repeatedly merge the pair whose merging costs the least likelihood (Brown et al., 1992). The number of states is chosen by BIC. Every comparison is on held-out trajectories, five folds.

**Testing invariance.** For each pair of domains $(A, B)$:

- *Borrowing cost*: held-out bits per step on $A$ under $B$'s learned states, minus under $A$'s own.
- *Agreement*: adjusted Rand index between the two partitions, over the acts both use.

Each is compared with a floor from bootstrap resamples of $A$ alone. A pair differs when its cost exceeds every resample's and its agreement falls below every resample's.

Checked on planted structure in [`test_state_machines.py`](test_state_machines.py).

## Decision model

[`mdp.py`](mdp.py).

**State.** $(s, r)$ with $r \in \lbrace 0, 1 \rbrace$ whether the goal has been reached, so the goal pays once.

**Reward.** For a cost model $\kappa$ with goal states $G$:

$$
R\big((s, r), a, s'\big) = -c_\kappa(a) \;+\; v_G\,[s' \in G \wedge r = 0] \;-\; d\,[s' = \text{disrupted}]
$$

| Cost model | $c(a)$ | Encodes |
|---|---|---|
| `uniform` | 1 for every act, 0 for `(stop)` | "Offenders are direct." $L^*$ is the shortest feasible path to $G$ |
| `declared` | 1 plus the mean of four friction levels from `config/esm_costs.json` (template: [`esm_costs.example.json`](esm_costs.example.json)) | "Offenders take the easiest path", with "easy" set by the researcher. Not present until a researcher writes the table |

**Solution.** Value iteration on $V^*(x) = \max_{a \in A(x)} \sum_{x'} \hat{T}(x' \mid x, a)\,[R + \gamma V^*(x')]$, $\gamma = 0.95$, giving $Q^*$, the optimal policy, and $L^*$, its most probable path from `start`.

**Tests.**

- *Rationality.* Assume $P(a \mid x) \propto \exp(\beta\, Q^*(x, a))$. $\beta = 0$ is indifference to the model's values. $\beta$ is fitted by maximum likelihood to every observed choice made among two or more options, and the fit is compared with indifference and with 200 random cost models ($c(a) \sim U[0, 2]$).
- *Agreement.* The share of observed choices that are the optimal action, beside the share reached by always taking each state's most common action.
- *Paths.* $L^*$ beside the observed trajectories: length, and whether they reach $G$.

Checked on a planted goal-directed actor ($\beta = 2$) and an indifferent one in [`test_state_machines.py`](test_state_machines.py).

## Backbone and intervention

[`coverage.py`](coverage.py).

$$
\mathrm{cov}_d(s) = \frac{\left|\lbrace c \in C_d : s \in \sigma_c \rbrace\right|}{|C_d|}, \qquad \mathcal{B}_\theta = \lbrace s : \mathrm{cov}_d(s) \ge \theta \ \ \forall d \rbrace
$$

Reported at $\theta \in \lbrace 0.9, 0.75, 0.5, 0.25, 0.1 \rbrace$.

Share of goal-reaching paths that avoid state $b$:

$$
\kappa_d(b) = \frac{\left|\lbrace c \in C^G_d : b \notin \sigma_c \rbrace\right|}{|C^G_d|}
$$

$\kappa_d(b) = 0$: every recorded path to the goal in domain $d$ went through $b$.

## Ontology

[`ontology.py`](ontology.py) writes trajectories and fitted machines in the SDK's `trajectories` (0.3.1) and `means` (0.1.0) extensions. Every graph is validated by the SDK gate.

| Object | Class | Carries |
|---|---|---|
| State | `traj:State` | One per state of an alphabet; the same IRI in every graph |
| Act | `traj:PhaseAssertion` | The state it occupies, its place in the telling, the interval its paragraph dates it to (open when undated), a confidence from how it was settled, and the record it was read from |
| Last act before narrated detection | `traj:PhaseAssertion` | `isTerminal true`, `terminalPolarity "disrupted"` |
| Record's telling | `traj:Trajectory` | Its assertions |
| Step | `traj:Transition` | Triggered by and enacting a `uco-action:Action` for the act, with the technology as `uco-action:instrument` |
| Goal | `means:Goal` | Reaching the goal state, pursued by the record's offender |
| Act by a named technology | `means:Option` | One per technology: the instrument, the state it was taken from, the transition it enacted |
| The ability to use it | `means:OffenderCapability` | Evidenced by its use in the record |
| Fitted machine | `traj:StateMachineModel` | The trajectories it was learned from, its transitions, and one `traj:TransitionEstimate` per $(s, a, s')$ with $\hat{T}$ and its counts, generated by an analysis run of this code |

Not written: reward, value, policy (`means` records none by design); `means:Selection` (a record shows the option taken, not the menu); `means:OptionAssessment` (frictions are not in a record).

## Capability

[`capability/`](capability/): a sketch of the Capability class proposed in [UCO issue 682](https://github.com/ucoProject/UCO/issues/682), to offer upstream.

| File | Holds |
|---|---|
| `capability.ttl` | `cap:Capability` (a `uco-core:UcoObject`), `cap:structuredCharacterization` to a `uco-action:ActionPattern`, `cap:capabilityScope`. A bridge re-parents `means:OffenderCapability` onto it, as that class's own comment asks |
| `capability-shapes.ttl` | At most one characterization, and it is an action pattern |
| `capability-exemplar.ttl` | One capability from a gold statement of offense, written both ways: the stand-in the engine writes today, and the proposal's form with a `hasCapability` relationship |
| `capability-invalid-exemplar.ttl` | Must fail its shapes |

Module and Parser, which describe forensic software, are left out. The exemplar passes the SDK gate with `capability.ttl` as a local ontology, and its own shapes; the invalid exemplar fails them.

## Results

2026-11-14, collected corpus, rules only, offense domains. Full figures in `report.json`.

**Machine.** 20,813 trajectories, 78,069 steps. 1,675 end in narrated detection. The action space holds 10 to 13 kinds of act at every state.

**States.** Learned per domain, all records:

| Domain | Trajectories | States learned | Held-out bits per step: own states | five phases | states pooled over all domains | Agreement with the five phases |
|---|---:|---:|---:|---:|---:|---:|
| fraud | 14,849 | 10 | 2.973 | 3.064 | 2.970 | 0.26 |
| trafficking | 1,556 | 7 | 2.975 | 3.100 | 2.986 | −0.02 |
| forced labor | 139 | 4 | 2.837 | 3.038 | 3.045 | 0.05 |
| cyber | 91 | 4 | 3.295 | 3.385 | 3.295 | −0.03 |
| child exploitation | 90 | 3 | 3.104 | 3.241 | 3.444 | −0.02 |

| Invariance, 20 ordered pairs of domains | |
|---|---:|
| Borrowing another domain's states costs more than every resample of the same domain | 15 of 20 |
| Partitions agree less than every resample of the same domain | 11 of 20 |
| Mean agreement between domains | 0.04 |
| Mean agreement between resamples of one domain | 0.36 |

Fraud and trafficking, the two large domains: fraud's states cost trafficking 0.095 bits per step and trafficking's cost fraud 0.128, against floors of 0.010 and 0.001; agreement −0.12. In every domain the five phases predict held-out trajectories worse than its own states.

**Decision model**, uniform costs, goal `harm`:

| | All records | Court filings |
|---|---:|---:|
| $L^*$ | `start` → `transfer` → `harm`, then stop | `start` → `transport` → `harm`, then stop |
| Observed median length | 2 acts | 3 acts |
| Observed trajectories reaching `harm` | 62% | 82% |
| Fitted $\beta$ | 0.000 | 0.099 |
| Gain over indifference, bits per choice | 0.000 | 0.011 |
| Random cost models fitting at least as well | 88% | 68% |
| Optimal action taken | 22% | 12% |
| Most common action at each state | 32% | 20% |

Uniform cost does not explain the observed choices: $\beta \approx 0$, and most random cost models fit as well.

**Backbone.** No state is covered by 75% of trajectories in every domain. `harm` is at 50%; `approach` joins at 25%; `leverage` at 10%.

**Graphs.** A fitted machine for each of 11 domains' court filings (590 trajectories) passes the SDK gate with no violation.

## Limits

Results are measurements over what records narrate. They are not yet findings about offending.

- **Reward.** Not in the data. Only `uniform` has been tested; "easiest path" needs a researcher's cost table.
- **Detection.** Every case was prosecuted. `disrupted` means the record narrates detection.
- **Acts.** Read by a list of verbs; about three in ten are missed ([`gold/conduct.py`](../gold/conduct.py)).
- **Order.** The order of telling.
- **Unit.** A trajectory is one record's telling, not a case's or one defendant's.
- **Domain.** The collector's search term, not the charge.
- **Small domains.** BIC learns coarse states from little data, and a coarse partition agrees poorly with a fine one by construction. Weigh the fraud and trafficking comparison, where both are large.
- **Release.** $L^*$ and $Q^*$ are published only at the level of phases and kinds of act, from closed public cases.
- **Dissections.** None yet. Hand close-reads mapped onto the same classes would test what the corpus can only count.

## Code map

| File | What it does |
|---|---|
| [`machine.py`](machine.py) | Trajectories as steps; the fitted machine: counts, $\hat{T}$, action space, observed policy |
| [`states.py`](states.py) | State induction, held-out evaluation, the invariance test |
| [`mdp.py`](mdp.py) | Cost models, value iteration, $L^*$, rationality, agreement |
| [`coverage.py`](coverage.py) | Coverage, backbone, intervention |
| [`ontology.py`](ontology.py) | Trajectory and model graphs in the `trajectories` and `means` extensions; the gate |
| [`analysis.py`](analysis.py) | Each analysis as one call, for the command line and the MCP server |
| [`capability/`](capability/) | The capability sketch |
| [`test_state_machines.py`](test_state_machines.py) | Tests on planted structure |
| `bellman.py`, `compute_lstar.py`, `iris.py`, `lifecycle_api.py`, `sparql_queries.py`, `trajectory.py`, `graphs/`, `data/` | Earlier lifecycle model, read only by the researcher site in `run/`. To be removed |
