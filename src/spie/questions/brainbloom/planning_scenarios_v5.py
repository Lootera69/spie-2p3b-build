"""Revision-15 presentation: arrival is success; efficiency is optional.

The existing concise scenarios remain unchanged for saved revisions 12 and 13.
This adapter changes the objective and its identity without adding a game rule.
"""

from __future__ import annotations

from ...forge.corpus import digest
from . import planning_scenarios
from .planning_scenarios import consequence, dialogue  # noqa: F401

VERSION = "planning-episode-v4"
EXPERIENCE_VERSION = "planning-experience-v5"


def create(model, source_facts):
    scenario = planning_scenarios.create(model, source_facts)
    robot = scenario["characters"]["robot"]["name"]
    scenario.update(
        version=VERSION,
        id=digest([VERSION, digest(model)]),
        objective=f"Reach {model['names'][-1]} with {robot}. Every legal arrival succeeds. "
        "Optional challenge: use fewer actions.",
    )
    return scenario


def _grammar_model(model):
    # These two public-fact renderers contain revision-13 wording fixes. Preserve
    # those fixes while keeping the actual revision in scenario identity/replay.
    return {**model, "experience_version": "planning-experience-v3"}


def connection_hint(model, current, step, level):
    return planning_scenarios.connection_hint(_grammar_model(model), current, step, level)


def resolution(scenario, model, actions, states):
    return planning_scenarios.resolution(scenario, _grammar_model(model), actions, states)
