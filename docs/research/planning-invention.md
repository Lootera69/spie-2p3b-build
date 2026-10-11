# Strategy-aware planning invention and guided repair

The `planning-invention-v1` search targets one explicit strategy: **invest energy now
to save actions later**. It uses the existing fully observable energy/gates/switches
family, with the same physical rules and necessity requirements. The original
`state_planning.propose` remains available for saved-model replay.

New workshop requests use engine revision 8 and this strategy-aware search for the
energy/switch activity. Revision 7 retains its original proposer and seeded output.
The normal guided-search allowance is 2,000 attempts; the comparison below deliberately
gives both modes the same smaller 1,000-attempt cap.

This adds a requested strategic property and repairs rejected designs. It does not
invent arbitrary new mechanics, use a learned model, or establish human difficulty.
The underlying [state-planning report](state-planning.md) describes the physical domain
and its earlier independent audit.

## Exact strategy contract

Consider every action legal in the initial state, including the initial switch. Its
immediate energy cost comes from the stated route or switch rule. The `invest-energy`
property requires all of the following:

1. Exactly one first action achieves the minimum total action count.
2. That first action spends strictly more energy than the cheapest legal first action.
3. **Every** action tied for the cheapest immediate energy cost admits a successful
   committed continuation.
4. Every cheapest action requires strictly more total actions than the optimum, even
   with unrestricted optimal continuation after that first action.

The committed comparison excludes undo-only returns to the initial room with unchanged
gates, no energy gain, and no improvement in remaining recharge availability. A cheapest
action cannot qualify merely by being a dead end or an irrelevant out-and-back move.
The stricter unrestricted-cost comparison prevents the commitment filter itself from
creating an artificial disadvantage for the cheaper action.

This defeats the precisely defined policy “choose any legal first action with minimum
immediate energy expenditure.” It does not claim to defeat every heuristic, to require
optimality at all later decisions, or to make the entire optimal action sequence unique.

## Guided search and restart baseline

Both modes draw fresh candidates from the unchanged `state_planning._sample`, evaluate
the same existing length, uniqueness, reachability, branching and mechanic-necessity
gates, and apply the same strategy filter. The evaluator returns diagnostics from its
actual solution and ablation paths. Acceptance still requires the independent physical
and strategy certificates.

The guided mode retains a bounded set of near misses and proposes local edits to energy
costs, starting conditions, gate requirements, switch effects or charger access. Failed
checks and their witnesses supply some candidate repairs; general neighborhood edits
provide additional possibilities, and fresh samples permit restarts. Not every mutation
is a direct repair of one counterexample.
The repair history records parent and child physical models, hashes, the exact field
edit, its reason and witness, and the search scores before and after the edit.

The restart mode uses independent fresh samples and never edits a prior model. It stops
at the first model passing the same complete target. Consequently it tests whether
repair improves search for this particular target, rather than comparing different
acceptance rules. The legacy proposer has a different stopping condition: it accepts
the old physical gates without requiring the new strategy. Its strategy frequency is
reported separately as context, never as an efficiency baseline.

## Fair accounting and independent audit

The comparison fixes a budget of 1,000 candidate attempts per request for each new mode.
The budget includes invalid proposals and duplicates that do not require a graph
construction. The report therefore distinguishes budgeted attempts from actual baseline
graphs, each of the four ablation graphs, and distinct evaluated physical models. An
exhausted request retains its counters; no failed seed disappears from the denominator.
Both modes use the same lazy ablation rule.

Generation time is measured without instrumentation. The identical seeded request is
then replayed while independent wrappers count every raw sampler call and every domain
graph construction. The full resulting model or exhaustion telemetry must match the
first run. This prevents observation overhead from disproportionately charging the
restart mode for its larger number of raw samples. Certification, independent auditing
and instrumented replay have separate measured durations.

The audit uses the separate raw-domain interpreter and forward BFS in
`tools/benchmark_state_planning.py`. From raw rules it recomputes initial energy costs,
every cheapest tie, unrestricted and committed continuation costs, and the unique best
first action. It compares every claimed strategy continuation against the independent
graph, including the complete state sequence and the absence of a forbidden return.
The existing complete graph/goal comparisons and all four mechanic ablations also run.

For restart mode, the audit independently reproduces the entire `_sample` sequence
from its seed and checks that no extra proposal bias or mutation was inserted. For
accepted repairs, it uses the physical models actually observed during generation,
replays every exact edit, checks the chain back to a raw sample, and independently
establishes that each parent failed the complete target. A success is counted as rescued
by repair only when a changed final model passes and its immediate parent fails. A
separate count identifies final repairs whose parent already passed the old physical
gates but failed the new strategy.

Complete strategy certification is in `planning_strategy.certify`: it uses the compiled
core graph and independent forward searches, rather than accepting search diagnostics
or authored answer metadata. The ordinary physical certificate retains complete direct
versus core graph agreement and the Z3 proof of minimum action count and uniquely
optimal first action. Verification discrepancies abort the benchmark; only the declared
bounded-search exhaustion is an expected rejection.

## Reproduce the comparison

From the `engine` directory:

```powershell
./.venv/Scripts/python.exe -B tools/benchmark_planning_invention.py --seeds 0,1,2,3,4,5,6,7,8,9 --levels 1,2,3 --budget 1000 --progress --out artifacts/planning-invention/comparison-new.json
```

The corpus uses consecutive seeds at all three levels and alternates guided/restart
order by case. It is a fixed-corpus comparison, not a held-out evaluation: seed 0 was
also used for implementation pilots. Development experiments must remain separate from
the frozen measurement. The default command additionally reports the legacy proposer's
frequency on the same seeds at its original 2,000-proposal budget.

Output includes accepted raw models, physical and strategy audits, repair histories,
all exhaustion counters, separate timing phases, canonical structure and route-topology
counts, runtime versions and hashes of the relevant source files. The command refuses
to overwrite evidence, rejects Python `-O`, and aborts if recorded source files change
during measurement.

## Frozen fixed-seed results

The [tracked comparison results](planning-invention-results.json) contain 30 requests
per mode: seeds 0–9 at all three levels, together with the full report's SHA-256.
The complete local report remains at
`artifacts/planning-invention/fixed-seeds-0-9-budget1000-v1.json` from the `engine`
directory; it retains raw models, full certificates and accepted repair histories.
All **52 accepted outputs**
passed exact seeded replay, the independent raw-domain strategy audit, the complete
physical checks and all four mechanic-necessity interventions. Recorded source hashes
remained unchanged for the completed run. The algorithm was not retuned from these
results. Development experiments used seeds 20–29 as well as seed-0 pilots.

| Level | Guided verified / 10 | Restart verified / 10 | Candidate attempts, guided / restart | Actual graphs, guided / restart | Route topologies, guided / restart |
| --- | --- | --- | --- | --- | --- |
| Easy | 10 | 9 | 2,187 / 4,627 | 3,724 / 6,733 | 4 / 3 |
| Medium | 9 | 10 | 1,593 / 2,708 | 2,818 / 2,777 | 9 / 10 |
| Hard | 8 | 6 | 4,193 / 6,001 | 4,041 / 5,725 | 8 / 6 |
| Total | 27 | 25 | 7,973 / 13,336 | 10,583 / 15,235 | 21 / 19 |

Guided search accepted **27/30** requests and exhausted three; independent restarts
accepted **25/30** and exhausted five. Paired by seed and level, both succeeded in 23
cases, only guided succeeded in four, only restart succeeded in two, and both exhausted
in one. Guided was therefore not uniformly better: it missed one medium and one hard
case that restart solved. Every accepted structure was distinct within its own mode:
27 guided structures and 25 restart structures.

Of the 27 guided successes, **25 were rescued by actual repairs**, verified by replaying
the changed physical rules and independently rejecting their immediate parents. Ten
final parents already passed the old physical gates and failed only the target strategy.
The other two guided successes came directly from a fresh sample. Every cheapest legal
first action, including all ties, had a committed solution but needed one or two more
actions than the unique optimal first action.

The candidate counters include 163 invalid-shape and 1,067 duplicate guided attempts,
and 1,197 invalid-shape restart attempts. Actual baseline graph calls were **6,743 versus
12,139**; ablation graph calls were **3,840 versus 3,096**. Guided search spent more work
on ablations even though its overall graph count was lower. At medium level its graph
count was slightly higher and its acceptance count lower. These distinctions matter
when interpreting candidate-count reductions.

Across all 30 requests, uninstrumented generation took **25.896 s guided versus
32.046 s restart** in total; medians were **0.490 s versus 0.864 s**, and nearest-rank
95th percentiles **3.237 s versus 2.737 s**. At hard level guided generation took slightly
longer overall, **12.035 s versus 11.736 s**, while producing two more verified outputs.
Certification medians for accepted outputs were 0.792 s and 0.808 s. The report keeps
the extra independent audit and instrumented replay durations separate. These local
Windows/Python 3.12/Z3 4.13.4 observations overlapped other validation work and do not
establish a uniform latency improvement or a hardware-independent speed claim.

The original proposer produced 30 verified physical puzzles at its original 2,000
proposal cap; **16/30 already satisfied the new strategy** when independently examined.
That is contextual strategy frequency, not a comparison of search efficiency: the
legacy proposer stops on a different acceptance condition and uses a different cap.

As a concrete repair example, guided easy seed 0 first changed a gate to make switches
necessary. That intermediate model passed the old physical gates but its free initial
switch was also optimal, so it failed `invest-energy`. The final repair changed the
other initial gate setting. The best first action then spent one energy to move to
Orchard and led to a five-action solution; the free switch still admitted a committed
solution but required six actions. Both physical edits, their parent and child models,
and the independently checked costs are retained in the evidence.

## Interpretation limits

Equal candidate budgets do not imply equal wall-clock or graph-computation budgets;
both are reported explicitly. A lower failure rate or fewer sampled candidates is not
automatically a throughput improvement. Topology fingerprints ignore labels, energy
costs, gates, switches and charger position, while full structural fingerprints retain
the mechanics and ignore only naming symmetries. Neither is a universal novelty test.

The result applies to this bounded family, local repair operators and exact initial
decision strategy. It establishes neither global search optimality nor arbitrary
planning intelligence. Human engagement and difficulty require separate player data.
The optional Studio editorial limits documented for the physical family also remain
separate from formal correctness.

## Validation

The release checks passed **444 targeted Python tests** (340 planning, integration,
editorial, feedback and library checks plus 104 synthesis, reasoning-control,
Autopilot and activity regressions). All six JavaScript suites passed against the
revision-8 local server, as did the live API smoke test and Ruff checks for the source,
tests and benchmark tools.
These checks complement the fixed-seed evidence above; no benchmark timings were
rerun while preparing the compact tracked result files.
