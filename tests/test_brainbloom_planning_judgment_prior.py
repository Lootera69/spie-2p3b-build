"""Static development priors must reproduce fresh compiled foundation analyses."""

from collections import defaultdict
from copy import deepcopy

from spie.questions.brainbloom import planning_experience as experience
from spie.questions.brainbloom import planning_experience_v3 as revision13
from spie.questions.brainbloom import planning_foundations_v3 as foundations
from spie.questions.brainbloom import planning_judgment as judgment
from spie.questions.brainbloom import planning_judgment_prior as prior
from spie.questions.brainbloom import state_planning as domain
from spie.questions.brainbloom import state_planning_variety as variety


def test_every_support_set_matches_fresh_compiled_foundation_decisions():
    signatures, roles = defaultdict(set), defaultdict(set)
    fields = ("capacity", "initial_energy", "initial_gates", "charger", "routes", "switches")
    for family, physical_models in sorted(foundations.FOUNDATIONS.items()):
        level, profile = family
        for values in physical_models:
            model = {
                "version": domain.VERSION, "names": list("ABCDEF")[:level + 3],
                "level": level, "strategy": profile,
                **dict(zip(fields, deepcopy(values), strict=True)),
            }
            # Independent core-IR transitions, rather than the prior script's
            # direct domain graph. No saved source answers or policies are used.
            graph = variety._compiled_graph(model)
            quality = experience._evaluate_graph(model, graph, policies=False)
            report = judgment.evaluate(model, graph, quality)
            signatures[report["decision_signature"]].add(family)
            decisions = {tuple(row["state"]): row for row in quality["decisions"]}
            sequences = []

            def visit(state, sequence, decisions=decisions, graph=graph,
                      model=model, sequences=sequences):
                if state[0] == len(model["names"]) - 1:
                    sequences.append(sequence)
                    return
                row = decisions[state]
                for action, target in graph[state]:
                    if action in row["optimal_actions"]:
                        selected = ((revision13._action_role(model, action),)
                                    if row["meaningful"] else ())
                        visit(target, (*sequence, *selected))

            visit(domain._initial(model), ())
            roles[min(sequences)].add(family)
    assert prior.FAMILY_KEYS == tuple(sorted(foundations.FOUNDATIONS))
    assert prior.DECISION_SIGNATURE_SUPPORT == {
        key: tuple(sorted(values)) for key, values in signatures.items()
    }
    assert prior.MEANINGFUL_ROLE_SUPPORT == {
        key: tuple(sorted(values)) for key, values in roles.items()
    }
    assert prior.FOUNDATION_VERSION == foundations.VERSION
    assert prior.JUDGMENT_VERSION == judgment.VERSION
