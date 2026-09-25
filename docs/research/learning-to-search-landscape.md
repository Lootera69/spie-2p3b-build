# Learning-to-Search Landscape for SPIE

*A web + code research survey for the "smarter niche/operator selection" phase of SPIE's MAP-Elites invention loop.*

**Scope & disclaimer.** This report surveys open, non-LLM techniques for making SPIE's search *steer itself* — deciding **which occupied niche to expand** and **which invention operator to apply** — while leaving the formal correctness gate (`validate → verify → certify`) as the sole, unlearned authority. All web content below is treated as data. Nothing here proposes putting a learned model in the correctness, acceptance, or measurement path.

Grounded against the live code at `engine/src/spie/`:
- `mapelites.py` — `evolve()` is where the two RNG choices live (lines ~268 and ~270).
- `operators.py` — 16 operators in 4 families (`STRUCTURAL`, `TEMPORAL`, `INFORMATION`, `GOAL`; `FAMILIES`, `OPERATORS`).
- `quality.py` — the `QualityVector` fields that become policy features.

---

## 1. TL;DR

**Replicate Adaptive Operator Selection (AOS) built on a bandit, with "survival" credit assignment.** Concretely: replace the two uniform `rng.choice(...)` calls in `evolve()` with (a) a **UCB-style bandit over the 16 operators** (optionally hierarchical: family, then operator) and (b) a **UCB bandit over occupied cells** for parent selection — this second one is *exactly* the published "Quality-Diversity Selection as a Multi-Armed Bandit" result. The reward is free: SPIE's `place()` already tells you whether a child was `placed`/`replaced` (an "elite survived") versus `dominated`/`no-op`/rejected. This is a few hundred lines of pure Python, adds no dependency, and stays byte-deterministic if scores are rounded (as `fitness_of` already does) with sorted tie-breaks. Because operator utility drifts as the archive fills, use a **non-stationary variant** (discounted or sliding-window UCB, or DMAB + Page-Hinkley change detection). **Runner-up:** Thierens' **Adaptive Pursuit / Probability Matching** — even smaller, but reintroduces a roulette-wheel draw. **Second runner-up / the "decision-model" idea done right:** a tiny per-operator **contextual bandit / online logistic model** over `QualityVector` features that outputs a *calibrated* survival probability (Platt/temperature/isotonic-PAVA calibration) — this is how you borrow the Laya/Jev *concept* (state → typed choice + honest probability, no text, no LLM) without their 421M-param torch weights. **Biggest risk:** floating-point / dependency creep silently breaking archive byte-reproducibility, and the standing temptation to let "high confidence" skip a gate — which would breach the thesis. Both are avoidable and flagged below.

---

## 2. Landscape table

| Approach | Open? / License | Deterministic-friendly? | Dependency weight | How it maps to SPIE niche/operator selection | Thesis-safe (steering-only)? |
|---|---|---|---|---|---|
| **UCB1 bandit AOS** (operator + parent selection; "survival" credit) | Yes — classic public-domain algorithms; QD-MAB paper's code on GitHub (check repo license) | **Excellent** — rank-based (argmax), only RNG is tie-break; reuse the existing seeded `Random` | **Nil** — pure Python, ~150–300 LOC, no new deps | Replace both `rng.choice` calls; per-operator & per-cell counters `n,w`; reward = `placed`/`replaced` | **Yes** — only picks what to *try*; `certify` still gates |
| **Discounted / Sliding-Window UCB, DMAB + Page-Hinkley** (non-stationary AOS) | Yes — public algorithms (Garivier & Moulines 2008; DaCosta 2008) | **Excellent** — same as UCB1 plus a discount factor / window; fully seedable | **Nil** — pure Python, tens of extra LOC | Same plug-in as UCB1; adds decay so stale operators are dropped as cells fill | **Yes** |
| **Adaptive Pursuit / Probability Matching** (Thierens 2005) | Yes — public algorithm | **Good** — deterministic prob-vector update, but selection is a seeded roulette wheel (more RNG draws than UCB) | **Nil** — pure Python, ~100 LOC | Maintain a probability vector over operators; winner-take-most pursuit update; sample operator | **Yes** |
| **Contextual bandit / LinUCB / online logistic** (state → operator) | Yes — public algorithms | **Feasible-with-care** — fixed summation order + rounding; **no numpy/BLAS** (threaded reductions reorder sums) | **Light** — pure Python + a rank-1 matrix update (Sherman–Morrison); ~200–400 LOC | Context = `QualityVector` fields of the parent cell; per-operator linear model predicts survival | **Yes** |
| **Probability calibration** (temperature, Platt, isotonic-PAVA) | Yes — public algorithms | **Excellent** — PAVA is O(n) deterministic; temperature is one scalar | **Nil** — pure Python, ~50–120 LOC | Turns raw bandit/logistic scores into an *honest* P(elite) for budgeting & reporting | **Yes** — calibrates confidence only |
| **Laya (the model)** | **Open-weight, Apache-2.0** | **No** — card warns fp differs across batch shape / device / precision; bf16/fp16 can flip argmaxes | **Very heavy** — 421M params, `torch 2.14` + `transformers 5.x` + `huggingface_hub`, ~808 MB weights | Only the *idea* transfers (typed decision + calibrated prob, no text) — not the weights | Idea yes; the model as-is fails deps/determinism |
| **Jev (the model)** | **No — proprietary, closed hosted API** ($0.042/1M tokens) | N/A (hosted) | N/A (would be an external paid service — banned by constraint 1) | Only the *concept*; cannot be used | Cannot use — hosted, closed |
| **CMA-ME / DQD / pyribs emitters** | Yes — pyribs MIT-licensed | **Poor** — CMA covariance & gradients are float-heavy; pyribs = numpy | **Heavy** — numpy (DQD implies gradients/torch) | Ideas only: "multi-emitter" = run several operator-biased streams; gradient/CMA machinery N/A to a discrete symbolic genome | Idea yes; machinery off-limits |
| **Neural-guided combinatorial / program synthesis** (CROSSBEAM, LambdaBeam, NGDS, DeepCoder-style policy/value) | Mixed — several have open code | **Poor** — nets need GPU/torch; float & training nondeterminism | **Very heavy** — torch, training pipeline, data | Concept only: a learned policy scores candidate moves — the contextual bandit is the cheap, deterministic stand-in | Concept yes; implementation off-limits |

---

## 3. Deep-dive on the top recommendations

### 3.0 The reward is already in the code (why AOS fits SPIE perfectly)

The whole difficulty of learning-to-search is usually *credit assignment*: "was this move good?" In SPIE the answer is already computed, deterministically, by `mapelites.place()`. Its `Archive.tally` records, per candidate, one of:

- `placed` — child occupied an **empty** niche (a new elite was born),
- `replaced` — child beat the incumbent in its niche (an elite improved),
- `dominated` — child certified but lost to the incumbent,
- `no-op` — the operator returned `None` (didn't apply to this puzzle),
- `invalid` / `verify-failed` / `unsolvable` — the child failed a formal gate.

Define the **survival reward** `r ∈ {0,1}`: `r = 1` iff `adm.reason ∈ {"placed","replaced"}`, else `0`. This is precisely the "offspring survives" signal used by the published QD-as-MAB work and by Cully & Demiris's *curiosity* score. Crucially, `r` is a *consequence* of the certification gate, not a substitute for it — so using it to steer keeps the learned component strictly outside the correctness path.

Each `Lineage` already carries `operator` and `family`, so per-operator/per-family credit assignment needs no new bookkeeping beyond counters.

### 3.1 TOP PICK — UCB-style Adaptive Operator Selection (+ non-stationary decay)

**What it is.** Treat each of the 16 operators (arm) — and, separately, each occupied cell (arm) — as a bandit arm. Pick the arm maximizing a UCB score, apply it, observe the survival reward, update counters. The parent-selection half is literally the algorithm from *"Quality-Diversity Selection as a Multi-Armed Bandit Problem"* (Sfikas et al.), which reported UCB parent selection beating uniform-random and greedy on QD metrics. The operator-selection half is textbook AOS (Fialho/DaCosta/Schoenauer/Sebag; Thierens).

**The selection rule** (the QD-MAB paper's own formula), for arm `i` with survival count `w(i)`, pull count `n(i)`, total pulls `N`:

```
U(i) = w(i)/n(i)  +  λ · sqrt( ln(N) / n(i) )      if n(i) > 0
U(i) = +infinity                                    if n(i) == 0   (force each arm once)
λ = 1/sqrt(2)   (optimal when reward ∈ [0,1])
```

Pick `argmax_i U(i)`; break ties by **sorted arm key** (operator `__name__`, or sorted niche tuple), falling back to the existing seeded `rng` only among exact ties. That keeps selection as order-deterministic as today's `rng.choice(sorted(...))`.

**Non-stationarity (do not skip this).** Operator utility drifts: `hide_variable` is gold while the belief-count axis is empty and near-useless once those cells are full. Stationary UCB will keep over-crediting early winners. Fixes, cheapest first:
- **Discounted UCB** (Garivier & Moulines 2008): on each update `n(i) ← γ·n(i) + 1`, `w(i) ← γ·w(i) + r`, with `γ ≈ 0.95–0.99`. One extra multiply; fully deterministic.
- **Sliding-window UCB**: keep the last `τ` outcomes per arm in a deque; recompute `w,n` over the window.
- **DMAB + Page-Hinkley** (DaCosta et al. 2008): run stationary UCB but reset an arm's stats when a Page-Hinkley test flags a change in its reward stream. Most powerful, ~30 extra LOC, still deterministic.

**Concrete plug-in into `mapelites.py`.** Today `evolve()` (lines ~266–284) does:

```python
parent_niche = rng.choice(sorted(archive.cells))   # (A) which elite to expand
parent_cell  = archive.cells[parent_niche]
operator     = rng.choice(OPERATORS)               # (B) which operator to apply
child        = operator(parent_cell.puzzle, rng)
...
place(archive, child, corpus, lineage)
```

Add two small bandit state objects (persisted on `Archive` as new, default-empty fields so old archives still round-trip — bump an archive schema version). Sketch:

```python
# New, serialized on Archive (defaults keep back-compat):
#   op_stats:   dict[str, tuple[float, float]]      # operator __name__ -> (w, n)
#   cell_stats: dict[Niche, tuple[float, float]]    # niche          -> (w, n)
GAMMA = 0.98   # discount for non-stationarity; 1.0 == plain UCB1
LAM   = 0.7071067811865476  # 1/sqrt(2)

def _ucb(w, n, N):
    if n <= 0.0:
        return float("inf")
    return round(w / n + LAM * math.sqrt(math.log(N) / n), 6)   # round → byte-stable

def _pick(keys, stats):                      # keys already sorted → deterministic
    N = sum(n for _, n in stats.values()) or 1.0
    best, best_u = None, -1.0
    for k in keys:                           # iterate in sorted order
        w, n = stats.get(k, (0.0, 0.0))
        u = _ucb(w, n, N)
        if u > best_u:                       # strict > keeps the FIRST (sorted) on ties
            best, best_u = k, u
    return best

def _credit(stats, key, r):                  # discounted survival update
    w, n = stats.get(key, (0.0, 0.0))
    stats[key] = (GAMMA * w + r, GAMMA * n + 1.0)
```

Then in the loop: `parent_niche = _pick(sorted(archive.cells), archive.cell_stats)` and `operator = OPERATORS[_pick(range(len(OPERATORS)), ...)]` (key operators by their sorted `__name__`). After `place(...)` returns `adm`, compute `r = 1.0 if adm.reason in ("placed","replaced") else 0.0` and call `_credit` for both the operator and the parent niche. **`no-op` handling:** when `operator(...)` returns `None`, prefer *not* charging a full pull (or charge `r=0` but keep it eligible) — several operators only apply to some puzzles, and counting inapplicability as failure would unfairly starve them. Flag this as a tuning choice.

**Hierarchical option.** Because operators are grouped in `FAMILIES` (4 × 4), a clean variant is a **two-level bandit**: pick a family by UCB, then an operator within it by UCB. This shares credit across an operator's siblings (faster warm-up with only 16 arms) and matches the roadmap's 4-family structure. Either is fine; flat-16 is simplest.

**Why this is the top pick:** zero new dependencies, ~150–300 LOC, reward already computed, and the *only* new nondeterminism risk is float ties — neutralized by the `round(...,6)` already used for `fitness_of` plus sorted-key tie-breaks.

### 3.2 RUNNER-UP — Adaptive Pursuit / Probability Matching (Thierens 2005)

**What it is.** Instead of a UCB score, maintain a **probability vector** `P` over the 16 operators and a quality estimate `Q` per operator. On observing reward `r_a` for the operator used:

```
Q_a ← Q_a + α (r_a − Q_a)                         # exponential-recency quality, α∈(0,1]
```

**Probability Matching (PM)** sets selection probabilities proportional to quality, floored so no operator dies:

```
P_a ← p_min + (1 − K·p_min) · Q_a / Σ_b Q_b        # K = number of operators (16)
```

**Adaptive Pursuit (AP)** instead pushes probability toward the current best operator `a* = argmax_a Q_a`:

```
p_max = 1 − (K−1)·p_min
P_a*  ← P_a* + β (p_max − P_a*)                    # pursue the winner, learning rate β
P_a   ← P_a  + β (p_min − P_a)     for a ≠ a*      # decay the rest
```

Then sample the operator from `P` (roulette wheel) using the seeded `rng`. AP adapts faster and tracks non-stationary rewards better than PM (Thierens' result), and the `α`/`p_min` recency already handles drift, so no separate discounting is needed.

**Trade-off vs. UCB.** AP/PM is arguably even smaller (~100 LOC) and its `p_min` floor guarantees continued exploration of every operator. But selection is a *roulette-wheel sample*, i.e. an extra `rng` draw per iteration, whereas UCB is a deterministic argmax with RNG only on ties. Both are byte-reproducible under a fixed seed, but UCB touches the RNG less, which is why it edges ahead for SPIE's "determinism is sacred" posture. AP maps to `evolve()` identically (swap the `_pick` internals for a `Q`/`P` update + `rng`-weighted choice over sorted operators).

### 3.3 SECOND RUNNER-UP — the "decision-model" idea as a tiny contextual bandit + calibration

This is where you **borrow the Laya/Jev concept, not the model**. Laya/Jev's pitch is: *given a state, emit a typed decision plus a mathematically calibrated probability, in one forward pass, with no text generation and no authority over ground truth.* Strip away the 421M-param ModernBERT encoder and that is exactly a **contextual bandit with a calibrated head** — implementable in pure Python.

**Context features** (all already on the parent cell's `QualityVector`, all deterministic functions of the puzzle):

| Feature | Source field |
|---|---|
| difficulty band, raw | `difficulty.band`, `difficulty.raw` |
| belief size, sensing, plan branching, depth spread, info gain | `difficulty.belief_count`, `.sensing_actions`, `.plan_branching`, `.depth_spread`, `.information_gain` |
| free/forced choices, max branching | `difficulty.free_choices`, `.forced_steps`, `.max_branching` |
| novelty, elegance, minimality, rule count | `novelty.score`, `elegance.score`, `.minimality_ratio`, `.rule_count` |
| strategy effort, deceptiveness | `strategy.backtracks`, `.inference_depth`, `.branching_faced`, `surprise.score` |
| lineage depth, niche coords | `lineage.generation`, the 4-tuple `niche` |

**Model.** One linear/logistic model per operator (or one model with operator-indicator features). Predict `P(survive | context, operator)`. **LinUCB**-style exploration: score `= θ_opᵀx + α·sqrt(xᵀ A_op⁻¹ x)`; update `A_op += xxᵀ`, `b_op += r·x`, maintained by a **Sherman–Morrison rank-1 update** so you never invert a matrix. All pure Python lists, no numpy.

**Why third, not first.** It only pays off if operator success genuinely *depends on puzzle features* (plausible here — `hide_variable` needs a hideable variable, `add_resource_budget` needs headroom). But it's more code, needs feature scaling/bucketing, and its float accumulation must be order-pinned to stay byte-reproducible. Start with the context-free bandit (3.1); graduate to this only if per-niche behaviour shows the context matters.

### 3.4 Calibration — making the confidence honest (thesis-safe)

"Calibrated probability" is the selling point of the decision-model framing, and Laya's own card admits it *"ships over-confident"* (ECE ≈ 0.466 → 0.081 only after temperature scaling). If SPIE reports a confidence, it should be honest. Three pure-Python, deterministic options, cheapest first:

- **Temperature scaling** — one scalar `T`; replace score `s` with `sigmoid(s/T)` (or divide logits by `T`). Fit `T` by minimizing log-loss on a held-out slice of past (score, survived) pairs via a deterministic 1-D line search. ~20 LOC.
- **Platt scaling** — fit `sigmoid(a·s + b)` (a 2-parameter logistic) on past pairs; deterministic gradient descent. ~40 LOC.
- **Isotonic regression via PAVA** (Pool-Adjacent-Violators) — the non-parametric option: sort by raw score, run PAVA to get a monotone step function mapping score → empirical survival frequency. PAVA is an O(n) single left-to-right pass, completely deterministic, ~40 LOC, no dependency. This is the most flexible and is a natural fit given SPIE already rounds and sorts everywhere.

Calibration is **purely steering/reporting**: it rescales confidence numbers used for budget allocation and dashboards. It never sees a puzzle's certificate and never gates admission — so it is trivially thesis-safe.

---

## 4. Explicit warnings

1. **Determinism — floats & dependencies.** Pure-Python `float` arithmetic is deterministic on a fixed CPython build, but (a) cross-platform ULP differences in `math.log`/`math.sqrt`/division could flip an argmax tie, and (b) **any** move to `numpy`/BLAS/torch/GPU reintroduces reordered (threaded) reductions and float nondeterminism — the Laya model card itself warns its numerics differ across batch shape, device, and precision, and can *"flip a small number of argmaxes."* **Mitigations:** round every score to 6 dp (matching `fitness_of`/`niche_of` discipline) before comparison; break ties on sorted keys; keep the single seeded `random.Random`; forbid numpy/torch in this module. A pure-Python bandit satisfies all of this; a neural policy does not.

2. **Never let confidence touch correctness.** The one forbidden optimization is "skip `certify()`/`verify()` when the policy is confident." That would move a learned model into the correctness path and break the thesis. The bandit chooses *what to try*; `place()`'s `validate → verify → certify` stays the sole authority, and the reward is *derived from* that gate (survival), never a replacement for it. Any code that reads a confidence before/instead of a gate is a red flag in review. Likewise, keep the learned signal out of `QualityVector`, niches, and fitness — those are measurement, and the module docstrings already guard that boundary (e.g. surprise is deliberately kept out of fitness).

3. **Non-stationarity is not optional.** Plain UCB1 over-commits to operators that paid off early and then stalls once those niches saturate. Use discounted/sliding-window UCB or DMAB+Page-Hinkley (Section 3.1). Without decay the search can converge to a near-degenerate operator mix — worse than today's uniform baseline on late-stage diversity.

4. **`no-op` accounting.** Operators return `None` when inapplicable (`_clean` / guard failure → `no-op` tally). Counting that as a failed pull unfairly starves narrowly-applicable operators (e.g. `add_reset_action`, `make_observation_costly`). Decide explicitly: resample on `None`, or record `r=0` but do not let it dominate the pull count. This is a correctness-of-*search* subtlety, not of puzzles, but it materially changes behaviour.

5. **Archive byte-reproducibility across the change.** Adding bandit counters to `Archive` changes `archive_to_json` output, so the archive-determinism golden files change. That is expected — version the archive schema and regenerate goldens deliberately; the property to preserve is *"same seed ⇒ same bytes,"* not *"same bytes as the old version."*

6. **Open-source / license hygiene.** The *algorithms* (UCB, AP/PM, DMAB, LinUCB, PAVA, Platt/temperature) are public-domain math — safe to reimplement. If you lift code from a repo (e.g. the QD-MAB authors' GitHub, or a PAVA gist), check and record that file's license before copying; prefer a clean-room reimplementation to sidestep the question entirely. Do **not** vendor Laya (Apache-2.0 but 808 MB + torch/transformers) and never call Jev (closed, hosted, paid).

---

## 5. Sources

**Adaptive Operator Selection & bandits for evolutionary / QD search**
- [Quality-Diversity Selection as a Multi-Armed Bandit Problem (arXiv 2104.08781)](https://arxiv.org/html/2104.08781v1) — UCB1 parent selection for MAP-Elites; "survival" reward; the most directly applicable result. *Paper; authors' code linked from the paper (verify repo license before reuse).*
- [Adaptive Operator Selection with Dynamic Multi-Armed Bandits (DaCosta, Fialho, Schoenauer, Sebag; GECCO'08)](https://gpbib.pmacs.upenn.edu/gecco2008/docs/p913.pdf) — DMAB + Page-Hinkley; compared to PM and Adaptive Pursuit. *Academic paper.*
- [Analysis of adaptive operator selection / bandit AOS (LRI tech report)](http://www.lri.fr/~marc/Papers/banditGECCO10.pdf) — credit assignment framing for AOS. *Academic paper (PDF did not text-extract in this survey; cited from the AOS literature).*
- [An Adaptive Pursuit Strategy for Allocating Operator Probabilities (Thierens, GECCO'05)](https://gpbib.cs.ucl.ac.uk/gecco2005/docs/p1539.pdf) and [lecture slides](https://ics-websites.science.uu.nl/docs/vakken/ea/slides/adapPursuit.pdf) — Adaptive Pursuit vs. Probability Matching update rules. *Academic; the AP/PM formulas in §3.2 are the canonical formulations from this line of work (source PDFs are Flate-compressed and did not text-extract here).*
- [A Unified Framework for the Adaptive Operator Selection of Discrete Parameters (arXiv 2005.05613)](https://arxiv.org/html/2005.05613v1) — modern survey unifying PM / AP / DMAB / UCB AOS. *Academic paper.*
- [UCB Algorithms for Adaptive Operator Selection in MOEA/D (Springer)](https://link.springer.com/chapter/10.1007/978-3-319-15934-8_28) — UCB AOS in decomposition-based MOEA. *Paywalled chapter.*
- [Adaptive Operator Selection based on Dynamic Thompson Sampling for MOEA/D (arXiv 2004.10874)](https://arxiv.org/html/2004.10874v1) — DYTS, a Thompson-sampling AOS alternative to UCB. *Academic paper.*

**Non-stationary bandits (for the decay recommendation)**
- [On Upper-Confidence Bound Policies for Non-Stationary Bandit Problems (Garivier & Moulines, arXiv 0805.3415)](https://arxiv.org/html/0805.3415v1) — discounted-UCB and sliding-window-UCB, with regret bounds. *Academic paper.*
- [Empirical Comparison of Forgetting Mechanisms for UCB-based Algorithms (arXiv 2511.19240)](https://arxiv.org/abs/2511.19240) — recent (2025) comparison of discount vs. window forgetting. *Academic paper.*

**MAP-Elites emitters (ideas only)**
- [Covariance Matrix Adaptation for the Rapid Illumination of Behavior Space — CMA-ME (arXiv 1912.02400)](http://arxiv.org/pdf/1912.02400v1) — *Academic paper.*
- [Multi-Emitter MAP-Elites (arXiv 2007.05352)](https://arxiv.org/html/2007.05352v2) — the borrowable "several biased emitters" concept. *Academic paper.*
- [Gradient-Informed QD for Discrete Spaces / DQD (arXiv 2306.05138)](https://arxiv.org/html/2306.05138v2) — gradient emitters (off-limits: gradients). *Academic paper.*
- [pyribs documentation](https://docs.pyribs.org/en/latest/index.html) and [ribs on PyPI](https://pypi.org/project/ribs/0.3.0/) — reference implementation of CMA-ME. *Library — MIT-licensed but numpy-dependent; ideas only.*

**Neural-guided combinatorial / program synthesis (concept only)**
- [Learning to Search in Bottom-Up Program Synthesis — CROSSBEAM (arXiv 2203.10452)](https://arxiv.org/html/2203.10452?fallback=original) — *Academic paper; torch-based.*
- [Neural Program Search with Higher-Order Functions — LambdaBeam (arXiv 2306.02049)](https://arxiv.org/pdf/2306.02049) — *Academic paper.*
- [Neural-Guided Deductive Search — NGDS (arXiv 1804.01186)](https://arxiv.org/html/1804.01186v1) — *Academic paper.*
- [Learning to Control Local Search for Combinatorial Optimization (arXiv 2206.13181)](https://arxiv.org/html/2206.13181v1) — learned steering of local search. *Academic paper.*

**Contextual bandits (for the "decision-model" replica)**
- [A Contextual Bandit Bake-off (arXiv 1802.04064)](https://arxiv.org/html/1802.04064v2) — practical comparison incl. LinUCB / online-logistic. *Academic paper.*
- [Adapting multi-armed bandit policies to contextual scenarios (arXiv 1811.04383)](https://arxiv.org/html/1811.04383v2) — lightweight contextual reductions. *Academic paper.*
- [Improved Thompson Sampling for Logistic Contextual Bandits (arXiv 1805.07458)](https://arxiv.org/html/1805.07458v1) — *Academic paper.*

**Probability calibration**
- [scikit-learn `_isotonic.pyx` (PAVA implementation reference)](https://github.com/mjbommar/scikit-learn/blob/main/sklearn/_isotonic.pyx) — algorithm reference. *BSD-3-Clause (scikit-learn); reimplement clean-room in pure Python.*
- [PAV — pure-Python Pool-Adjacent-Violators (gaurav324/PAV)](https://github.com/gaurav324/PAV/blob/master/python/pav.py) and [a PAVA gist](https://gist.github.com/vgoklani/9499893) — small pure-Python PAVA examples. *Check each repo/gist license before copying; prefer clean-room.*
- [scipy `isotonic_regression` docs](https://docs.scipy.org/doc/scipy-1.17.0/reference/generated/scipy.optimize.isotonic_regression.html) — PAVA reference & properties. *Docs (BSD).*
- [A Deep Dive into Isotonic Regression and the PAVA Algorithm](https://33rdsquare.com/isotonic-regression-and-the-pava-algorithm/) — tutorial. *Blog.*

**Decision models / System-1 models (idea to borrow; not the weights)**
- [Laya model card (Hugging Face, convaiinnovations/laya)](https://huggingface.co/convaiinnovations/laya/blob/main/README.md) — **Apache-2.0**, 421M params, ModernBERT-large encoder + typed decision head, ~808 MB weights, `torch 2.14` + `transformers 5.x` + `huggingface_hub`; RLCD calibration via strictly-proper scoring rules; card admits over-confidence and non-bit-exact numerics.
- [Laya GitHub (NandhaKishorM/laya)](https://github.com/NandhaKishorM/laya) — **Apache-2.0**; Python ≥3.10; confirms torch/transformers floor and the "Jev is a closed hosted API" comparison ($0.042/1M tokens).
- [Laya project site](https://laya.convaiinnovations.com/) — "33 ms Multilingual System-1 Decision Engine with Calibrated Probabilities."
- [Laya is a 421M open-weights answer to Jev (dev.to)](https://dev.to/techaiwire/laya-is-a-421m-open-weights-answer-to-jev-4n97) — Apache-2.0 framing vs. proprietary Jev. *Blog.*
- [mariojcr/laya-onnx (Hugging Face)](https://huggingface.co/mariojcr/laya-onnx) and [receptron/laya (Node/ONNX runner)](https://github.com/receptron/laya) — ONNX exports/clients. *Apache-2.0 lineage; still torch/onnx-scale, ideas only.*
- [laya on PyPI](https://pypi.org/project/laya/0.1.2/) — packaging/deps confirmation.

*Note: Jev (TypeSafe AI) is proprietary and hosted; it is out of bounds under SPIE's "open only, no external service" constraint and is cited only for the concept.*

