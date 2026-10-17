"""Select varied complete episodes with explicit limits on quality regret.

Revision 11's bounded candidate walk and physical gates remain unchanged.
Every shortest route must now contain a witnessed causal link. Selection
protects traps and forced steps, bounds extra reading and length, and samples
distinct roles, topologies and structures without cross-request novelty state.
"""

from __future__ import annotations

from copy import deepcopy
from itertools import permutations
from random import Random

from ...forge.corpus import compact, digest
from . import planning_causal_paths as causal_paths
from . import planning_experience as previous
from . import state_planning as domain
from . import state_planning_variety as variety

VERSION = "planning-experience-v2"
CERTIFICATE_VERSION = "planning-experience-core-bfs-v2"
SELECTION_VERSION = "quality-capped-role-topology-structure-v2"
PROPOSAL_BUDGET = previous.PROPOSAL_BUDGET
TARGET = {**previous.TARGET, "all_shortest_routes_linked": True}
TRADEOFF_DIMENSIONS = (
    "trap_choices_on_optimal_episodes",
    "maximum_forced_steps",
    "rule_rows",
    "solution_steps",
)
REGRET_LIMITS = dict(zip(TRADEOFF_DIMENSIONS, (0, 0, 1, 1), strict=True))
PHYSICAL_FIELDS = (
    "capacity", "initial_energy", "initial_gates", "charger", "routes", "switches"
)
ExperienceExhausted = previous.ExperienceExhausted


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


def _quality(model, graph):
    quality = previous._evaluate_graph(model, graph, policies=False)
    linked, status = None, "not-required"
    if quality["meets_target"]:
        try:
            linked = causal_paths.evaluate(model, graph, quality)["all_shortest_routes_linked"]
            status = "covered" if linked else "uncovered"
        except causal_paths.CausalCoverageExhausted:
            # An exhausted proof is never evidence that every route is linked.
            status = "unknown"
    quality["all_shortest_routes_linked"] = linked
    quality["causal_coverage_status"] = status
    quality["meets_target"] = quality["meets_target"] and linked is True
    return quality


def _selection(comparisons, seed):
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
        row for row in candidates
        if all(
            row["dimensions"][key] <= lexicographic["dimensions"][key] + limit
            for key, limit in REGRET_LIMITS.items()
        )
    ]

    def dominates(other, row):
        a = tuple(other["dimensions"][key] for key in TRADEOFF_DIMENSIONS)
        b = tuple(row["dimensions"][key] for key in TRADEOFF_DIMENSIONS)
        return all(left <= right for left, right in zip(a, b, strict=True)) and a != b

    # A better puzzle in a different map/role must not erase that experience.
    # Within the same group, however, there is no reason to accept worse costs.
    frontier = [
        row for row in bounded
        if not any(
            other["topology_key"] == row["topology_key"]
            and other["role_sequence"] == row["role_sequence"]
            and dominates(other, row)
            for other in bounded
        )
    ]
    roles = sorted({tuple(row["role_sequence"]) for row in frontier})
    rng = Random(seed)
    role = rng.choice(roles)
    in_role = [row for row in frontier if tuple(row["role_sequence"]) == role]
    topologies = sorted({row["topology_key"] for row in in_role})
    topology = rng.choice(topologies)
    in_topology = [row for row in in_role if row["topology_key"] == topology]
    selected = rng.choice(in_topology)
    return {
        "version": SELECTION_VERSION,
        "scope": "Among recorded evaluated candidates meeting every mandatory gate.",
        "seed": seed,
        "tradeoff_dimensions": list(TRADEOFF_DIMENSIONS),
        "tradeoff_direction": "minimize each dimension; no scalar improvement claim",
        "quality_reference": "lexicographic best recorded candidate meeting the hard target",
        "maximum_regret": dict(REGRET_LIMITS),
        "dominance_scope": "within each topology and optimal role sequence",
        "draw_rule": "uniform role sequence, then uniform topology, then uniform structure",
        "eligible_candidates": sum(row["meets_target"] for row in comparisons),
        "distinct_eligible_structures": len(candidates),
        "quality_bounded_structures": len(bounded),
        "frontier_attempts": sorted(row["attempt"] for row in frontier),
        "frontier_structures": len(frontier),
        "frontier_role_sequences": len(roles),
        "frontier_topologies": len({row["topology_key"] for row in frontier}),
        "selected_role_sequence": list(role),
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
            for row in certificate["decisions"] if row["state"] != list(initial)
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
            action for action, target in variant[initial]
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


def audit_selection(model):
    """Compile recorded candidates afresh and replay deduplication and selection.

    This audits the recorded candidate set and seed, not the RNG's provenance or
    completeness of the proposal search. It is deliberately separate from play
    certification so each player action need not re-solve the candidate pool.
    """
    if model.get("experience_version") != VERSION:
        raise ValueError("Unsupported planning experience version")
    search = model.get("experience_search", {})
    selection = search.get("selection", {})
    if search.get("version") != VERSION or selection.get("version") != SELECTION_VERSION:
        raise ValueError("Unsupported planning selection evidence")
    records = search.get("comparisons")
    seed = selection.get("seed")
    budget = search.get("budget")
    if (
        not isinstance(records, list) or not 1 <= len(records) <= PROPOSAL_BUDGET
        or type(budget) is not int or not 1 <= budget <= PROPOSAL_BUDGET
        or type(seed) is not int or not 0 <= seed < 2**32
    ):
        raise ValueError("Invalid planning selection evidence")
    attempts = set()
    rebuilt = []
    for row in records:
        if (
            type(row.get("attempt")) is not int
            or not 1 <= row["attempt"] <= search.get("budget", 0)
            or row["attempt"] in attempts
            or not isinstance(row.get("physical_rules"), dict)
            or set(row["physical_rules"]) != set(PHYSICAL_FIELDS)
        ):
            raise ValueError("Invalid planning candidate record")
        attempts.add(row["attempt"])
        candidate = {
            "version": domain.VERSION,
            "names": list(model["names"]),
            "level": model["level"],
            "design_version": variety.VERSION,
            "strategy": model["strategy"],
            **deepcopy(row["physical_rules"]),
        }
        graph = variety._compiled_graph(candidate)
        quality = _quality(candidate, graph)
        if quality["meets_target"]:
            # Every shortlisted candidate must also satisfy every old gate.
            certify({**candidate, "experience_version": VERSION})
        verified = {
            **row,
            "physical_key": variety._physical_key(candidate),
            "structural_key": domain.structural_key(candidate),
            "topology_key": _topology_key(candidate),
            "role_sequence": _role_sequence(candidate, quality),
            "dimensions": quality["dimensions"],
            "rank": quality["rank"],
            "meets_target": quality["meets_target"],
            "all_shortest_routes_linked": quality["all_shortest_routes_linked"],
            "causal_coverage_status": quality["causal_coverage_status"],
        }
        if compact(verified) != compact(row):
            raise ValueError("Planning candidate evidence disagrees with independent replay")
        rebuilt.append(verified)
    expected = _selection(rebuilt, seed)
    if (
        expected is None or compact(expected) != compact(selection)
        or expected["selected_structural_key"] != domain.structural_key(model)
    ):
        raise ValueError("Planning selection disagrees with independent replay")
    selected = certify(model)
    if compact(selected["dimensions"]) != compact(expected["selected_dimensions"]):
        raise ValueError("Selected planning quality disagrees with candidate evidence")
    return deepcopy(expected)


def propose(names, level, rng, *, requested_profile=None, budget=PROPOSAL_BUDGET):
    """Keep the bounded physical walk and draw from auditable quality limits."""
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
        "mode": "bounded-quality-capped-role-topology-structure-selection",
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
    current, foundation = variety._foundation(names, level, profile, rng)
    template = deepcopy(current)
    other_foundations = list(range(len(variety._FOUNDATIONS[(level, profile)])))
    other_foundations.remove(foundation)
    rng.shuffle(other_foundations)
    foundations = [foundation, *other_foundations]
    diagnostics.update(foundation=foundation, foundation_order=foundations)
    best_model = best_quality = None
    seen, candidates, topology_cache = set(), {}, {}
    for attempt in range(budget):
        is_foundation = attempt < len(foundations)
        if is_foundation:
            candidate = previous._foundation_at(template, foundations[attempt])
        else:
            parent = best_model if best_model is not None and rng.randrange(3) == 0 else current
            candidate = variety._mutate(parent, rng)
        diagnostics["model_evaluations"] += 1
        key = variety._physical_key(candidate)
        if key in seen:
            diagnostics["rejections"]["duplicate"] += 1
            continue
        seen.add(key)
        _, graph, reason, graphs = _assess(candidate)
        diagnostics["graph_evaluations"] += graphs
        if reason:
            diagnostics["rejections"][reason] += 1
            continue
        quality = _quality(candidate, graph)
        if not is_foundation:
            diagnostics["accepted_edits"] += 1
        current = candidate
        if best_quality is None or quality["rank"] > best_quality["rank"]:
            best_model, best_quality = deepcopy(candidate), quality
        if not quality["meets_target"]:
            diagnostics["rejections"]["experience"] += 1
        candidates[attempt + 1] = candidate
        endpoints = tuple(sorted((a, b) for a, b, _, _ in candidate["routes"]))
        if endpoints not in topology_cache:
            topology_cache[endpoints] = _topology_key(candidate)
        record = {
            "attempt": attempt + 1,
            "origin": "foundation" if is_foundation else "revision",
            "physical_rules": {field: deepcopy(candidate[field]) for field in PHYSICAL_FIELDS},
            "physical_key": key,
            "structural_key": domain.structural_key(candidate),
            "topology_key": topology_cache[endpoints],
            "role_sequence": _role_sequence(candidate, quality),
            "dimensions": quality["dimensions"],
            "rank": quality["rank"],
            "meets_target": quality["meets_target"],
            "all_shortest_routes_linked": quality["all_shortest_routes_linked"],
            "causal_coverage_status": quality["causal_coverage_status"],
        }
        diagnostics["comparisons"].append(record)
    selection = _selection(diagnostics["comparisons"], rng.getrandbits(32))
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
    selected.update(
        options=options,
        answer_action=result["optimal_first_actions"][0],
        best_steps=result["best_steps"],
        solution=result["solution"],
        experience_search=diagnostics,
    )
    return selected
