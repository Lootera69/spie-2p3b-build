"""Exact Bayesian inference and optimal adaptive yes/no planning, without ML or LLMs."""

from __future__ import annotations

from fractions import Fraction
from functools import cache
from itertools import permutations, product

from ...forge.corpus import digest


def bayes_propose(names: list[str], level: int, rng) -> dict | None:
    priors = [1] * 4 if level == 1 else [rng.randint(1, 7) for _ in names]
    rates = [[rng.randint(1, 9) for _ in range(level)] for _ in names]
    observed = [True] * level if level < 3 else [True, False, True]
    unnormalised = []
    for weight, row in zip(priors, rates, strict=True):
        probability = Fraction(weight, sum(priors))
        for rate, positive in zip(row, observed, strict=True):
            probability *= Fraction(rate if positive else 10 - rate, 10)
        unnormalised.append(probability)
    normalizer = sum(unnormalised)
    posterior = [p / normalizer for p in unnormalised]
    ordered = sorted(range(4), key=lambda i: posterior[i], reverse=True)
    best, second = ordered[:2]
    if posterior[best] == posterior[second]:
        return None
    # Avoid effectively certain answers or indistinguishably close probabilities.
    margin = posterior[best] - posterior[second]
    if not Fraction(1, 25) <= margin <= Fraction(3, 5):
        return None
    prior_leader = max(range(4), key=lambda i: priors[i])
    likelihoods = [unnormalised[i] / priors[i] for i in range(4)]
    reversal = priors[best] < priors[prior_leader]
    base_rate_matters = likelihoods[best] < max(likelihoods)
    score = 20 * level + 10 * reversal + 10 * base_rate_matters
    return {
        "names": names, "priors": priors, "positive_rates_out_of_ten": rates,
        "observed_positive": observed, "posterior": [str(p) for p in posterior],
        "answer_index": best, "score": score,
        "quality": {"evidence_steps": level, "hypotheses": 4,
                    "posterior_margin": str(margin), "prior_leader_overturned": reversal,
                    "base_rates_change_likelihood_only_winner": base_rate_matters},
    }


def bayes_check(model: dict) -> dict:
    rates = model["positive_rates_out_of_ten"]
    observed = model["observed_positive"]
    # Independent finite experiment: each readout draws one of ten tickets.
    # Enumerate outcome tuples, rather than multiply the stored likelihoods.
    frequencies = []
    for prior, row in zip(model["priors"], rates, strict=True):
        matching = sum(
            all((ticket < cutoff) == positive for ticket, cutoff, positive
                in zip(tickets, row, observed, strict=True))
            for tickets in product(range(10), repeat=len(observed))
        )
        frequencies.append(prior * matching)
    total = sum(frequencies)
    checked = [Fraction(count, total) for count in frequencies]
    if [str(p) for p in checked] != model["posterior"]:
        raise RuntimeError("Bayesian update/finite-frequency disagreement")
    winner = model["answer_index"]
    if any(checked[winner] <= p for i, p in enumerate(checked) if i != winner):
        raise RuntimeError("Bayesian answer is tied or incorrect")
    steps = []
    for i, name in enumerate(model["names"]):
        factors = [str(Fraction(r if positive else 10 - r, 10))
                   for r, positive in zip(rates[i], observed, strict=True)]
        steps.append(f"{name}: prior weight {model['priors'][i]} × "
                     + " × ".join(factors) + f"; normalized posterior {checked[i]}.")
    steps.append(f"{model['names'][winner]} has the largest posterior. "
                 "This means most likely under the model, not certain.")
    shape = sorted((p, tuple(r)) for p, r in zip(model["priors"], rates, strict=True))
    return {
        "method": "exact-bayes-and-independent-finite-experiment",
        "frequency_counts": frequencies, "posterior": [str(p) for p in checked],
        "agree": True, "steps": steps,
        "structural_key": digest(["bayes", shape, observed]),
        "scope": "the explicitly stated priors, fictional readouts and conditional independence",
    }


def optimal_costs(weights: list[int], tests: list[list[int]]) -> tuple[list[Fraction], dict]:
    """Bellman recursion on a finite belief state; all questions have unit cost."""
    masks = [sum(1 << i for i in members) for members in tests]

    @cache
    def mass(state):
        return sum(w for i, w in enumerate(weights) if state & (1 << i))

    @cache
    def solve(state):
        if state.bit_count() == 1:
            return Fraction(0), {"answer": state.bit_length() - 1}
        candidates = []
        for index, mask in enumerate(masks):
            yes, no = state & mask, state & ~mask
            if not yes or not no:
                continue
            left, left_tree = solve(yes)
            right, right_tree = solve(no)
            value = 1 + Fraction(mass(yes), mass(state)) * left
            value += Fraction(mass(no), mass(state)) * right
            candidates.append((value, index, left_tree, right_tree))
        if not candidates:
            raise ValueError("Available questions cannot distinguish the hidden cards")
        value, index, yes_tree, no_tree = min(candidates, key=lambda entry: (entry[0], entry[1]))
        return value, {"question": index, "yes": yes_tree, "no": no_tree}

    state = (1 << len(weights)) - 1
    costs = []
    for mask in masks:
        yes, no = state & mask, state & ~mask
        if not yes or not no:
            raise ValueError("A first question must split the belief state")
        costs.append(1 + Fraction(mass(yes), mass(state)) * solve(yes)[0]
                     + Fraction(mass(no), mass(state)) * solve(no)[0])
    return costs, solve(state)[1]


def planning_propose(names: list[str], level: int, rng) -> dict | None:
    n = len(names)
    weights = [1] * n if level == 1 else [rng.randint(1, 6) for _ in names]
    # Complement questions carry identical information; never offer both.
    options = list(range(1, (1 << (n - 1))))
    masks = rng.sample(options, 4)
    signatures = {tuple(bool(mask & (1 << i)) for mask in masks) for i in range(n)}
    if len(signatures) != n:
        return None
    tests = [[i for i in range(n) if mask & (1 << i)] for mask in masks]
    costs, tree = optimal_costs(weights, tests)
    best = min(costs)
    if costs.count(best) != 1:
        return None
    answer = costs.index(best)
    margin = sorted(costs)[1] - best
    score = 20 * level + min(10, int(margin * 20))
    return {
        "names": names, "weights": weights, "tests": tests,
        "expected_questions": [str(c) for c in costs], "tree": tree,
        "answer_index": answer, "score": score,
        "quality": {"hypotheses": n, "lookahead": "until exact identification",
                    "expected_questions": str(best), "optimality_margin": str(margin)},
    }


def planning_check(model: dict) -> dict:
    names, weights, tests = model["names"], model["weights"], model["tests"]

    def exhaustive(remaining: frozenset[int]) -> Fraction:
        if len(remaining) == 1:
            return Fraction(0)
        possibilities = []
        for members in tests:
            yes, no = remaining.intersection(members), remaining.difference(members)
            if yes and no:
                total = sum(weights[i] for i in remaining)
                cost = Fraction(sum(weights[i] for i in yes), total) * exhaustive(yes)
                cost += Fraction(sum(weights[i] for i in no), total) * exhaustive(no)
                possibilities.append(1 + cost)
        if not possibilities:
            raise RuntimeError("Planning leaves indistinguishable cards")
        return min(possibilities)

    universe = frozenset(range(len(names)))
    checked = []
    for members in tests:
        yes, no = universe.intersection(members), universe.difference(members)
        cost = Fraction(sum(weights[i] for i in yes), sum(weights)) * exhaustive(yes)
        cost += Fraction(sum(weights[i] for i in no), sum(weights)) * exhaustive(no)
        checked.append(1 + cost)
    if [str(v) for v in checked] != model["expected_questions"]:
        raise RuntimeError("Bellman/exhaustive decision-tree disagreement")
    answer = model["answer_index"]
    if checked.count(min(checked)) != 1 or checked[answer] != min(checked):
        raise RuntimeError("No unique optimal first question")
    depths, routes = [], []
    for identity, name in enumerate(names):
        node, route = model["tree"], []
        while "question" in node:
            index = node["question"]
            truth = identity in tests[index]
            route.append(f"{chr(65 + index)}={'yes' if truth else 'no'}")
            node = node["yes" if truth else "no"]
            if len(route) >= len(names):
                raise RuntimeError("Decision tree contains a non-shrinking route")
        if node["answer"] != identity:
            raise RuntimeError("Decision tree misidentifies a card")
        depths.append(len(route))
        routes.append(f"If the card is {name}: " + " → ".join(route) + ".")
    expected = sum(Fraction(w, sum(weights)) * depth
                   for w, depth in zip(weights, depths, strict=True))
    if expected != checked[answer]:
        raise RuntimeError("Decision-tree rollout cost disagreement")
    steps = [f"Start with Question {chr(65 + i)}: optimal expected total {cost} questions."
             for i, cost in enumerate(checked)]
    steps.extend(routes)
    # Canonicalise both card names and question ordering for in-batch shape dedup.
    shapes = []
    for order in permutations(range(4)):
        shapes.append(sorted((weights[i], tuple(int(i in tests[j]) for j in order))
                             for i in range(len(names))))
    return {
        "method": "bellman-planning-and-exhaustive-policy-check",
        "expected_questions": [str(c) for c in checked], "rollout_depths": depths,
        "agree": True, "steps": steps,
        "structural_key": digest(["planning", min(shapes)]),
        "scope": "optimal among the four stated, noiseless, unit-cost questions and given priors",
    }
