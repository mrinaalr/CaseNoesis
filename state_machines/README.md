# Exploitation State Machine

The acts CaseNoesis reads from public records, fitted as a state machine and tested. Every part of the formal model that a record can supply is estimated here; the part a record cannot supply, the reward, is a declared assumption that the tests can reject. The claims the model was built around are treated as hypotheses. Where the data disagree with them, the disagreement is reported.

| | |
|---|---|
| Input | The `conduct` table: each record's acts in order, with dates and means ([`extraction/conduct.py`](../extraction/conduct.py)) |
| Command line | `python -m state_machines {machine, states, decide, coverage, report, graphs}` |
| MCP | `esm_machine`, `esm_states`, `esm_decide`, `esm_coverage` |
| Report | `data/extracted/esm/report.json` |
| Graphs | `data/extracted/esm/records/`, `data/extracted/esm/models/`, in the SDK's `trajectories` and `means` extensions |
| Tests | [`test_state_machines.py`](test_state_machines.py), 16 tests on synthetic trajectories with planted structure |

**Contents:** [Machine](#the-machine) · [Trajectories](#trajectories) · [Transition function](#transition-function) · [States](#states-are-a-hypothesis) · [Decision model](#decision-model) · [Backbone and intervention](#backbone-and-intervention) · [Ontology](#ontology) · [Capability](#capability) · [Results](#results) · [Limits](#limits) · [Code map](#code-map)

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

Every case in the corpus was prosecuted, so every offense in it was disrupted in fact. `disrupted` means the record narrates the detection. `completed` means it does not. The split describes the telling.

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

**Action space.** $A(s)$ is the set of actions taken at $s$ at least 5 times and in at least 1% of departures from $s$, plus `(stop)`. An action seen once at a state is not evidence that it is open there.

**Observed policy.** $\hat{\pi}(a \mid s) = n(s, a, \cdot) / n(s, \cdot, \cdot)$. It records what offenders in these records did, not a rule they followed.

## States are a hypothesis

The framework this model serves holds that states stay roughly fixed across domains while actions change. That is tested, not assumed.

**Learning states.** A state alphabet is a partition of the kinds of act. For a partition $\phi$, the class model is

$$
P(x_{t+1} \mid x_t) = P\big(\phi(x_{t+1}) \mid \phi(x_t)\big)\ P\big(x_{t+1} \mid \phi(x_{t+1})\big)
$$

and the partition is found by agglomeration: start with every act in its own class and repeatedly merge the pair whose merging costs the least likelihood (Brown et al., 1992). The number of states is chosen by BIC. Every comparison is on held-out trajectories, five folds.

**Testing invariance.** For each pair of domains $(A, B)$:

- *Borrowing cost*: held-out bits per step on $A$ under $B$'s learned states, minus under $A$'s own.
- *Agreement*: adjusted Rand index between the two partitions, over the acts both use.

Each is set beside a floor from bootstrap resamples of $A$ alone: what borrowing costs, and how far partitions disagree, when nothing but sampling differs. Domains differ in their states to the extent that a pair's cost exceeds every resample's, and its agreement falls below every resample's.

The test is run on synthetic data with planted structure in [`test_state_machines.py`](test_state_machines.py): it recovers a planted partition, finds two domains with the same structure invariant, and finds two with different structures different.

## Decision model

The fitted machine says what followed what. The decision model asks whether observed choices look like those of an actor pursuing a goal, under a stated account of cost. [`mdp.py`](mdp.py).

**State.** $(s, r)$ with $r \in \lbrace 0, 1 \rbrace$ whether the goal has been reached, so that the goal pays once. Without $r$, a loop through the goal state pays on every pass.

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

- *Rationality.* Assume $P(a \mid x) \propto \exp(\beta\, Q^*(x, a))$. $\beta = 0$ is indifference to the model's values. $\beta$ is fitted by maximum likelihood to every observed choice made among two or more options, and the fit is compared with indifference and with 200 random cost models ($c(a) \sim U[0, 2]$). A cost model that fits the choices no better than random costs does not describe them.
- *Agreement.* The share of observed choices that are the optimal action, beside the share reached by always taking each state's most common action.
- *Paths.* $L^*$ beside the observed trajectories: length, and whether they reach $G$.

The rationality test is checked in [`test_state_machines.py`](test_state_machines.py) on trajectories drawn from a planted goal-directed actor ($\beta = 2$, recovered above 1 and beating 95% of random costs) and from an indifferent one (gain below 0.05 bits per choice).

**Release.** $L^*$ and $Q^*$ are computed over kinds of stage and kinds of act, from closed public cases, and are published only at that level. Neither is written into the ontology: the `means` extension records no reward and no value by design.

## Backbone and intervention

Most records tell part of an offense, so an intersection of states across trajectories is empty for reasons about the records. Coverage is used instead. [`coverage.py`](coverage.py).

$$
\mathrm{cov}_d(s) = \frac{\left|\lbrace c \in C_d : s \in \sigma_c \rbrace\right|}{|C_d|}, \qquad \mathcal{B}_\theta = \lbrace s : \mathrm{cov}_d(s) \ge \theta \ \ \forall d \rbrace
$$

$\mathcal{B}_\theta$ is reported at $\theta \in \lbrace 0.9, 0.75, 0.5, 0.25, 0.1 \rbrace$, so a reader sees where states drop out.

Removing a state $b$ is measured on the recorded paths that reach the goal:

$$
\kappa_d(b) = \frac{\left|\lbrace c \in C^G_d : b \notin \sigma_c \rbrace\right|}{|C^G_d|}
$$

$\kappa_d(b) = 0$ means every recorded path to the goal in domain $d$ went through $b$. It is a statement about recorded paths and does not predict how an offender would reroute.

## Ontology

[`ontology.py`](ontology.py) writes trajectories and fitted machines in the SDK's `trajectories` (0.3.1) and `means` (0.1.0) extensions. Every graph is validated by the SDK gate: SHACL and the closed-world concept check.

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

Not written: a reward, a value, or a policy; `means:Selection`, because a record shows the option taken and not the menu it was taken from; `means:OptionAssessment`, because frictions are a researcher's reading and not in a record.

## Capability

[`capability/`](capability/) is a sketch of the Capability class proposed in [UCO issue 682](https://github.com/ucoProject/UCO/issues/682), for review before it is offered upstream.

| File | Holds |
|---|---|
| `capability.ttl` | `cap:Capability` (a `uco-core:UcoObject`), `cap:structuredCharacterization` to a `uco-action:ActionPattern`, `cap:capabilityScope`. A bridge re-parents `means:OffenderCapability` onto it, as that class's own comment asks |
| `capability-shapes.ttl` | At most one characterization, and it is an action pattern |
| `capability-exemplar.ttl` | One capability from a gold statement of offense, written both ways: the stand-in the engine writes today, and the proposal's form with a `hasCapability` relationship |
| `capability-invalid-exemplar.ttl` | Must fail its shapes |

The proposal's Module and Parser classes describe forensic software and are left out. The exemplar passes the SDK gate with `capability.ttl` as a local ontology (marked not publishable, as a local term must be) and passes its own shapes; the invalid exemplar fails them. If UCO adopts the class, `cap:Capability` becomes the UCO class and this folder is retired.

## Results

Measured 2026-11-14 on the collected corpus, rules only, offense domains (the mixed `bulk` and `transcripts` court folders left out). Full figures in `report.json`.

**Machine.** 20,813 trajectories, 78,069 steps. 1,675 end in narrated detection. The action space holds 10 to 13 kinds of act at every state: in these records most kinds of act follow most states.

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

In the two large domains the result is clearest. Fraud's states cost trafficking 0.095 bits per step and trafficking's cost fraud 0.128, against resampling floors of 0.010 and 0.001, and the two partitions agree at −0.12. In every domain the five phases predict held-out trajectories worse than the domain's own learned states.

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

"Offenders are direct" does not describe the observed choices: the fitted $\beta$ is at or near zero, and most random cost models fit as well. No researcher cost table exists yet, so "offenders take the easiest path" has not been tested.

**Backbone.** No state is covered by 75% of trajectories in every domain. `harm` is at 50%; `approach` joins at 25%; `leverage` at 10%.

**Graphs.** A fitted machine for each of 11 domains' court filings (590 trajectories) passes the SDK gate with no violation.

### What these results do and do not show

They are measurements over what records narrate, read by rule readers that miss about three acts in ten. They do not by themselves show that offending in different domains has different states. Four things stand between them and that claim:

- **Domain is the collector's search term**, not the charge.
- **Small domains learn coarse states.** BIC with little data prefers few classes, and a coarse partition agrees poorly with a fine one by construction. The resampling floor guards against sampling noise within a domain; it does not equalize sample size between domains. The fraud and trafficking comparison, where both are large, is the one to weigh.
- **The fifteen kinds of act** are themselves a choice, and a partition can only be as fine as they are.
- **Order is the order of telling.**

What they do show is that, at the resolution this engine reads, the data do not ask for one alphabet across domains, and the five phases are not the alphabet they ask for.

## Limits

- **The reward is not in the data.** A cost model is an assumption to test, and only `uniform` has been tested.
- **Detection is a property of the telling.** Every case was prosecuted.
- **A trajectory is one record's telling**, not a case's, and not one person's when a record names several defendants.
- **Acts are read by a list of verbs.** Paraphrased acts are missed ([`gold/conduct.py`](../gold/conduct.py) measures how often).
- **No dissections yet.** Hand close-reads mapped onto the same classes would test what the corpus can only count.

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
| `bellman.py`, `compute_lstar.py`, `iris.py`, `lifecycle_api.py`, `sparql_queries.py`, `trajectory.py`, `graphs/`, `data/` | An earlier lifecycle model, still read by the researcher site in `run/`. Not used by anything above. `graphs/` also holds hand-built close-reads (`*_ESM.ttl`, `slavery_*.ttl`, `layered*.ttl`) that belong in the dissection work |
