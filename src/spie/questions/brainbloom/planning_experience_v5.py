"""Select consequentially different plans within the unchanged 48-model budget.

Development-only physical foundations seed a role-balanced population. A genuine
physical edit can change its dependencies; an independent foundation restart can
escape a local optimum. Every assessment and final selection retains revision12's
physical, strategy, all-shortest-route causal and quality-tradeoff requirements.
No request depends on cross-request novelty state or on precomputed answers.
"""

from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from functools import lru_cache
from itertools import permutations
from random import Random

from ...forge.corpus import compact, digest
from . import planning_causal_paths as causal_paths
from . import planning_experience as previous
from . import planning_foundations_v3 as foundations_v3
from . import planning_judgment as judgment
from . import planning_judgment_prior as prior
from . import state_planning as domain
from . import state_planning_variety as variety

VERSION = "planning-experience-v5"
CERTIFICATE_VERSION = "planning-experience-core-bfs-v5"
SELECTION_VERSION = "role-first-quality-capped-dependency-v5"
PROPOSAL_BUDGET = previous.PROPOSAL_BUDGET
TARGET = {**previous.TARGET, "all_shortest_routes_linked": True}
TRADEOFF_DIMENSIONS = (
    "trap_choices_on_optimal_episodes",
    "maximum_forced_steps",
    "rule_rows",
    "solution_steps",
)
REGRET_LIMITS = dict(zip(TRADEOFF_DIMENSIONS, (0, 0, 0, 1), strict=True))
PHYSICAL_FIELDS = ("capacity", "initial_energy", "initial_gates", "charger", "routes", "switches")
ExperienceExhausted = previous.ExperienceExhausted


def quiz_stem(model):
    """Compact complete rules; the episode separately retains its full story."""
    names = model["names"]
    rooms = ", ".join(f"{i + 1}={name}" for i, name in enumerate(names))
    routes = "; ".join(f"{a + 1}→{b + 1}:{cost}" + (f"/{'AB'[gate]}" if gate >= 0 else "")
                       for a, b, cost, gate in model["routes"])
    switches = "; ".join(f"{at + 1}:{''.join('AB'[bit] for bit in range(2) if mask & (1 << bit))}/{cost}"
                         for at, mask, cost in model["switches"])
    gates = ", ".join(f"{'AB'[i]}={'open' if state else 'closed'}"
                      for i, state in enumerate(model["initial_gates"]))
    return (f"Rooms: {rooms}. Start 1; goal {len(names)}; energy {model['initial_energy']}/{model['capacity']}. "
            "Each action takes one turn. Energy stays nonnegative.\n"
            f"Only listed one-way routes (energy cost/open gate; omitted=none): {routes}.\n"
            f"Initially {gates}. Switches persistently toggle listed gates (room:gates/energy): {switches}.\n"
            f"Recharge once at {model['charger'] + 1} to {model['capacity']}, only below capacity. "
            "Revisits allowed. Which first action minimizes total turns?")


def _mutate(model, rng):
    """Draw a genuine physical edit, including route rewiring.

    Enumerating legal values avoids spending an assessment on unchanged rules.
    This list performs no solving and conveys no acceptance guarantee. All
    returned models still pass the complete physical and experience gates.
    """
    changed = deepcopy(model)
    n = len(model["names"])
    edits = []
    existing = {(a, b) for a, b, _, _ in model["routes"]}
    for index, (origin, destination, cost, gate) in enumerate(model["routes"]):
        edits.extend(("route", index, 2, value) for value in range(1, 5) if value != cost)
        edits.extend(("route", index, 3, value) for value in (-1, 0, 1) if value != gate)
        edits.extend(
            ("route", index, 1, value)
            for value in range(n)
            if value not in (origin, destination) and (origin, value) not in existing
        )
    edits.extend(
        ("capacity", value)
        for value in range(max(3, model["initial_energy"]), 9)
        if value != model["capacity"]
    )
    edits.extend(
        ("initial_energy", value)
        for value in range(1, model["capacity"] + 1)
        if value != model["initial_energy"]
    )
    edits.extend(("charger", value) for value in range(1, n - 1) if value != model["charger"])
    edits.extend(("gate", index) for index in range(2))
    for index, (at, mask, cost) in enumerate(model["switches"]):
        edits.extend(("switch", index, 1, value) for value in (1, 2, 3) if value != mask)
        edits.append(("switch", index, 2, 1 - cost))
        if at:
            edits.extend(("switch", index, 0, value) for value in range(1, n - 1) if value != at)
    if len(model["routes"]) > n:
        edits.extend(
            ("remove-route", index) for index, row in enumerate(model["routes"]) if row[0] != 0
        )
    if len(model["routes"]) < 12:
        edits.extend(
            ("add-route", a, b)
            for a in range(1, n - 1)
            for b in range(n)
            if a != b and (a, b) not in existing
        )
    if len(model["switches"]) == 1:
        edits.extend(("add-switch", at) for at in range(1, n - 1))
    else:
        edits.append(("remove-switch",))
    edit = rng.choice(edits)
    if edit[0] == "route":
        changed["routes"][edit[1]][edit[2]] = edit[3]
    elif edit[0] == "switch":
        changed["switches"][edit[1]][edit[2]] = edit[3]
    elif edit[0] == "gate":
        changed["initial_gates"][edit[1]] ^= 1
    elif edit[0] == "remove-route":
        changed["routes"].pop(edit[1])
    elif edit[0] == "add-route":
        changed["routes"].append([edit[1], edit[2], rng.randint(1, 4), rng.choice((-1, 0, 1))])
    elif edit[0] == "add-switch":
        changed["switches"].append([edit[1], rng.randint(1, 3), rng.randrange(2)])
    elif edit[0] == "remove-switch":
        changed["switches"].pop()
    else:
        changed[edit[0]] = edit[1]
    changed["routes"].sort()
    changed["switches"].sort()
    return changed


def _foundation_at(names, level, profile, index):
    values = foundations_v3.FOUNDATIONS[(level, profile)][index]
    return {
        "version": domain.VERSION,
        "names": list(names),
        "level": level,
        "design_version": variety.VERSION,
        "strategy": profile,
        **dict(zip(PHYSICAL_FIELDS, deepcopy(values), strict=True)),
    }


def _assess(model):
    """Reuse the base graph; intervention gates need no committed-path analyses."""
    try:
        domain._validate(model)
    except ValueError:
        return None, None, "shape", 0
    graph = domain._graph(model)
    result = domain._analyse_graph(model, graph)
    steps = result["best_steps"]
    if steps is None or not domain.MIN_STEPS[model["level"] - 1] <= steps <= domain.MAX_STEPS:
        return None, None, "length", 1
    if (
        len(result["optimal_first_actions"]) != 1
        or sum(cost is not None for cost in result["committed_first_costs"].values()) < 2
        or max(result["later_committed_choices"], default=0) < 2
        or result["reachable_locations"] != len(model["names"])
    ):
        return None, None, "choices", 1
    variants = {mechanic: domain._graph(model, mechanic) for mechanic in domain.MECHANICS}
    ablations = {
        mechanic: domain._analyse_graph(model, variant, committed=False)
        for mechanic, variant in variants.items()
    }
    if any(
        domain._ablation_signature(row) == domain._ablation_signature(result)
        for row in ablations.values()
    ):
        return None, None, "mechanics", 5
    try:
        variety._profile_record(model, graph, variants["energy"])
    except ValueError:
        return None, None, "profile", 5
    return result, graph, None, 5


def _action_role(model, action):
    if action == "recharge":
        return action
    if action.startswith("switch_"):
        return "switch-start" if action == "switch_0" else "switch-away"
    destination = int(action.split("_")[2])
    if destination == len(model["names"]) - 1:
        return "move-goal"
    if destination == model["charger"]:
        return "move-charger"
    return "move-start" if destination == 0 else "move-interior"


def _role_sequence(model, quality):
    """A label-invariant representative of the complete optimal role sequences.

    Dynamic programming chooses the lexical minimum *role* sequence across all
    shortest paths, so room relabeling cannot change a later action tie-break.
    """
    decisions = {tuple(row["state"]): row for row in quality["decisions"]}
    sequences = {}
    for state, decision in sorted(decisions.items(), key=lambda pair: pair[1]["best_remaining"]):
        sequences[state] = min(
            (_action_role(model, row["action"]), *sequences.get(tuple(row["next_state"]), ()))
            for row in decision["actions"]
            if row["action"] in decision["optimal_actions"]
        )
    return list(sequences[domain._initial(model)])


def _topology_key(model):
    n = len(model["names"])
    shapes = []
    for interior in permutations(range(1, n - 1)):
        mapping = dict(zip((0, *interior, n - 1), range(n), strict=True))
        shapes.append(tuple(sorted((mapping[a], mapping[b]) for a, b, _, _ in model["routes"])))
    return digest([n, min(shapes)])


def _meaningful_roles(model, quality):
    """Canonical semantic roles after removing all nonconsequential actions."""
    decisions = {tuple(row["state"]): row for row in quality["decisions"]}
    sequences = {}
    for state, decision in sorted(decisions.items(), key=lambda pair: pair[1]["best_remaining"]):
        sequences[state] = min(
            ((_action_role(model, row["action"]),) if decision["meaningful"] else ())
            + sequences.get(tuple(row["next_state"]), ())
            for row in decision["actions"] if row["action"] in decision["optimal_actions"]
        )
    return list(sequences[domain._initial(model)])


def _quality(model, graph):
    quality = previous._evaluate_graph(model, graph, policies=False)
    linked, status = None, "not-required"
    decision_judgment = None
    if quality["meets_target"]:
        try:
            coverage = causal_paths.evaluate(model, graph, quality)
            linked = coverage["all_shortest_routes_linked"]
            status = "covered" if linked else "uncovered"
            if linked:
                decision_judgment = judgment.evaluate(model, graph, quality, coverage=coverage)
        except causal_paths.CausalCoverageExhausted:
            # An exhausted proof is never evidence that every route is linked.
            status = "unknown"
        except judgment.JudgmentExhausted:
            linked = None
            status = "judgment-unknown"
    quality["all_shortest_routes_linked"] = linked
    quality["causal_coverage_status"] = status
    quality["meets_target"] = quality["meets_target"] and linked is True
    quality["decision_judgment"] = decision_judgment
    return quality


@lru_cache(maxsize=256)
def _foundation_analysis(level, profile, index):
    """Reuse fixed foundation work without changing deterministic outcomes.

    Callers treat cached analyses as immutable; cache occupancy never enters a result or its
    accounting. Certification and selection replay always compile rules afresh.
    """
    model = _foundation_at(list("ABCDEF")[:level + 3], level, profile, index)
    result, graph, reason, graphs = _assess(model)
    quality = _quality(model, graph) if reason is None else None
    return result, graph, reason, graphs, quality


def _policy_rank(row, level):
    policies = {item["horizon"]: item for item in row["decision_judgment"]["policy_checks"]}
    shallow, deeper = policies[2], policies[5]

    def value(report, key):
        return Fraction(report[key])

    if level == 1:
        return (value(shallow, "success_probability"), value(shallow, "optimal_probability"),
                -value(shallow, "dead_end_probability"))
    if level == 2:
        return (value(deeper, "success_probability"), -value(deeper, "dead_end_probability"),
                value(deeper, "optimal_probability"))
    # Achievable success and fewer dead ends precede any efficiency advantage.
    return (value(deeper, "success_probability"), -value(shallow, "dead_end_probability"),
            -value(deeper, "dead_end_probability"),
            value(deeper, "success_probability") - value(shallow, "success_probability"),
            value(deeper, "optimal_probability") - value(shallow, "optimal_probability"),
            value(deeper, "optimal_probability"))


def _prior_choice(keys, support, rng):
    """Favor forms supported by fewer development families, with exact weights."""
    # LCM(1..12) makes every inverse family count an integer. Unknown forms
    # have weight one before scaling; a prior never bypasses a quality gate.
    weights = [27720 // max(1, len(support.get(key, ()))) for key in keys]
    draw = rng.randrange(sum(weights))
    for key, weight in zip(keys, weights, strict=True):
        if draw < weight:
            return key
        draw -= weight
    raise RuntimeError("Invalid decision-prior draw")


def _selection(comparisons, seed, level, policy_loader):
    """Reconstruct the exact lottery from independently reproducible records."""
    unique = {}
    for row in comparisons:
        if row["meets_target"]:
            unique.setdefault(row["structural_key"], row)
    candidates = sorted(unique.values(), key=lambda row: row["structural_key"])
    if not candidates:
        return None
    lexicographic = max(candidates, key=lambda row: row["rank"])
    bounded = [
        row
        for row in candidates
        if all(
            row["dimensions"][key] <= lexicographic["dimensions"][key] + limit
            for key, limit in REGRET_LIMITS.items()
        )
    ]

    def dominates(other, row):
        a = tuple(other["dimensions"][key] for key in TRADEOFF_DIMENSIONS)
        b = tuple(row["dimensions"][key] for key in TRADEOFF_DIMENSIONS)
        return all(left <= right for left, right in zip(a, b, strict=True)) and a != b

    def depth(row):
        item = row["decision_judgment"]
        cap = 3 if level == 3 else 2
        return (min(item["minimum_dependency_chain"], cap),
                min(item["minimum_meaningful_decisions"], cap))

    # Distinct consequential forms survive independently of ordinary travel.
    frontier = [
        row
        for row in bounded
        if not any(
            other["decision_judgment"]["decision_signature"]
            == row["decision_judgment"]["decision_signature"]
            and dominates(other, row)
            for other in bounded
        )
    ]
    signatures = sorted({row["decision_judgment"]["decision_signature"] for row in frontier})
    rng = Random(seed)
    roles = sorted({tuple(row["meaningful_role_sequence"]) for row in frontier})
    role = _prior_choice(roles, prior.MEANINGFUL_ROLE_SUPPORT, rng)
    in_role = [row for row in frontier if tuple(row["meaningful_role_sequence"]) == role]
    best_depth = max(map(depth, in_role))
    in_role = [row for row in in_role if depth(row) == best_depth]
    role_signatures = sorted({row["decision_judgment"]["decision_signature"] for row in in_role})
    signature = _prior_choice(role_signatures, prior.DECISION_SIGNATURE_SUPPORT, rng)
    in_signature = [row for row in in_role
                    if row["decision_judgment"]["decision_signature"] == signature]
    ranks = {row["attempt"]: _policy_rank(
        {"decision_judgment": {"policy_checks": policy_loader(row)}}, level
    ) for row in in_signature}
    best_policy = max(ranks.values())
    policy_pool = [row for row in in_signature if ranks[row["attempt"]] == best_policy]
    topologies = sorted({row["topology_key"] for row in policy_pool})
    topology = rng.choice(topologies)
    in_topology = [row for row in policy_pool if row["topology_key"] == topology]
    selected = rng.choice(in_topology)
    return {
        "version": SELECTION_VERSION,
        "scope": "Among recorded evaluated candidates meeting every mandatory gate.",
        "seed": seed,
        "level": level,
        "tradeoff_dimensions": list(TRADEOFF_DIMENSIONS),
        "tradeoff_direction": "minimize each dimension; no scalar improvement claim",
        "quality_reference": "lexicographic best recorded candidate meeting the hard target",
        "maximum_regret": dict(REGRET_LIMITS),
        "dominance_scope": "within each complete meaningful-decision signature",
        "draw_rule": (
            "bounded costs; inverse development-family "
            "support for meaningful roles; prefer linked depth within the chosen role; then signature; "
            "best level-specific success/efficiency policy rank; uniform topology and structure"
        ),
        "decision_signatures": signatures,
        "prior_version": prior.VERSION,
        "frontier_meaningful_roles": [list(item) for item in roles],
        "selected_meaningful_roles": list(role),
        "selected_role_signatures": role_signatures,
        "selected_decision_signature": signature,
        "selected_depth": list(best_depth),
        "selected_policy_rank": list(map(str, best_policy)),
        "policy_scope": "All legal arrivals count as success; optimality is a separate challenge.",
        "eligible_candidates": sum(row["meets_target"] for row in comparisons),
        "distinct_eligible_structures": len(candidates),
        "quality_bounded_structures": len(bounded),
        "frontier_attempts": sorted(row["attempt"] for row in frontier),
        "frontier_structures": len(frontier),
        "frontier_decision_signatures": len(signatures),
        "frontier_role_sequences": len({tuple(row["role_sequence"]) for row in frontier}),
        "frontier_topologies": len({row["topology_key"] for row in frontier}),
        "selected_role_sequence": list(selected["role_sequence"]),
        "selected_topology_key": topology,
        "selected_structural_key": selected["structural_key"],
        "selected_attempt": selected["attempt"],
        "selected_dimensions": deepcopy(selected["dimensions"]),
        "selected_rank": list(selected["rank"]),
        "lexicographic_attempt": lexicographic["attempt"],
        "lexicographic_dimensions": deepcopy(lexicographic["dimensions"]),
        "lexicographic_rank": list(lexicographic["rank"]),
        "selected_minus_lexicographic": {
            key: selected["dimensions"][key] - lexicographic["dimensions"][key]
            for key in TRADEOFF_DIMENSIONS
        },
    }


def certify(model):
    """Independently certify the selected model, ignoring search provenance."""
    if model.get("experience_version") != VERSION:
        raise ValueError("Unsupported planning experience version")
    graph = variety._compiled_graph(model)
    variants = {mechanic: variety._compiled_graph(model, mechanic) for mechanic in domain.MECHANICS}
    profile = variety._profile_record(model, graph, variants["energy"])
    certificate = previous._evaluate_graph(model, graph)
    best = certificate["dimensions"]["solution_steps"]
    initial = domain._initial(model)
    initial_decision = next(
        row for row in certificate["decisions"] if row["state"] == list(initial)
    )
    if (
        not domain.MIN_STEPS[model["level"] - 1] <= best <= domain.MAX_STEPS
        or len(initial_decision["optimal_actions"]) != 1
        or len(initial_decision["committed_actions"]) < 2
        or not any(
            len(row["committed_actions"]) >= 2
            for row in certificate["decisions"]
            if row["state"] != list(initial)
        )
        or len({state[0] for state in graph}) != len(model["names"])
    ):
        raise ValueError("Planning experience does not preserve physical and decision gates")
    ablations = {}
    for mechanic, variant in variants.items():
        distances = previous._distances(
            variant, {state for state in variant if state[0] == len(model["names"]) - 1}
        )
        variant_best = distances.get(initial)
        winners = [
            action
            for action, target in variant[initial]
            if target in distances and distances[target] + 1 == variant_best
        ]
        if (variant_best, winners) == (best, initial_decision["optimal_actions"]):
            raise ValueError(f"The {mechanic} ablation must change the answer or optimum")
        ablations[mechanic] = {"best_steps": variant_best, "optimal_first_actions": winners}
    if not certificate["meets_target"]:
        raise ValueError("Planning experience does not meet the declared episode decision target")
    certificate.update(strategy=profile["strategy"], ablations=ablations, core_graphs=5)
    try:
        coverage = causal_paths.evaluate(model, graph, certificate)
    except causal_paths.CausalCoverageExhausted as exc:
        raise ValueError("All-shortest causal coverage could not be certified") from exc
    if not coverage["all_shortest_routes_linked"]:
        raise ValueError("Every shortest planning episode must contain a causal link")
    certificate["causal_path_coverage"] = coverage
    certificate["decision_judgment"] = judgment.evaluate(
        model, graph, certificate, coverage=coverage, policy_metrics=True
    )
    certificate["target"] = dict(TARGET)
    certificate["scope"] = (
        "Every shortest episode has at least two meaningful decisions and one causal link."
    )
    certificate["version"] = CERTIFICATE_VERSION
    certificate["selection_evidence_scope"] = (
        "Final model quality is certified here; candidate selection diagnostics require "
        "the separate audit_selection replay and do not establish scalar improvement."
    )
    return certificate


def _record(candidate, quality, attempt, origin, parent_attempt, topology=None):
    return {
        "attempt": attempt, "origin": origin, "parent_attempt": parent_attempt,
        "physical_rules": {field: deepcopy(candidate[field]) for field in PHYSICAL_FIELDS},
        "physical_key": variety._physical_key(candidate),
        "structural_key": domain.structural_key(candidate),
        "topology_key": topology if topology is not None else _topology_key(candidate),
        "role_sequence": _role_sequence(candidate, quality),
        "meaningful_role_sequence": _meaningful_roles(candidate, quality),
        **{key: quality[key] for key in (
            "dimensions", "rank", "meets_target", "all_shortest_routes_linked",
            "causal_coverage_status", "decision_judgment")},
    }


def _compact_record(row):
    # Retain raw inputs plus a commitment to every recomputable measurement.
    # The digest is integrity evidence, not authentication or proof by itself.
    return {**{key: row[key] for key in (
        "attempt", "origin", "parent_attempt", "physical_rules")},
        "evidence_sha256": digest(row)}


def expand_comparisons(model):
    """Reconstruct and check compact candidate evidence from physical rules."""
    if model.get("experience_version") != VERSION:
        raise ValueError("Unsupported planning experience version")
    search = model.get("experience_search", {})
    records, budget = search.get("comparisons"), search.get("budget")
    if (search.get("version") != VERSION or search.get("evidence_encoding") != "physical-rules-sha256-v1"
            or not isinstance(records, list) or not 1 <= len(records) <= PROPOSAL_BUDGET
            or type(budget) is not int or not 1 <= budget <= PROPOSAL_BUDGET):
        raise ValueError("Invalid planning selection evidence")
    attempts, rebuilt = set(), []
    for row in records:
        if (not isinstance(row, dict) or set(row) != {
                "attempt", "origin", "parent_attempt", "physical_rules", "evidence_sha256"}
                or type(row["attempt"]) is not int or not 1 <= row["attempt"] <= budget
                or row["attempt"] in attempts or not isinstance(row["physical_rules"], dict)
                or set(row["physical_rules"]) != set(PHYSICAL_FIELDS)):
            raise ValueError("Invalid planning candidate record")
        attempts.add(row["attempt"])
        candidate = {"version": domain.VERSION, "names": list(model["names"]),
                     "level": model["level"], "design_version": variety.VERSION,
                     "strategy": model["strategy"], **deepcopy(row["physical_rules"])}
        _, graph, reason, _ = _assess(candidate)
        if reason is not None:
            raise ValueError("Planning candidate physical gates disagree with replay")
        quality = _quality(candidate, graph)
        verified = _record(candidate, quality, row["attempt"], row["origin"], row["parent_attempt"])
        if compact(_compact_record(verified)) != compact(row):
            raise ValueError("Planning candidate evidence disagrees with independent replay")
        rebuilt.append(verified)
    return rebuilt


def _candidate_policies(model, row):
    candidate = {"version": domain.VERSION, "names": list(model["names"]),
                 "level": model["level"], **row["physical_rules"]}
    return judgment.policy_metrics(candidate, domain._graph(candidate),
                                   row["dimensions"]["solution_steps"], horizons=(2, 5))


def audit_selection(model):
    """Audit the recorded pool and seed, not proposal RNG provenance/completeness."""
    rebuilt = expand_comparisons(model)
    selection = model["experience_search"].get("selection", {})
    seed = selection.get("seed")
    if (selection.get("version") != SELECTION_VERSION or type(seed) is not int
            or not 0 <= seed < 2**32):
        raise ValueError("Invalid planning selection evidence")
    expected = _selection(rebuilt, seed, model["level"], lambda row: _candidate_policies(model, row))
    if (expected is None or compact(expected) != compact(selection)
            or expected["selected_structural_key"] != domain.structural_key(model)):
        raise ValueError("Planning selection disagrees with independent replay")
    if compact(certify(model)["dimensions"]) != compact(expected["selected_dimensions"]):
        raise ValueError("Selected planning quality disagrees with candidate evidence")
    return deepcopy(expected)


def propose(names, level, rng, *, requested_profile=None, budget=PROPOSAL_BUDGET):
    """Assess independent foundations and role-balanced edits within one budget."""
    domain._validate_names(names)
    if type(level) is not int or level not in (1, 2, 3) or len(names) != level + 3:
        raise ValueError("State planning requires level+3 location names")
    if requested_profile is not None and requested_profile not in variety.PROFILES:
        raise ValueError("Unknown state-planning variety profile")
    if type(budget) is not int or not 0 <= budget <= PROPOSAL_BUDGET:
        raise ValueError("Invalid planning experience budget")
    profile = requested_profile if requested_profile is not None else rng.choice(variety.PROFILES)
    diagnostics = {
        "version": VERSION,
        "mode": "bounded-foundation-restarts-and-role-balanced-physical-edits",
        "foundation_version": foundations_v3.VERSION,
        "requested_profile": profile,
        "profile_selection": (
            "explicit" if requested_profile is not None else "uniform-before-synthesis"
        ),
        "budget": budget,
        "model_evaluations": 0,
        "graph_evaluations": 0,
        "accepted_edits": 0,
        "target": dict(TARGET),
        "rank_dimensions": list(previous.RANK_DIMENSIONS),
        "rank_scope": (
            "Lexicographic walk/reference quality; final selection has explicit regret limits."
        ),
        "rejections": dict.fromkeys(
            ("shape", "length", "choices", "mechanics", "profile", "duplicate", "experience"), 0
        ),
        "comparisons": [],
    }
    if budget == 0:
        raise ExperienceExhausted(diagnostics)
    foundations = [rng.choice(group) for group in foundations_v3.FAMILIES[(level, profile)]]
    rng.shuffle(foundations)
    diagnostics.update(foundation=foundations[0], foundation_order=foundations)
    best_quality = None
    seen, candidates, graphs_by_attempt, topology_cache, population = set(), {}, {}, {}, {}
    for attempt in range(budget):
        is_foundation = attempt < len(foundations)
        if is_foundation:
            candidate = _foundation_at(names, level, profile, foundations[attempt])
            parent_attempt = None
        elif population:
            role = rng.choice(sorted(population))
            parent_attempt = rng.choice(population[role])
            candidate = _mutate(candidates[parent_attempt], rng)
        else:
            parent_attempt = None
            candidate = _mutate(_foundation_at(names, level, profile, rng.choice(foundations)), rng)
        diagnostics["model_evaluations"] += 1
        key = variety._physical_key(candidate)
        if key in seen:
            diagnostics["rejections"]["duplicate"] += 1
            continue
        seen.add(key)
        if is_foundation:
            _, graph, reason, graphs, quality = _foundation_analysis(level, profile, foundations[attempt])
        else:
            _, graph, reason, graphs = _assess(candidate)
            quality = None
        diagnostics["graph_evaluations"] += graphs
        if reason:
            diagnostics["rejections"][reason] += 1
            continue
        if quality is None:
            quality = _quality(candidate, graph)
        if not is_foundation:
            diagnostics["accepted_edits"] += 1
        if best_quality is None or quality["rank"] > best_quality["rank"]:
            best_quality = quality
        if not quality["meets_target"]:
            diagnostics["rejections"]["experience"] += 1
        candidates[attempt + 1] = candidate
        graphs_by_attempt[attempt + 1] = graph
        endpoints = tuple(sorted((a, b) for a, b, _, _ in candidate["routes"]))
        if endpoints not in topology_cache:
            topology_cache[endpoints] = _topology_key(candidate)
        record = _record(candidate, quality, attempt + 1,
                         "foundation" if is_foundation else "role-population-revision",
                         parent_attempt, topology_cache[endpoints])
        diagnostics["comparisons"].append(record)
        role = tuple(record["meaningful_role_sequence"])
        pool = population.setdefault(role, [])
        pool.append(attempt + 1)
        # Local quality order does not erase a distinct role from the proposal
        # population. Eligibility and cross-role bounds still govern selection.
        ranks = {row["attempt"]: row["rank"] for row in diagnostics["comparisons"]}
        pool.sort(key=lambda index: (ranks[index], -index), reverse=True)
        del pool[4:]
    def policy_loader(row):
        attempt = row["attempt"]
        return judgment.policy_metrics(candidates[attempt], graphs_by_attempt[attempt],
                                       row["dimensions"]["solution_steps"], horizons=(2, 5))

    selection = _selection(diagnostics["comparisons"], rng.getrandbits(32), level, policy_loader)
    if selection is None:
        diagnostics["best_dimensions"] = best_quality["dimensions"] if best_quality else None
        raise ExperienceExhausted(diagnostics)
    selected = deepcopy(candidates[selection["selected_attempt"]])
    variety._relabel(selected, rng)
    selected["experience_version"] = VERSION
    result = domain.solve(selected)
    certificate = certify(selected)
    if certificate["dimensions"] != selection["selected_dimensions"]:
        raise RuntimeError("Experience quality changed under mechanical relabeling")
    if certificate["solution"] != result["solution"]:
        raise RuntimeError("Experience compiler and physical solver disagree")
    options = [f"move_0_{b}" for a, b, _, _ in selected["routes"] if a == 0] + ["switch_0"]
    rng.shuffle(options)
    diagnostics.update(
        core_graph_evaluations=5,
        graph_evaluations=diagnostics["graph_evaluations"] + 6,
        selection=selection,
        selected_attempt=selection["selected_attempt"],
        selected_dimensions=certificate["dimensions"],
        selected_rank=certificate["rank"],
        selected_physical_key=variety._physical_key(selected),
    )
    diagnostics["comparisons"] = [_compact_record(row) for row in diagnostics["comparisons"]]
    diagnostics["evidence_encoding"] = "physical-rules-sha256-v1"
    selected.update(
        options=options,
        answer_action=result["optimal_first_actions"][0],
        best_steps=result["best_steps"],
        solution=result["solution"],
        experience_search=diagnostics,
    )
    return selected
