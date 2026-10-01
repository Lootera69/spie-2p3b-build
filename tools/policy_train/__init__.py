"""Offline trainer for the SPIE decision model (Item 3, Phase C3) — **not shipped**.

This package lives outside ``src/`` and outside pytest's ``testpaths``, so the engine never
imports it and nothing here can affect run-time behaviour. It runs once, by hand, to regenerate the
frozen artifact ``src/spie/decision_model.py`` — the per-operator ridge weights of a disjoint-LinUCB
"decision model" (Li et al. 2010) fit on a corpus SPIE harvests *from itself*.

The pipeline, in order (each stage is a pure, deterministic function of its input):

1. :mod:`.collect` — a ``CollectorPolicy`` that satisfies :func:`spie.mapelites.evolve`'s policy
   protocol and proposes operators *uniformly at random* from its own seeded RNG (unbiased,
   well-covered labels). Run over a pinned grid of ``(seed-word population, integer seed)`` at fixed
   iterations, it records every ``(parent-context, operator, child-survived)`` triple the search
   produces. The child's survival is the label the unchanged ``validate -> verify -> certify`` gate
   already computed — so the corpus is *gated by the formal solvers*, exactly like everything else.
2. :mod:`.fit` — fold the canonically-sorted corpus into per-operator ridge stats
   ``A = ridge*I + Σ x·xᵀ``, ``b = Σ survived·x`` (the same accumulation
   :class:`spie.context_policy.ContextualBandit` performs online), then round every entry to 6 dp so
   the frozen weights have a byte-stable ``repr`` across platforms.
3. :mod:`.emit` — render the artifact module (wrapped to 100 columns so the generated file passes
   the project's own ``ruff`` configuration) and pin its content hash.

The thesis is untouched. The trained model only *proposes* which operator to try; every child it
proposes still clears the formal gate before it can occupy a cell, and at runtime the frozen model
never learns online (:class:`spie.decision.FrozenProposer` credits nothing back to the operator
weights). Nothing in this package is imported by :mod:`spie`; the only artifact it produces is a
checked-in Python data literal whose content hash the shipped test suite re-derives.
"""
