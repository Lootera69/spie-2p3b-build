"""One-time versioned repair; never changes the revision-14 generator."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src/spie/questions/brainbloom'
p = SRC / 'planning_experience_v5.py'
assert not p.exists()
s = (SRC / 'planning_experience_v4.py').read_text(encoding='utf-8')
s = s.replace('planning-experience-v4', 'planning-experience-v5').replace('planning-experience-core-bfs-v4', 'planning-experience-core-bfs-v5').replace('quality-capped-decision-dependency-v4', 'role-first-quality-capped-dependency-v5')
s = s.replace('                decision_judgment["policy_checks"] = judgment.policy_metrics(\n                    model, graph, quality["dimensions"]["solution_steps"], horizons=(2, 5)\n                )\n', '')
s = s.replace('def _selection(comparisons, seed, level):', 'def _selection(comparisons, seed, level, policy_loader):')
s = s.replace('    best_depth = max(map(depth, bounded))\n    deep = [row for row in bounded if depth(row) == best_depth]\n', '')
s = s.replace('for row in deep', 'for row in bounded').replace('for other in deep', 'for other in bounded')
s = s.replace('    role_signatures = sorted(', '    best_depth = max(map(depth, in_role))\n    in_role = [row for row in in_role if depth(row) == best_depth]\n    role_signatures = sorted(')
s = s.replace('    best_policy = max(_policy_rank(row, level) for row in in_signature)\n    policy_pool = [row for row in in_signature if _policy_rank(row, level) == best_policy]', '''    ranks = {row["attempt"]: _policy_rank(
        {"decision_judgment": {"policy_checks": policy_loader(row)}}, level
    ) for row in in_signature}
    best_policy = max(ranks.values())
    policy_pool = [row for row in in_signature if ranks[row["attempt"]] == best_policy]''')
s = s.replace('bounded costs; prefer linked decision depth by level; inverse development-family ', 'bounded costs; inverse development-family ')
s = s.replace('support for meaningful roles then decision signature; ', 'support for meaningful roles; prefer linked depth within the chosen role; then signature; ')
start = s.index('def audit_selection(model):')
end = s.index('\ndef propose(', start)
s = s[:start] + '''def _record(candidate, quality, attempt, origin, parent_attempt, topology=None):
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

''' + s[end:]
s = s.replace('    seen, candidates, topology_cache, population = set(), {}, {}, {}', '    seen, candidates, graphs_by_attempt, topology_cache, population = set(), {}, {}, {}, {}')
s = s.replace('            _, graph, reason, graphs, quality = deepcopy(\n                _foundation_analysis(level, profile, foundations[attempt])\n            )', '            _, graph, reason, graphs, quality = _foundation_analysis(level, profile, foundations[attempt])')
s = s.replace('        candidates[attempt + 1] = candidate', '        candidates[attempt + 1] = candidate\n        graphs_by_attempt[attempt + 1] = graph')
start = s.index('        record = {', s.index('def propose('))
end = s.index('        diagnostics["comparisons"].append(record)', start)
s = s[:start] + '''        record = _record(candidate, quality, attempt + 1,
                         "foundation" if is_foundation else "role-population-revision",
                         parent_attempt, topology_cache[endpoints])
''' + s[end:]
s = s.replace('    selection = _selection(diagnostics["comparisons"], rng.getrandbits(32), level)', '''    def policy_loader(row):
        attempt = row["attempt"]
        return judgment.policy_metrics(candidates[attempt], graphs_by_attempt[attempt],
                                       row["dimensions"]["solution_steps"], horizons=(2, 5))

    selection = _selection(diagnostics["comparisons"], rng.getrandbits(32), level, policy_loader)''')
s = s.replace('    selected.update(\n', '''    diagnostics["comparisons"] = [_compact_record(row) for row in diagnostics["comparisons"]]
    diagnostics["evidence_encoding"] = "physical-rules-sha256-v1"
    selected.update(
''')
s = s.replace('A caller receives a deep copy; cache occupancy never enters a result or its', 'Callers treat cached analyses as immutable; cache occupancy never enters a result or its')
p.write_text(s, encoding='utf-8')

p = SRC / 'catalog.py'
s = p.read_text(encoding='utf-8').replace('engine_revision: int = 14', 'engine_revision: int = 15').replace('11, 12, 13, 14))', '11, 12, 13, 14, 15))')
p.write_text(s, encoding='utf-8')
p = SRC / 'smart_activities.py'
s = p.read_text(encoding='utf-8').replace('        if request.engine_revision == 14:', '        if request.engine_revision == 15:\n            from .planning_experience_v5 import propose\n        elif request.engine_revision == 14:')
p.write_text(s, encoding='utf-8')
p = SRC / 'planning_scenarios_v5.py'
s = (SRC / 'planning_scenarios_v4.py').read_text(encoding='utf-8').replace('Revision-14', 'Revision-15').replace('planning-episode-v3', 'planning-episode-v4').replace('EXPERIENCE_VERSION = "planning-experience-v4"', 'EXPERIENCE_VERSION = "planning-experience-v5"')
p.write_text(s, encoding='utf-8')
p = SRC / 'planning_episode.py'
s = p.read_text(encoding='utf-8').replace('planning_scenarios_v4, state_planning', 'planning_scenarios_v4, planning_scenarios_v5, state_planning')
s = s.replace('    raise ValueError("Unsupported planning experience version")', '    if version == planning_scenarios_v5.EXPERIENCE_VERSION:\n        return planning_scenarios_v5\n    raise ValueError("Unsupported planning experience version")', 1)
p.write_text(s, encoding='utf-8')
p = SRC / 'state_planning.py'
s = p.read_text(encoding='utf-8').replace('            experience = planning_experience_v4.certify(model)\n', '            experience = planning_experience_v4.certify(model)\n        elif model.get("experience_version") == "planning-experience-v5":\n            from . import planning_experience_v5\n\n            experience = planning_experience_v5.certify(model)\n')
s = s.replace('    if "episode" in proof:\n', '    if model.get("experience_version") == "planning-experience-v5":\n        from .planning_experience_v5 import quiz_stem\n\n        stem = quiz_stem(model)\n    elif "episode" in proof:\n')
p.write_text(s, encoding='utf-8')
print('Created version-15 generator and dispatch; historical versions unchanged.')
