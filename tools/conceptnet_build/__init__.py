"""Offline build tool for the ConceptNet vocabulary layer (Step 2) — **not shipped**.

This package lives outside ``src/`` and outside pytest's ``testpaths``, so the engine never
imports it and nothing here can affect run-time behaviour. It runs once, by hand, to regenerate
the frozen artifact ``src/spie/conceptnet_data.py`` from a pinned ConceptNet 5.7 assertions dump.

The pipeline, in order (each stage is a pure, deterministic function of its input):

1. :mod:`.stream` / :mod:`.filters` — stream the ``.gz`` dump line by line (never decompressing
   it whole) and keep only ``/c/en/<single-token>`` endpoints, the six relation kinds the engine
   models, and edges at or above a weight floor.
2. :mod:`.select` — breadth-first from the curated seed words over the *undirected* filtered
   graph out to ``max_hops``, rank the reachable non-curated terms by
   ``(min_hop asc, -total_weight, name asc)`` and take the top ``cap``.
3. :mod:`.prune` — restrict every kept word's out-edges to targets inside
   ``curated | pool`` so the emitted subgraph is **closed** (a dangling relation target would
   raise at import in :func:`spie.concepts._check_integrity`).
4. :mod:`.affordance_rules` — derive the puzzle affordances ConceptNet does not carry, from a
   fixed rule table plus IsA inheritance.
5. :mod:`.gate` — the **exhaustive certify gate**: install the trial vocabulary in memory and run
   every candidate through ``invent`` -> ``validate`` -> ``certify`` -> ``verify`` (plus the
   presentation bijection and the ASCII check) at seeds 0..N-1, keeping only the words that pass.
   Vocabulary growth is therefore gated by the formal solvers, exactly like the rest of the
   engine — the thesis applied to the vocabulary itself.
6. :mod:`.build` — the fixpoint (dropping a word can dangle a kept word's edge, so prune and gate
   alternate until stable) and the CLI.
7. :mod:`.emit` — render the artifact module (wrapped to 100 columns so the generated file passes
   the project's own ``ruff`` configuration) and check the repository ``NOTICE``.

Nothing in this package is imported by :mod:`spie`; the only artifact it produces is a checked-in
Python data literal whose content hash the shipped test suite re-derives.
"""
